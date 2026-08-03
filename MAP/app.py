"""SafeAid Kit 오프라인 지도 변환 검증 웹앱."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from math import isfinite
import mimetypes
import os
from pathlib import Path
from queue import Empty
import shutil
import threading
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from map_engine import (
    DEFAULT_MAX_SNAP_M,
    MapValidationError,
    OfflineMap,
    RouteNotFound,
    SnapOutOfBounds,
    haversine_m,
    load_map_source,
    load_runtime,
)
from gps_service import GpsInputError, GpsService


ROOT = Path(__file__).resolve().parent
STATIC_ROOT = ROOT / "static"
RUNTIME_ROOT = ROOT / "runtime"
UPLOAD_ROOT = RUNTIME_ROOT / "uploads"
ACTIVE_MAP = RUNTIME_ROOT / "active_map.json"
SAMPLE_MAP = ROOT / "sample_data" / "konkuk_walk.graphml"
GPS_REPLAY = ROOT / "sample_data" / "air530_replay.nmea"
MAX_UPLOAD_BYTES = 64 * 1024 * 1024
MAX_JSON_BYTES = 64 * 1024
ALLOWED_SUFFIXES = {".graphml", ".osm", ".xml"}

SAMPLE_POINTS = {
    "current": {"lat": 37.5465126, "lon": 127.0757141},
    "destination": {"lat": 37.5405289551, "lon": 127.0794396497},
}


class MapRegistry:
    """현재 활성 지도와 런타임 파일 교체를 직렬화한다."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._import_status: dict[str, Any] = {
            "state": "idle",
            "stage": "지도 업로드 대기",
            "percent": 0,
        }
        RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
        UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
        self._map = self._load_initial_map()
        self._overview_cache = self._make_overview(self._map)

    def _load_initial_map(self) -> OfflineMap:
        if ACTIVE_MAP.exists():
            try:
                return load_runtime(ACTIVE_MAP)
            except MapValidationError as exc:
                print(f"활성 런타임 지도 복구 실패, 샘플로 전환: {exc}")
        offline_map = load_map_source(SAMPLE_MAP)
        offline_map.write_runtime(ACTIVE_MAP)
        return offline_map

    @staticmethod
    def _make_overview(offline_map: OfflineMap) -> dict[str, Any]:
        result = offline_map.overview()
        if offline_map.source_name == SAMPLE_MAP.name:
            result["suggested_points"] = SAMPLE_POINTS
        result["demo"] = True
        return result

    def overview(self) -> dict[str, Any]:
        with self._lock:
            return self._overview_cache

    def import_status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._import_status)

    def update_import(self, *, state: str, stage: str, percent: int) -> None:
        with self._lock:
            self._import_status = {
                "state": state,
                "stage": stage,
                "percent": max(0, min(100, percent)),
            }

    def fail_import(self, message: str) -> None:
        self.update_import(state="failed", stage=message, percent=0)

    def activate(self, source_path: Path, original_name: str) -> dict[str, Any]:
        safe_name = _safe_filename(original_name)
        try:
            self.update_import(state="processing", stage="그래프 구조와 연결망 검사 중", percent=30)
            converted = load_map_source(source_path)
            converted.source_name = safe_name
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            stored_name = f"{stamp}_{uuid4().hex[:8]}_{safe_name}"
            self.update_import(state="processing", stage="원본 지도 보관 중", percent=60)
            shutil.copy2(source_path, UPLOAD_ROOT / stored_name)
            self.update_import(state="processing", stage="Jetson 런타임 지도 저장 중", percent=75)
            converted.write_runtime(ACTIVE_MAP)
            self.update_import(state="processing", stage="전체 영역 화면 표본 생성 중", percent=90)
            overview = self._make_overview(converted)
            with self._lock:
                self._map = converted
                self._overview_cache = overview
                self._import_status = {
                    "state": "complete",
                    "stage": (
                        f"변환 완료 · 노드 {converted.graph.number_of_nodes():,} · "
                        f"엣지 {converted.graph.number_of_edges():,}"
                    ),
                    "percent": 100,
                }
            return overview
        except Exception as exc:
            self.fail_import(str(exc))
            raise

    def route(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = _point(payload.get("current"), "현재 위치")
        destination = _point(payload.get("destination"), "목적지")
        raw_accuracy = payload.get("accuracy_m", 10)
        accuracy_m = (
            None
            if raw_accuracy is None
            else _finite_number(raw_accuracy, "정확도", 0, 10_000)
        )
        max_snap_m = _finite_number(
            payload.get("max_snap_m", DEFAULT_MAX_SNAP_M),
            "최대 스냅 거리",
            1,
            2_000,
        )
        source = payload.get("source", "demo")
        if source not in {"demo", "sensor"}:
            raise MapValidationError("위치 출처는 demo 또는 sensor여야 합니다")
        sensor_fix = source == "sensor" and payload.get("fix") is True
        satellites = int(_finite_number(payload.get("satellites", 0), "위성 수", 0, 99))
        age_s = _finite_number(payload.get("age_s", 0), "좌표 경과 시간", 0, 86_400)

        with self._lock:
            result = self._map.find_route(
                start_lat=current["lat"],
                start_lon=current["lon"],
                goal_lat=destination["lat"],
                goal_lon=destination["lon"],
                max_snap_m=max_snap_m,
            )

        route_payload = result.as_dict()
        next_point = result.coordinates[1] if len(result.coordinates) > 1 else result.coordinates[0]
        next_wp_m = haversine_m(
            current["lon"], current["lat"], next_point[0], next_point[1]
        )
        on_trail = result.start_snap_m <= max(20.0, accuracy_m or 0.0)
        device_state = {
            "gps": {
                "fix": sensor_fix,
                "lat": current["lat"],
                "lon": current["lon"],
                "acc_m": accuracy_m,
                "satellites": satellites,
                "age_s": age_s,
                "source": source,
            },
            "route": {
                "on_trail": on_trail,
                "offset_m": round(result.start_snap_m, 1),
                "next_wp_m": round(next_wp_m, 1),
            },
        }
        return {
            "demo": source != "sensor",
            "current": current,
            "destination": destination,
            "route": route_payload,
            "device_state": device_state,
            "contract": {
                "map_and_route_computed_by_code": True,
                "llm_may_only_read_device_state": True,
                "llm_route_generation_allowed": False,
            },
        }


def _safe_filename(value: str) -> str:
    basename = Path(unquote(value)).name
    cleaned = "".join(
        character if character.isalnum() or character in {".", "-", "_"} else "_"
        for character in basename
    )
    return cleaned[:120] or "offline_map.graphml"


def _finite_number(value: Any, label: str, lower: float, upper: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise MapValidationError(f"{label} 값이 숫자가 아닙니다") from exc
    if not isfinite(number) or not lower <= number <= upper:
        raise MapValidationError(f"{label} 값이 허용 범위를 벗어났습니다")
    return number


def _point(value: Any, label: str) -> dict[str, float]:
    if not isinstance(value, dict):
        raise MapValidationError(f"{label} 객체가 없습니다")
    return {
        "lat": _finite_number(value.get("lat"), f"{label} 위도", -90, 90),
        "lon": _finite_number(value.get("lon"), f"{label} 경도", -180, 180),
    }


class AppHandler(BaseHTTPRequestHandler):
    """외부 프레임워크 없이 정적 앱과 JSON API를 제공한다."""

    registry: MapRegistry
    gps: GpsService
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - 표준 라이브러리 규약
        path = urlsplit(self.path).path
        if path == "/api/health":
            self._json(HTTPStatus.OK, {"status": "ok", "offline": True})
            return
        if path == "/api/map":
            self._json(HTTPStatus.OK, self.registry.overview())
            return
        if path == "/api/import-status":
            self._json(HTTPStatus.OK, self.registry.import_status())
            return
        if path == "/api/gps":
            self._json(HTTPStatus.OK, self.gps.snapshot())
            return
        if path == "/api/gps/ports":
            self._json(HTTPStatus.OK, {"ports": self.gps.ports()})
            return
        if path == "/api/gps/events":
            self._gps_events()
            return
        if path == "/":
            path = "/index.html"
        self._static(path)

    def do_POST(self) -> None:  # noqa: N802 - 표준 라이브러리 규약
        path = urlsplit(self.path).path
        try:
            if path == "/api/gps/configure":
                payload = self._read_json()
                mode = str(payload.get("mode", "off"))
                port = str(payload.get("port", "")).strip()
                raw_baud = payload.get("baud")
                try:
                    baud = int(raw_baud) if raw_baud not in {None, ""} else None
                except (TypeError, ValueError) as exc:
                    raise GpsInputError("baud는 정수여야 합니다") from exc
                snapshot = self.gps.configure(mode=mode, port=port, baud=baud)
                self._json(HTTPStatus.ACCEPTED, snapshot)
                return
            if path == "/api/gps/stop":
                self._discard_body()
                snapshot = self.gps.configure(mode="off")
                self._json(HTTPStatus.OK, snapshot)
                return
            if path == "/api/maps/import":
                self._import_map()
                return
            if path == "/api/route":
                payload = self._read_json()
                self._json(HTTPStatus.OK, self.registry.route(payload))
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "API 경로가 없습니다"})
        except (GpsInputError, MapValidationError, RouteNotFound, SnapOutOfBounds) as exc:
            self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)})
        except Exception as exc:
            print(f"요청 처리 실패: {exc}")
            self._json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "요청 처리 중 내부 오류가 발생했습니다"},
            )

    def _read_length(self, maximum: int) -> int:
        raw = self.headers.get("Content-Length")
        try:
            length = int(raw or "")
        except ValueError as exc:
            raise MapValidationError("Content-Length가 올바르지 않습니다") from exc
        if length <= 0:
            raise MapValidationError("빈 요청은 처리할 수 없습니다")
        if length > maximum:
            raise MapValidationError(f"파일 크기는 {maximum // (1024 * 1024)}MB 이하여야 합니다")
        return length

    def _read_json(self) -> dict[str, Any]:
        length = self._read_length(MAX_JSON_BYTES)
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MapValidationError("JSON 요청 형식이 올바르지 않습니다") from exc
        if not isinstance(payload, dict):
            raise MapValidationError("JSON 루트는 객체여야 합니다")
        return payload

    def _discard_body(self) -> None:
        raw = self.headers.get("Content-Length", "0")
        try:
            length = int(raw)
        except ValueError as exc:
            raise MapValidationError("Content-Length가 올바르지 않습니다") from exc
        if not 0 <= length <= MAX_JSON_BYTES:
            raise MapValidationError("요청 본문 크기가 허용 범위를 벗어났습니다")
        if length:
            self.rfile.read(length)

    def _import_map(self) -> None:
        length = self._read_length(MAX_UPLOAD_BYTES)
        encoded_name = self.headers.get("X-Filename", "offline_map.graphml")
        filename = _safe_filename(encoded_name)
        if Path(filename).suffix.lower() not in ALLOWED_SUFFIXES:
            raise MapValidationError("지원 형식은 .graphml, .osm, .xml입니다")
        self.registry.update_import(
            state="processing", stage="지도 파일 수신 중", percent=10
        )
        temporary = RUNTIME_ROOT / f"upload-{uuid4().hex}{Path(filename).suffix.lower()}"
        try:
            temporary.write_bytes(self.rfile.read(length))
            self.registry.update_import(
                state="processing", stage="파일 수신 완료 · 변환 준비 중", percent=20
            )
            overview = self.registry.activate(temporary, filename)
        except Exception as exc:
            self.registry.fail_import(str(exc))
            raise
        finally:
            temporary.unlink(missing_ok=True)
        self._json(HTTPStatus.CREATED, overview)

    def _static(self, request_path: str) -> None:
        mapping = {
            "/index.html": STATIC_ROOT / "index.html",
            "/app.js": STATIC_ROOT / "app.js",
            "/styles.css": STATIC_ROOT / "styles.css",
        }
        target = mapping.get(request_path)
        if not target or not target.is_file():
            self._json(HTTPStatus.NOT_FOUND, {"error": "파일이 없습니다"})
            return
        data = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _gps_events(self) -> None:
        subscriber = self.gps.subscribe()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            while True:
                try:
                    payload = subscriber.get(timeout=10.0)
                except Empty:
                    self.wfile.write(b": keep-alive\n\n")
                else:
                    encoded = json.dumps(
                        payload, ensure_ascii=False, separators=(",", ":")
                    ).encode("utf-8")
                    self.wfile.write(b"data: " + encoded + b"\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        finally:
            self.gps.unsubscribe(subscriber)

    def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        if urlsplit(self.path).path == "/api/import-status":
            return
        print(f"{self.address_string()} - {format % args}")


class GpsAppServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], handler: type[AppHandler], gps: GpsService) -> None:
        self.gps = gps
        super().__init__(address, handler)

    def server_close(self) -> None:
        self.gps.close()
        super().server_close()


def build_server(
    host: str,
    port: int,
    gps_configuration: dict[str, Any] | None = None,
) -> ThreadingHTTPServer:
    registry = MapRegistry()
    gps = GpsService(GPS_REPLAY)
    configuration = gps_configuration or {"mode": "off"}
    gps.configure(
        mode=str(configuration.get("mode", "off")),
        port=str(configuration.get("port", "")),
        baud=configuration.get("baud"),
    )
    handler = type(
        "ConfiguredAppHandler",
        (AppHandler,),
        {"registry": registry, "gps": gps},
    )
    return GpsAppServer((host, port), handler, gps)


def main() -> None:
    parser = argparse.ArgumentParser(description="오프라인 지도 변환 검증 웹앱")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument(
        "--gps-mode",
        choices=("off", "replay", "air530", "stm32"),
        default=os.getenv("SAFEAID_GPS_MODE", "off"),
    )
    parser.add_argument("--gps-port", default=os.getenv("SAFEAID_GPS_PORT", ""))
    parser.add_argument(
        "--gps-baud",
        type=int,
        default=int(os.getenv("SAFEAID_GPS_BAUD", "0")),
    )
    args = parser.parse_args()
    server = build_server(
        args.host,
        args.port,
        gps_configuration={
            "mode": args.gps_mode,
            "port": args.gps_port,
            "baud": args.gps_baud or None,
        },
    )
    print(f"지도 검증 앱: http://{args.host}:{args.port}")
    print("종료: Ctrl+C")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
