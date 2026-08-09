"""Air530 NMEA와 STM32 GET_FIX를 받는 오프라인 GNSS 서비스."""

from __future__ import annotations

from dataclasses import dataclass
import json
from math import isfinite
from pathlib import Path
from queue import Empty, Full, Queue
import threading
import time
from typing import Any


FIX_STALE_AFTER_S = 3.0
MAX_SERIAL_LINE_BYTES = 4096
SUPPORTED_MODES = {"off", "replay", "air530", "stm32"}


class GpsInputError(ValueError):
    """GNSS 입력 문장이 계약을 만족하지 않을 때 발생한다."""


def _number(
    value: Any,
    label: str,
    *,
    lower: float | None = None,
    upper: float | None = None,
) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise GpsInputError(f"{label} 값이 숫자가 아닙니다") from exc
    if not isfinite(number):
        raise GpsInputError(f"{label} 값이 유한수가 아닙니다")
    if lower is not None and number < lower:
        raise GpsInputError(f"{label} 값이 허용 범위보다 작습니다")
    if upper is not None and number > upper:
        raise GpsInputError(f"{label} 값이 허용 범위보다 큽니다")
    return number


def _optional_number(
    value: Any,
    label: str,
    *,
    lower: float | None = None,
    upper: float | None = None,
) -> float | None:
    if value is None or value == "":
        return None
    return _number(value, label, lower=lower, upper=upper)


def _nmea_coordinate(raw: str, hemisphere: str, *, latitude: bool) -> float:
    if not raw or hemisphere not in ({"N", "S"} if latitude else {"E", "W"}):
        raise GpsInputError("NMEA 좌표 또는 반구 값이 없습니다")
    value = _number(raw, "NMEA 좌표", lower=0)
    degrees = int(value // 100)
    minutes = value - degrees * 100
    if minutes >= 60:
        raise GpsInputError("NMEA 분 값이 60 이상입니다")
    coordinate = degrees + minutes / 60
    if hemisphere in {"S", "W"}:
        coordinate = -coordinate
    limit = 90 if latitude else 180
    if not -limit <= coordinate <= limit:
        raise GpsInputError("NMEA 좌표가 유효 범위를 벗어났습니다")
    return coordinate


def _nmea_body(line: str) -> str:
    sentence = line.strip()
    if not sentence.startswith("$") or "*" not in sentence:
        raise GpsInputError("NMEA 시작 문자 또는 체크섬이 없습니다")
    body, checksum_text = sentence[1:].rsplit("*", 1)
    if len(checksum_text) < 2:
        raise GpsInputError("NMEA 체크섬 길이가 잘못됐습니다")
    checksum = 0
    for character in body:
        checksum ^= ord(character)
    try:
        expected = int(checksum_text[:2], 16)
    except ValueError as exc:
        raise GpsInputError("NMEA 체크섬이 16진수가 아닙니다") from exc
    if checksum != expected:
        raise GpsInputError("NMEA 체크섬이 일치하지 않습니다")
    return body


class NmeaParser:
    """Air530에서 필요한 GGA·RMC 문장만 엄격하게 읽는다."""

    def parse(self, line: str) -> dict[str, Any] | None:
        body = _nmea_body(line)
        fields = body.split(",")
        sentence_type = fields[0][-3:]
        if sentence_type == "GGA":
            return self._parse_gga(fields)
        if sentence_type == "RMC":
            return self._parse_rmc(fields)
        return None

    @staticmethod
    def _parse_gga(fields: list[str]) -> dict[str, Any]:
        if len(fields) < 10:
            raise GpsInputError("GGA 필드가 부족합니다")
        quality = int(_number(fields[6] or 0, "GGA fix quality", lower=0, upper=8))
        satellites = int(_number(fields[7] or 0, "GGA 위성 수", lower=0, upper=99))
        hdop = _optional_number(fields[8], "GGA HDOP", lower=0)
        result: dict[str, Any] = {
            "fix": quality > 0,
            "utc": fields[1] or None,
            "satellites": satellites,
            "hdop": hdop,
            "acc_m": None,
            "accuracy_kind": "unknown",
            "sentence": "GGA",
        }
        if quality > 0:
            result["lat"] = _nmea_coordinate(fields[2], fields[3], latitude=True)
            result["lon"] = _nmea_coordinate(fields[4], fields[5], latitude=False)
            result["alt_m"] = _optional_number(fields[9], "GGA 고도")
        return result

    @staticmethod
    def _parse_rmc(fields: list[str]) -> dict[str, Any]:
        if len(fields) < 10:
            raise GpsInputError("RMC 필드가 부족합니다")
        fix = fields[2] == "A"
        result: dict[str, Any] = {
            "fix": fix,
            "utc": fields[1] or None,
            "date": fields[9] or None,
            "speed_knots": _optional_number(fields[7], "RMC 속도", lower=0),
            "course_deg": _optional_number(
                fields[8], "RMC 진행각", lower=0, upper=360
            ),
            "acc_m": None,
            "accuracy_kind": "unknown",
            "sentence": "RMC",
        }
        if fix:
            result["lat"] = _nmea_coordinate(fields[3], fields[4], latitude=True)
            result["lon"] = _nmea_coordinate(fields[5], fields[6], latitude=False)
        return result


def parse_stm32_fix(line: str) -> dict[str, Any] | None:
    """STM32 한 줄 JSON 중 `event=fix` 응답을 검증한다."""

    try:
        payload = json.loads(line)
    except json.JSONDecodeError as exc:
        raise GpsInputError("STM32 응답이 JSON이 아닙니다") from exc
    if not isinstance(payload, dict):
        raise GpsInputError("STM32 응답 루트가 객체가 아닙니다")
    if payload.get("event") != "fix":
        return None
    if payload.get("ok") is not True:
        raise GpsInputError(str(payload.get("reason", "STM32 fix 요청 실패")))

    inferred_fix = payload.get("lat") is not None and payload.get("lon") is not None
    fix = payload.get("fix", inferred_fix) is True
    if not fix:
        return {
            "fix": False,
            "last_age_s": _optional_number(
                payload.get("last_age_s"), "마지막 좌표 경과 시간", lower=0
            ),
            "sentence": "STM32_JSON",
        }

    lat = _number(payload.get("lat"), "STM32 위도", lower=-90, upper=90)
    lon = _number(payload.get("lon"), "STM32 경도", lower=-180, upper=180)
    acc_m = _optional_number(payload.get("acc_m"), "STM32 정확도", lower=0)
    satellites = int(
        _number(payload.get("sats", 0), "STM32 위성 수", lower=0, upper=99)
    )
    return {
        "fix": True,
        "lat": lat,
        "lon": lon,
        "acc_m": acc_m,
        "accuracy_kind": "reported" if acc_m is not None else "unknown",
        "satellites": satellites,
        "age_s": _optional_number(payload.get("age_s"), "STM32 좌표 경과 시간", lower=0),
        "sentence": "STM32_JSON",
    }


@dataclass(frozen=True)
class GpsConfiguration:
    mode: str = "off"
    port: str = ""
    baud: int = 0
    replay_path: str = ""


class GpsService:
    """GNSS 수신 스레드와 화면용 이벤트 스트림을 관리한다."""

    def __init__(self, default_replay_path: str | Path) -> None:
        self.default_replay_path = Path(default_replay_path)
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._subscribers: set[Queue[dict[str, Any]]] = set()
        self._configuration = GpsConfiguration()
        self._last_fix: dict[str, Any] | None = None
        self._last_fix_monotonic: float | None = None
        self._current_fix = False
        self._state: dict[str, Any] = {
            "mode": "off",
            "source": "none",
            "connected": False,
            "error": None,
            "received_lines": 0,
            "rejected_lines": 0,
            "reported_last_age_s": None,
        }
        self._nmea_parser = NmeaParser()

    def configure(
        self,
        *,
        mode: str,
        port: str = "",
        baud: int | None = None,
        replay_path: str | Path | None = None,
    ) -> dict[str, Any]:
        if mode not in SUPPORTED_MODES:
            raise GpsInputError(f"지원하지 않는 GPS 모드입니다: {mode}")
        if mode in {"air530", "stm32"} and not port:
            raise GpsInputError("직렬 포트 경로가 필요합니다")
        selected_baud = (
            0 if mode == "off" else int(baud or (115200 if mode == "stm32" else 9600))
        )
        if mode != "off" and selected_baud <= 0:
            raise GpsInputError("baud는 0보다 커야 합니다")
        selected_replay = Path(replay_path or self.default_replay_path)

        self.stop()
        with self._lock:
            self._configuration = GpsConfiguration(
                mode=mode,
                port=port,
                baud=selected_baud,
                replay_path=str(selected_replay),
            )
            self._last_fix = None
            self._last_fix_monotonic = None
            self._current_fix = False
            self._state = {
                "mode": mode,
                "source": mode if mode != "off" else "none",
                "connected": False,
                "error": None,
                "received_lines": 0,
                "rejected_lines": 0,
                "reported_last_age_s": None,
            }
            self._stop_event = threading.Event()

        if mode == "off":
            self._publish()
            return self.snapshot()
        target = self._run_replay if mode == "replay" else self._run_serial
        self._thread = threading.Thread(target=target, name=f"gps-{mode}", daemon=True)
        self._thread.start()
        return self.snapshot()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)
        self._thread = None

    def close(self) -> None:
        self.stop()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            now = time.monotonic()
            result = dict(self._state)
            result["configuration"] = {
                "mode": self._configuration.mode,
                "port": self._configuration.port,
                "baud": self._configuration.baud,
            }
            if self._last_fix and self._last_fix_monotonic is not None:
                local_age = max(0.0, now - self._last_fix_monotonic)
                device_age = self._last_fix.get("device_age_s") or 0.0
                age_s = round(local_age + device_age, 1)
                last_fix = {
                    key: value
                    for key, value in self._last_fix.items()
                    if key != "device_age_s"
                }
                last_fix["age_s"] = age_s
                result["last_fix"] = last_fix
                live = self._current_fix and local_age <= FIX_STALE_AFTER_S
                result["fix"] = live
                if live:
                    result.update(last_fix)
                else:
                    result["last_age_s"] = age_s
            else:
                result["fix"] = False
                result["last_fix"] = None
                if result.get("reported_last_age_s") is not None:
                    result["last_age_s"] = result["reported_last_age_s"]
            result["demo"] = self._configuration.mode == "replay"
            result.pop("reported_last_age_s", None)
            return result

    def subscribe(self) -> Queue[dict[str, Any]]:
        subscriber: Queue[dict[str, Any]] = Queue(maxsize=1)
        with self._lock:
            self._subscribers.add(subscriber)
        subscriber.put_nowait(self.snapshot())
        return subscriber

    def unsubscribe(self, subscriber: Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._subscribers.discard(subscriber)

    def ports(self) -> list[dict[str, str]]:
        try:
            from serial.tools import list_ports  # type: ignore
        except ImportError:
            return []
        return [
            {
                "device": str(port.device),
                "description": str(port.description or ""),
                "hwid": str(port.hwid or ""),
            }
            for port in list_ports.comports()
        ]

    def _run_replay(self) -> None:
        path = Path(self._configuration.replay_path)
        try:
            lines = [
                line.strip()
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            ]
            if not lines:
                raise GpsInputError("NMEA 재생 파일이 비어 있습니다")
            self._set_connection(True, None)
            index = 0
            while not self._stop_event.is_set():
                self._handle_line(lines[index % len(lines)], mode="replay")
                index += 1
                self._stop_event.wait(1.0)
        except Exception as exc:
            self._set_connection(False, str(exc))

    def _run_serial(self) -> None:
        try:
            import serial  # type: ignore
        except ImportError:
            self._set_connection(False, "pyserial이 설치되지 않았습니다")
            return
        configuration = self._configuration
        try:
            with serial.Serial(
                configuration.port,
                configuration.baud,
                timeout=1.0,
            ) as connection:
                self._set_connection(True, None)
                while not self._stop_event.is_set():
                    loop_started = time.monotonic()
                    if configuration.mode == "stm32":
                        connection.write(b"GET_FIX\n")
                        connection.flush()
                    raw = connection.readline(MAX_SERIAL_LINE_BYTES)
                    if raw:
                        self._handle_line(
                            raw.decode("ascii", errors="replace").strip(),
                            mode=configuration.mode,
                        )
                    else:
                        self._publish()
                    if configuration.mode == "stm32":
                        elapsed = time.monotonic() - loop_started
                        self._stop_event.wait(max(0.0, 1.0 - elapsed))
        except Exception as exc:
            self._set_connection(False, str(exc))

    def _handle_line(self, line: str, *, mode: str) -> None:
        with self._lock:
            self._state["received_lines"] += 1
        try:
            parsed = (
                parse_stm32_fix(line)
                if mode == "stm32"
                else self._nmea_parser.parse(line)
            )
        except GpsInputError as exc:
            with self._lock:
                self._state["rejected_lines"] += 1
                self._state["error"] = str(exc)
            self._publish()
            return
        if parsed is None:
            return
        with self._lock:
            self._state["error"] = None
            self._current_fix = parsed.get("fix") is True
            if self._current_fix:
                previous = self._last_fix or {}
                self._last_fix = {
                    "lat": parsed["lat"],
                    "lon": parsed["lon"],
                    "acc_m": parsed.get("acc_m", previous.get("acc_m")),
                    "accuracy_kind": parsed.get(
                        "accuracy_kind", previous.get("accuracy_kind", "unknown")
                    ),
                    "satellites": parsed.get(
                        "satellites", previous.get("satellites")
                    ),
                    "hdop": parsed.get("hdop", previous.get("hdop")),
                    "alt_m": parsed.get("alt_m", previous.get("alt_m")),
                    "utc": parsed.get("utc", previous.get("utc")),
                    "device_age_s": parsed.get("age_s") or 0.0,
                }
                self._last_fix_monotonic = time.monotonic()
                self._state["reported_last_age_s"] = None
            elif parsed.get("last_age_s") is not None:
                reported_age = parsed["last_age_s"]
                self._state["reported_last_age_s"] = reported_age
                if self._last_fix is not None:
                    self._last_fix["device_age_s"] = reported_age
                    self._last_fix_monotonic = time.monotonic()
        self._publish()

    def _set_connection(self, connected: bool, error: str | None) -> None:
        with self._lock:
            self._state["connected"] = connected
            self._state["error"] = error
            if not connected:
                self._current_fix = False
        self._publish()

    def _publish(self) -> None:
        snapshot = self.snapshot()
        with self._lock:
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(snapshot)
            except Full:
                try:
                    subscriber.get_nowait()
                except Empty:
                    pass
                try:
                    subscriber.put_nowait(snapshot)
                except Full:
                    pass
