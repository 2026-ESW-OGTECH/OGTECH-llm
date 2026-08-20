from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

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


if __name__ == "__main__":
    unittest.main()
