"""Air530 NMEA와 STM32 GET_FIX 입력 계약 테스트."""

from __future__ import annotations

from pathlib import Path
import time
import unittest

from gps_service import (
    GpsConfiguration,
    GpsInputError,
    GpsService,
    NmeaParser,
    encode_stm32_telemetry,
    parse_stm32_button,
    parse_stm32_fix,
    parse_stm32_output,
    parse_stm32_power_event,
)


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
    def test_button_event_requires_crc_and_fixed_enums(self) -> None:
        line = encode_stm32_telemetry(
            {
                "v": 1,
                "event": "button",
                "seq": 7,
                "button": "voice",
                "state": "released",
                "held_ms": 1840,
            }
        )

        self.assertEqual(
            parse_stm32_button(line),
            {
                "version": 1,
                "sequence": 7,
                "button": "voice",
                "state": "released",
                "held_ms": 1840,
            },
        )
        with self.assertRaises(GpsInputError):
            parse_stm32_button(
                encode_stm32_telemetry(
                    {
                        "v": 1,
                        "event": "button",
                        "seq": 7,
                        "button": "shell",
                        "state": "released",
                        "held_ms": 1840,
                    }
                )
            )
        with self.assertRaises(GpsInputError):
            parse_stm32_button(
                '{"v":1,"event":"button","seq":7,"button":"voice",'
                '"state":"released","held_ms":1840}'
            )

    def test_output_ack_requires_crc_and_consistent_level(self) -> None:
        line = encode_stm32_telemetry(
            {
                "v": 1,
                "event": "output",
                "seq": 2,
                "output": "trail",
                "level": "caution",
                "active": True,
                "watchdog_ms": 5000,
            }
        )

        result = parse_stm32_output(line)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["action"], "trail_caution")
        with self.assertRaises(GpsInputError):
            parse_stm32_output(
                encode_stm32_telemetry(
                    {
                        "v": 1,
                        "event": "output",
                        "seq": 3,
                        "output": "trail",
                        "level": "off",
                        "active": True,
                        "watchdog_ms": 5000,
                    }
                )
            )

    def test_power_event_requires_crc_and_consistent_gate_state(self) -> None:
        line = encode_stm32_telemetry(
            {
                "v": 1,
                "event": "power",
                "seq": 4,
                "state": "shutdown_ack",
                "gate_on": True,
                "shutdown_pending": True,
            }
        )

        event = parse_stm32_power_event(line)

        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event["state"], "shutdown_ack")
        cancelled = parse_stm32_power_event(
            encode_stm32_telemetry(
                {
                    "v": 1,
                    "event": "power",
                    "seq": 5,
                    "state": "shutdown_cancelled",
                    "gate_on": True,
                    "shutdown_pending": False,
                }
            )
        )
        self.assertIsNotNone(cancelled)
        assert cancelled is not None
        self.assertEqual(cancelled["state"], "shutdown_cancelled")
        with self.assertRaises(GpsInputError):
            parse_stm32_power_event(
                encode_stm32_telemetry(
                    {
                        "v": 1,
                        "event": "power",
                        "seq": 6,
                        "state": "gate_off",
                        "gate_on": True,
                        "shutdown_pending": False,
                    }
                )
            )

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
    def test_button_event_is_published_without_coordinate_payload(self) -> None:
        service = GpsService(NMEA_REPLAY)
        try:
            line = encode_stm32_telemetry(
                {
                    "v": 1,
                    "event": "button",
                    "seq": 3,
                    "button": "checkpoint",
                    "state": "released",
                    "held_ms": 320,
                }
            )
            service._handle_line(line, mode="stm32")

            buttons = service.snapshot()["hardware_buttons"]
            self.assertEqual(buttons["event_count"], 1)
            self.assertEqual(buttons["last_event"]["button"], "checkpoint")
            self.assertFalse(buttons["coordinates_accepted"])
            self.assertNotIn("lat", buttons["last_event"])
            self.assertNotIn("lon", buttons["last_event"])
        finally:
            service.close()

    def test_stm32_output_queue_accepts_only_fixed_enum_commands(self) -> None:
        class FakeSerial:
            def __init__(self, *, fail_flush_once: bool = False) -> None:
                self.writes: list[bytes] = []
                self.flushes = 0
                self.fail_flush_once = fail_flush_once

            def write(self, payload: bytes) -> None:
                self.writes.append(payload)

            def flush(self) -> None:
                self.flushes += 1
                if self.fail_flush_once:
                    self.fail_flush_once = False
                    raise OSError("test flush failure")

        service = GpsService(NMEA_REPLAY)
        try:
            self.assertFalse(service.request_stm32_output("trail_alert"))
            with self.assertRaises(GpsInputError):
                service.request_stm32_output("ALERT TRAIL ON\nPOWER OFF")

            with service._lock:  # 테스트 전용: 직렬 스레드 없이 STM32 모드만 설정한다.
                service._configuration = GpsConfiguration(
                    mode="stm32", port="test", baud=115200
                )
                service._state["mode"] = "stm32"
                service._state["connected"] = True
            self.assertTrue(service.request_stm32_output("trail_alert"))
            self.assertTrue(service.request_stm32_output("trail_clear"))

            connection = FakeSerial()
            service._drain_stm32_outputs(connection)
            snapshot = service.snapshot()

            self.assertEqual(
                connection.writes,
                [b"ALERT TRAIL OFF\n"],
            )
            self.assertEqual(connection.flushes, 1)
            self.assertEqual(snapshot["hardware_output"]["last_sent"], "trail_clear")
            self.assertEqual(snapshot["hardware_output"]["sent_count"], 1)
            self.assertFalse(snapshot["hardware_output"]["confirmed"])

            self.assertTrue(service.request_stm32_output("trail_caution"))
            failing = FakeSerial(fail_flush_once=True)
            with self.assertRaises(OSError):
                service._drain_stm32_outputs(failing)
            recovered = FakeSerial()
            service._drain_stm32_outputs(recovered)
            self.assertEqual(recovered.writes, [b"ALERT TRAIL CAUTION\n"])
            self.assertEqual(
                service.snapshot()["hardware_output"]["last_sent"],
                "trail_caution",
            )
            service._handle_line(
                encode_stm32_telemetry(
                    {
                        "v": 1,
                        "event": "output",
                        "seq": 8,
                        "output": "trail",
                        "level": "caution",
                        "active": True,
                        "watchdog_ms": 5000,
                    }
                ),
                mode="stm32",
            )
            self.assertTrue(service.snapshot()["hardware_output"]["confirmed"])

            self.assertTrue(service.request_stm32_output("trail_alert"))
            self.assertFalse(service.request_stm32_power_shutdown_ack())
            service._handle_line(
                encode_stm32_telemetry(
                    {
                        "v": 1,
                        "event": "power",
                        "seq": 9,
                        "state": "shutdown_requested",
                        "gate_on": True,
                        "shutdown_pending": True,
                    }
                ),
                mode="stm32",
            )
            self.assertTrue(service.request_stm32_power_shutdown_ack())
            prioritized = FakeSerial()
            service._drain_stm32_outputs(prioritized)
            service._drain_stm32_outputs(prioritized)
            self.assertEqual(
                prioritized.writes,
                [b"POWER OFF ACK\n", b"ALERT TRAIL ON\n"],
            )
            service._handle_line(
                encode_stm32_telemetry(
                    {
                        "v": 1,
                        "event": "power",
                        "seq": 10,
                        "state": "shutdown_ack",
                        "gate_on": True,
                        "shutdown_pending": True,
                    }
                ),
                mode="stm32",
            )
            self.assertTrue(service.request_stm32_power_shutdown_cancel())
            service._drain_stm32_outputs(prioritized)
            self.assertEqual(prioritized.writes[-1], b"POWER OFF CANCEL\n")
            service._handle_line(
                encode_stm32_telemetry(
                    {
                        "v": 1,
                        "event": "power",
                        "seq": 11,
                        "state": "shutdown_cancelled",
                        "gate_on": True,
                        "shutdown_pending": False,
                    }
                ),
                mode="stm32",
            )
            hardware_power = service.snapshot()["hardware_power"]
            self.assertEqual(hardware_power["transaction_phase"], "idle")
            self.assertFalse(hardware_power["cancel_requested"])
        finally:
            service.close()

    def test_lost_shutdown_ack_event_still_allows_fail_safe_cancel(self) -> None:
        class FakeSerial:
            def __init__(self) -> None:
                self.writes: list[bytes] = []

            def write(self, payload: bytes) -> None:
                self.writes.append(payload)

            def flush(self) -> None:
                pass

        service = GpsService(NMEA_REPLAY)
        try:
            with service._lock:  # 테스트 전용: 직렬 스레드 없이 STM32 모드만 설정한다.
                service._configuration = GpsConfiguration(
                    mode="stm32", port="test", baud=115200
                )
                service._state["mode"] = "stm32"
                service._state["connected"] = True
            service._handle_line(
                encode_stm32_telemetry(
                    {
                        "v": 1,
                        "event": "power",
                        "seq": 13,
                        "state": "shutdown_requested",
                        "gate_on": True,
                        "shutdown_pending": True,
                    }
                ),
                mode="stm32",
            )
            self.assertTrue(service.request_stm32_power_shutdown_ack())
            connection = FakeSerial()
            service._drain_stm32_outputs(connection)

            # ACK write 뒤 CRC shutdown_ack 이벤트만 유실된 상황이다.
            self.assertEqual(
                service.snapshot()["hardware_power"]["transaction_phase"],
                "ack_queued",
            )
            self.assertTrue(service.request_stm32_power_shutdown_cancel())
            service._drain_stm32_outputs(connection)

            self.assertEqual(
                connection.writes,
                [b"POWER OFF ACK\n", b"POWER OFF CANCEL\n"],
            )
        finally:
            service.close()

    def test_newer_non_pending_telemetry_overrides_older_pending_event(self) -> None:
        service = GpsService(NMEA_REPLAY)
        try:
            with service._lock:  # 테스트 전용: 직렬 스레드 없이 상태 순서를 만든다.
                service._configuration = GpsConfiguration(
                    mode="stm32", port="test", baud=115200
                )
                service._state["mode"] = "stm32"
                service._state["connected"] = True
            service._handle_line(
                encode_stm32_telemetry(
                    {
                        "v": 1,
                        "event": "power",
                        "seq": 12,
                        "state": "shutdown_requested",
                        "gate_on": True,
                        "shutdown_pending": True,
                    }
                ),
                mode="stm32",
            )
            with service._lock:
                service._last_power = {
                    "jetson_gate_on": True,
                    "shutdown_pending": False,
                }
                service._last_power_monotonic = time.monotonic()

            self.assertFalse(service.request_stm32_power_shutdown_ack())
        finally:
            service.close()

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
