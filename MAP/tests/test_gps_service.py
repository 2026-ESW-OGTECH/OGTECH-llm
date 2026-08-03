"""Air530 NMEA와 STM32 GET_FIX 입력 계약 테스트."""

from __future__ import annotations

from pathlib import Path
import time
import unittest

from gps_service import GpsInputError, GpsService, NmeaParser, parse_stm32_fix


ROOT = Path(__file__).resolve().parents[1]
NMEA_REPLAY = ROOT / "sample_data" / "air530_replay.nmea"


class NmeaParserTest(unittest.TestCase):
    def test_gga_fix_keeps_reported_fields_without_inventing_accuracy(self) -> None:
        result = NmeaParser().parse(
            "$GNGGA,120000.00,3732.7908,N,12704.5428,E,1,10,0.8,35.0,M,0.0,M,,*76"
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result["fix"])
        self.assertAlmostEqual(result["lat"], 37.54651333333333)
        self.assertAlmostEqual(result["lon"], 127.07571333333333)
        self.assertEqual(result["satellites"], 10)
        self.assertEqual(result["hdop"], 0.8)
        self.assertIsNone(result["acc_m"])
        self.assertEqual(result["accuracy_kind"], "unknown")

    def test_gga_no_fix_has_no_coordinate(self) -> None:
        result = NmeaParser().parse(
            "$GNGGA,120004.00,,,,,0,00,99.9,,,,,,*46"
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertFalse(result["fix"])
        self.assertNotIn("lat", result)
        self.assertNotIn("lon", result)

    def test_bad_checksum_is_rejected(self) -> None:
        with self.assertRaises(GpsInputError):
            NmeaParser().parse(
                "$GNGGA,120000.00,3732.7908,N,12704.5428,E,1,10,0.8,35.0,M,0.0,M,,*00"
            )


class Stm32ParserTest(unittest.TestCase):
    def test_live_fix_contract(self) -> None:
        result = parse_stm32_fix(
            '{"ok":true,"event":"fix","lat":37.12345,"lon":128.54321,'
            '"acc_m":6.2,"sats":11,"age_s":2}'
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result["fix"])
        self.assertEqual(result["acc_m"], 6.2)
        self.assertEqual(result["satellites"], 11)
        self.assertEqual(result["accuracy_kind"], "reported")

    def test_no_fix_contract(self) -> None:
        result = parse_stm32_fix(
            '{"ok":true,"event":"fix","fix":false,"last_age_s":840}'
        )

        self.assertEqual(
            result,
            {"fix": False, "last_age_s": 840.0, "sentence": "STM32_JSON"},
        )

    def test_unrelated_event_is_ignored(self) -> None:
        self.assertIsNone(parse_stm32_fix('{"ok":true,"event":"status"}'))


class GpsServiceTest(unittest.TestCase):
    def test_replay_publishes_demo_fix(self) -> None:
        service = GpsService(NMEA_REPLAY)
        try:
            service.configure(mode="replay")
            deadline = time.monotonic() + 2.0
            snapshot = service.snapshot()
            while not snapshot["fix"] and time.monotonic() < deadline:
                time.sleep(0.02)
                snapshot = service.snapshot()

            self.assertTrue(snapshot["connected"])
            self.assertTrue(snapshot["demo"])
            self.assertTrue(snapshot["fix"])
            self.assertIsNone(snapshot["acc_m"])
            self.assertEqual(snapshot["satellites"], 10)
        finally:
            service.close()

    def test_stm32_no_fix_preserves_last_coordinate_and_reported_age(self) -> None:
        service = GpsService(NMEA_REPLAY)
        try:
            service._handle_line(  # 테스트 전용: 직렬 장치 없이 계약 입력을 주입한다.
                '{"ok":true,"event":"fix","lat":37.1,"lon":127.1,'
                '"acc_m":5.0,"sats":9,"age_s":1}',
                mode="stm32",
            )
            service._handle_line(
                '{"ok":true,"event":"fix","fix":false,"last_age_s":840}',
                mode="stm32",
            )
            snapshot = service.snapshot()

            self.assertFalse(snapshot["fix"])
            self.assertAlmostEqual(snapshot["last_fix"]["lat"], 37.1)
            self.assertGreaterEqual(snapshot["last_age_s"], 840.0)
        finally:
            service.close()

    def test_rmc_does_not_erase_recent_gga_satellite_metadata(self) -> None:
        service = GpsService(NMEA_REPLAY)
        try:
            service._handle_line(
                "$GNGGA,120000.00,3732.7908,N,12704.5428,E,1,10,0.8,35.0,M,0.0,M,,*76",
                mode="air530",
            )
            rmc_body = "GNRMC,120000.00,A,3732.7908,N,12704.5428,E,0.0,0.0,030826,,,A"
            checksum = 0
            for character in rmc_body:
                checksum ^= ord(character)
            service._handle_line(f"${rmc_body}*{checksum:02X}", mode="air530")
            snapshot = service.snapshot()

            self.assertEqual(snapshot["satellites"], 10)
            self.assertEqual(snapshot["hdop"], 0.8)
        finally:
            service.close()


if __name__ == "__main__":
    unittest.main()
