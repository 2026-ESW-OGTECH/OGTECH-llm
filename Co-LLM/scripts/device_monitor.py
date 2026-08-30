#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""지도 SSE를 감시해 CO·트레일·일조·도착 전이를 먼저 말하는 제품 데몬."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys
import time
from typing import Any, Iterator
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config as C  # noqa: E402
import engines as E  # noqa: E402
from pipeline_gate import exclusive_pipeline  # noqa: E402
from product_assistant import LOCAL_HOSTS, MapApiError  # noqa: E402
from tts_pipeline import TtsPipeline  # noqa: E402


@dataclass(frozen=True)
class ProactiveMessage:
    kind: str
    source_id: str
    text: str


class AlertDetector:
    """동일 상태 반복 전송을 막고, 해제 후 재발할 때만 다시 알린다."""

    def __init__(self) -> None:
        self.active: dict[str, str | None] = {
            "co_alarm": None,
            "trail": None,
            "daylight": None,
            "arrival": None,
        }

    @staticmethod
    def _demo_prefix(device: dict[str, Any]) -> str:
        return "데모 값 기준으로, " if device.get("demo") else ""

    def detect(self, device: dict[str, Any]) -> list[ProactiveMessage]:
        messages: list[ProactiveMessage] = []
        prefix = self._demo_prefix(device)
        co = device.get("co") or {}
        co_key = "alarm" if co.get("alarm") is True and not co.get("stale") else None
        if co_key and self.active["co_alarm"] != co_key:
            ppm = co.get("ppm")
            value = "확인 불가" if ppm is None else str(round(float(ppm)))
            messages.append(
                ProactiveMessage(
                    "co_alarm",
                    "SAFE-PROACTIVE-CO",
                    prefix
                    + f"일산화탄소 경보입니다. 센서 계측은 {value}피피엠입니다. STM32 물리 경보가 작동 중입니다.",
                )
            )
        self.active["co_alarm"] = co_key

        trail = device.get("trail") or {}
        trail_status = trail.get("status")
        trail_key = (
            str(trail_status)
            if trail_status in {"off_trail", "off_trail_estimate"}
            else None
        )
        if trail_key and self.active["trail"] != trail_key:
            text = (
                "트레일 이탈 경보입니다. 지도에서 현재 위치와 GPS 정확도를 확인하세요."
                if trail_key == "off_trail"
                else "트레일 이탈 가능성이 큽니다. GPS 정확도는 확인되지 않았으므로 지도에서 현재 위치를 확인하세요."
            )
            messages.append(
                ProactiveMessage(
                    "trail",
                    "SAFE-PROACTIVE-TRAIL",
                    prefix + text,
                )
            )
        self.active["trail"] = trail_key

        sun = device.get("sun") or {}
        daylight_key = "return_now" if sun.get("status") == "return_now" else None
        if daylight_key and self.active["daylight"] != daylight_key:
            messages.append(
                ProactiveMessage(
                    "daylight",
                    "SAFE-PROACTIVE-DAYLIGHT",
                    prefix + "귀환 권고 시각에 도달했습니다. 베이스캠프 경로를 화면에서 확인하세요.",
                )
            )
        self.active["daylight"] = daylight_key

        navigation = device.get("navigation") or {}
        arrival = navigation.get("arrival") or {}
        target = arrival.get("target") or {}
        arrival_key = (
            str(target.get("id") or target.get("kind") or "target")
            if arrival.get("arrived")
            else None
        )
        if arrival_key and self.active["arrival"] != arrival_key:
            is_basecamp = target.get("id") == "basecamp" or target.get("kind") == "basecamp"
            messages.append(
                ProactiveMessage(
                    "arrival",
                    "SAFE-PROACTIVE-ARRIVAL",
                    prefix
                    + ("베이스캠프에 도착하였습니다." if is_basecamp else "목적지에 도착하였습니다."),
                )
            )
        self.active["arrival"] = arrival_key
        return messages


def device_events(base_url: str) -> Iterator[dict[str, Any]]:
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme != "http" or parsed.hostname not in LOCAL_HOSTS:
        raise MapApiError("장치 이벤트는 로컬 HTTP 주소만 사용할 수 있습니다")
    request = urllib.request.Request(
        base_url.rstrip("/") + "/api/device/events",
        headers={"Accept": "text/event-stream"},
    )
    with urllib.request.urlopen(request, timeout=30.0) as response:
        for raw in response:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            payload = json.loads(line[5:].strip())
            if isinstance(payload, dict):
                yield payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OGTECH 선제 음성 알림 데몬")
    parser.add_argument("--map-url", default=C.MAP_API_URL)
    parser.add_argument("--tts-order", default=",".join(C.TTS_ENGINE_ORDER))
    parser.add_argument("--no-tts", action="store_true", help="문장만 출력하고 합성하지 않음")
    parser.add_argument("--no-play", action="store_true")
    parser.add_argument("--once", action="store_true", help="첫 알림을 처리한 뒤 종료")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    detector = AlertDetector()
    order = tuple(item.strip() for item in args.tts_order.split(",") if item.strip())
    pipeline = TtsPipeline(engine_order=order)
    output = C.RESULT_DIR / "proactive_alert.wav"
    print("선제 알림 감시 시작: CO · 트레일 이탈 · 귀환 권고 · 도착")
    while True:
        try:
            for device in device_events(args.map_url):
                for message in detector.detect(device):
                    print(f"[{message.kind}] {message.text}")
                    if not args.no_tts:
                        with exclusive_pipeline():
                            for result in pipeline.synthesize_sentences(message.text, output):
                                if not args.no_play:
                                    E.play(result.path)
                    if args.once:
                        return 0
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, MapApiError) as exc:
            print(f"지도 이벤트 연결 대기: {exc}", file=sys.stderr)
            time.sleep(2.0)
        except KeyboardInterrupt:
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
