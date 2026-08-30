from __future__ import annotations

import argparse
import contextlib
import io
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import device_monitor  # noqa: E402
from device_monitor import AlertDetector  # noqa: E402


def base_device() -> dict[str, object]:
    return {
        "demo": False,
        "co": {"alarm": False, "stale": False},
        "trail": {"status": "on_trail"},
        "sun": {"status": "scheduled"},
        "navigation": {"arrival": {"arrived": False, "target": None}},
    }


class AlertDetectorTest(unittest.TestCase):
    def test_transition_is_announced_once_and_rearms_after_clear(self) -> None:
        detector = AlertDetector()
        device = base_device()
        device["trail"] = {"status": "off_trail"}

        first = detector.detect(device)
        second = detector.detect(device)
        device["trail"] = {"status": "on_trail"}
        detector.detect(device)
        device["trail"] = {"status": "off_trail"}
        third = detector.detect(device)

        self.assertEqual([item.kind for item in first], ["trail"])
        self.assertEqual(second, [])
        self.assertEqual([item.kind for item in third], ["trail"])

    def test_co_has_priority_when_multiple_events_start_together(self) -> None:
        detector = AlertDetector()
        device = base_device()
        device.update(
            {
                "demo": True,
                "co": {"alarm": True, "stale": False, "ppm": 112.4},
                "trail": {"status": "off_trail"},
                "sun": {"status": "return_now"},
            }
        )

        messages = detector.detect(device)

        self.assertEqual([item.kind for item in messages[:3]], ["co_alarm", "trail", "daylight"])
        self.assertIn("112피피엠", messages[0].text)
        self.assertTrue(all(item.text.startswith("데모 값") for item in messages))

    def test_accuracy_unknown_large_offset_is_spoken_as_possibility(self) -> None:
        detector = AlertDetector()
        device = base_device()
        device["trail"] = {"status": "off_trail_estimate", "offset_m": 72.0}

        messages = detector.detect(device)

        self.assertEqual([item.kind for item in messages], ["trail"])
        self.assertIn("가능성", messages[0].text)
        self.assertIn("정확도는 확인되지", messages[0].text)
        self.assertNotIn("이탈 경보입니다", messages[0].text)

    def test_arrival_phrase_distinguishes_destination_and_basecamp(self) -> None:
        detector = AlertDetector()
        destination = base_device()
        destination["navigation"] = {
            "arrival": {
                "arrived": True,
                "target": {"id": "destination", "kind": "destination"},
            }
        }
        first = detector.detect(destination)
        self.assertEqual(first[0].text, "목적지에 도착하였습니다.")

        cleared = base_device()
        detector.detect(cleared)
        basecamp = base_device()
        basecamp["navigation"] = {
            "arrival": {
                "arrived": True,
                "target": {"id": "basecamp", "kind": "basecamp"},
            }
        }
        second = detector.detect(basecamp)
        self.assertEqual(second[0].text, "베이스캠프에 도착하였습니다.")

    def test_co_alarm_is_not_repeated_while_detector_state_is_retained(self) -> None:
        detector = AlertDetector()
        device = base_device()
        device["co"] = {"alarm": True, "stale": False, "ppm": 250}

        first = detector.detect(device)
        second = detector.detect(device)

        self.assertEqual([item.kind for item in first], ["co_alarm"])
        self.assertEqual(second, [])

    def test_co_alarm_without_numeric_ppm_is_spoken_as_unknown(self) -> None:
        for ppm in (None, "n/a"):
            detector = AlertDetector()
            device = base_device()
            device["co"] = {"alarm": True, "stale": False, "ppm": ppm}

            messages = detector.detect(device)

            self.assertEqual([item.kind for item in messages], ["co_alarm"], ppm)
            self.assertIn("확인 불가", messages[0].text)


class _FakeSpeech:
    path = Path("/nonexistent/alert.wav")


class _FakePipeline:
    def __init__(self, **_kwargs) -> None:
        pass

    def synthesize_sentences(self, _text, _output):
        yield _FakeSpeech()


class DeviceMonitorMainTest(unittest.TestCase):
    def test_playback_failure_keeps_detector_state(self) -> None:
        """재생 실패가 데몬을 죽여 새 detector 가 경보를 재발화하는 루프를 막는다(WORKLOG #28)."""
        co = base_device()
        co["co"] = {"alarm": True, "stale": False, "ppm": 120}
        trail = dict(co)
        trail["trail"] = {"status": "off_trail"}
        batches = iter([[co, co, trail]])

        def fake_events(_url):
            try:
                batch = next(batches)
            except StopIteration:
                raise KeyboardInterrupt  # 두 번째 연결 시도에서 데몬을 끝낸다
            for device in batch:
                yield device

        args = argparse.Namespace(
            map_url="http://127.0.0.1:8790", tts_order="clear",
            no_tts=False, no_play=False, once=False,
        )
        played: list[Path] = []

        def failing_play(path):
            played.append(path)
            raise subprocess.CalledProcessError(1, ["aplay"])

        stderr = io.StringIO()
        with patch.object(device_monitor, "parse_args", return_value=args), \
                patch.object(device_monitor, "device_events", fake_events), \
                patch.object(device_monitor, "TtsPipeline", _FakePipeline), \
                patch.object(device_monitor, "exclusive_pipeline", contextlib.nullcontext), \
                patch.object(device_monitor.E, "play", failing_play), \
                patch.object(device_monitor.time, "sleep", lambda _s: None), \
                contextlib.redirect_stderr(stderr), \
                contextlib.redirect_stdout(io.StringIO()):
            code = device_monitor.main()

        self.assertEqual(code, 0)
        # CO 1회 + 트레일 1회. 두 번째 CO 프레임은 같은 detector 가 중복으로 보지 않는다.
        self.assertEqual(len(played), 2)
        self.assertEqual(stderr.getvalue().count("알림 재생 실패"), 2)


if __name__ == "__main__":
    unittest.main()
