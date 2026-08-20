"""로컬 GNSS API와 지도 경로 연계 통합 테스트."""

from __future__ import annotations

from http.client import HTTPConnection
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from app import AppHandler, build_server
from gps_service import GpsConfiguration, encode_stm32_telemetry


class GpsApiIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.server = build_server(
            "127.0.0.1",
            0,
            gps_configuration={"mode": "replay"},
            waypoint_path=Path(self.temporary.name) / "waypoints.json",
            force_sample_map=True,
        )
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2.0)
        self.temporary.cleanup()

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
    ) -> tuple[int, dict[str, object]]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {} if body is None else {"Content-Type": "application/json"}
        connection = HTTPConnection("127.0.0.1", self.port, timeout=5.0)
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read().decode("utf-8"))
        finally:
            connection.close()

    def test_replay_fix_routes_without_masquerading_as_live_sensor(self) -> None:
        status, error = self.request(
            "POST",
            "/api/gps/configure",
            {"mode": "air530", "port": "/dev/null", "baud": "invalid"},
        )
        self.assertEqual(status, 422)
        self.assertIn("baud", str(error["error"]))

        deadline = time.monotonic() + 2.0
        gps: dict[str, object] = {}
        while time.monotonic() < deadline:
            status, gps = self.request("GET", "/api/gps")
            if gps.get("fix") is True:
                break
            time.sleep(0.02)
        self.assertEqual(status, 200)
        self.assertTrue(gps["fix"])
        self.assertTrue(gps["demo"])

        _, map_overview = self.request("GET", "/api/map")
        points = map_overview["suggested_points"]
        assert isinstance(points, dict)
        destination = points["destination"]
        status, route = self.request(
            "POST",
            "/api/route",
            {
                "current": {"lat": gps["lat"], "lon": gps["lon"]},
                "destination": destination,
                "accuracy_m": gps.get("acc_m"),
                "satellites": gps.get("satellites", 0),
                "age_s": gps.get("age_s", 0),
                "source": "demo",
                "fix": True,
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(route["contract"]["map_and_route_computed_by_code"])
        self.assertFalse(route["device_state"]["gps"]["fix"])
        self.assertTrue(route["demo"])

        status, stopped = self.request("POST", "/api/gps/stop", {})
        self.assertEqual(status, 200)
        self.assertEqual(stopped["mode"], "off")
        self.assertFalse(stopped["fix"])

    def test_product_screen_and_waypoint_api_use_integrated_device_state(self) -> None:
        deadline = time.monotonic() + 2.0
        device: dict[str, object] = {}
        while time.monotonic() < deadline:
            status, device = self.request("GET", "/api/device")
            gps = device.get("gps")
            if isinstance(gps, dict) and gps.get("fix") is True:
                break
            time.sleep(0.02)
        self.assertEqual(status, 200)
        self.assertIn("environment", device)
        self.assertIn("sun", device)
        self.assertIn("navigation", device)
        self.assertTrue(device["demo"])

        status, saved = self.request(
            "POST",
            "/api/waypoints",
            {"action": "save_current", "kind": "basecamp"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(saved["waypoints"]["selected_target"], "basecamp")
        self.assertTrue(saved["contract"]["map_route_bearing_distance_computed_by_code"])
        self.assertFalse(saved["contract"]["llm_may_generate_coordinates"])

        connection = HTTPConnection("127.0.0.1", self.port, timeout=5.0)
        try:
            connection.request("GET", "/product/")
            response = connection.getresponse()
            html = response.read().decode("utf-8")
        finally:
            connection.close()
        self.assertEqual(response.status, 200)
        self.assertIn("ENVIRONMENT", html)
        self.assertNotIn("demo-badge", html)
        self.assertIn("live_app.js", html)
        self.assertIn("이 장치는 구조 요청 수단이 아닙니다", html)
        self.assertIn("bootAcknowledge", html)
        self.assertIn('id="positionDetails"', html)
        self.assertIn('id="bootChecks"', html)

        status, diagnostics = self.request("GET", "/api/diagnostics")
        self.assertEqual(status, 200)
        self.assertEqual(diagnostics["overall"], "demo")
        checks = {item["id"]: item for item in diagnostics["checks"]}
        self.assertEqual(checks["map"]["state"], "demo")
        self.assertEqual(checks["poi"]["state"], "demo")
        self.assertEqual(checks["clock"]["state"], "waiting")
        self.assertIn("RTC 미연동", checks["clock"]["detail"])
        self.assertEqual(checks["audio"]["state"], "pass")
        self.assertIn("출력 미검사", checks["audio"]["detail"])
        self.assertIn(checks["gps"]["state"], {"demo", "pass"})
        self.assertFalse(diagnostics["contract"]["network_required"])
        self.assertTrue(
            diagnostics["contract"]["rtc_is_not_claimed_without_stm32_evidence"]
        )

    def test_diagnostics_rejects_truncated_wav_header(self) -> None:
        invalid = Path(self.temporary.name) / "invalid.wav"
        invalid.write_bytes(b"RIFF" + (b"\x00" * 42))

        self.assertFalse(AppHandler._wav_ready(invalid))

    def test_button_api_exposes_only_validated_enum_event(self) -> None:
        self.server.gps._handle_line(
            encode_stm32_telemetry(
                {
                    "v": 1,
                    "event": "button",
                    "seq": 2,
                    "button": "voice",
                    "state": "pressed",
                    "held_ms": 0,
                }
            ),
            mode="stm32",
        )

        status, buttons = self.request("GET", "/api/buttons")

        self.assertEqual(status, 200)
        self.assertEqual(buttons["last_event"]["button"], "voice")
        self.assertFalse(buttons["coordinates_accepted"])
        self.assertNotIn("lat", json.dumps(buttons))
        self.assertNotIn("lon", json.dumps(buttons))

        status, error = self.request("POST", "/api/power/shutdown-ack", {})
        self.assertEqual(status, 422)
        self.assertIn("종료 대기", str(error["error"]))
        status, error = self.request("POST", "/api/power/shutdown-cancel", {})
        self.assertEqual(status, 422)
        self.assertIn("ACK", str(error["error"]))

    def test_power_api_only_accepts_confirmed_pending_transaction(self) -> None:
        self.server.gps.stop()
        with self.server.gps._lock:  # 테스트 전용: 직렬 장치 없이 상태 머신만 검증한다.
            self.server.gps._configuration = GpsConfiguration(
                mode="stm32", port="test", baud=115200
            )
            self.server.gps._reset_state("stm32")
            self.server.gps._state["connected"] = True

        requested = encode_stm32_telemetry(
            {
                "v": 1,
                "event": "power",
                "seq": 1,
                "state": "shutdown_requested",
                "gate_on": True,
                "shutdown_pending": True,
            }
        )
        self.server.gps._handle_line(requested, mode="stm32")

        status, ack = self.request("POST", "/api/power/shutdown-ack", {})
        self.assertEqual(status, 200)
        self.assertTrue(ack["queued"])

        acknowledged = encode_stm32_telemetry(
            {
                "v": 1,
                "event": "power",
                "seq": 2,
                "state": "shutdown_ack",
                "gate_on": True,
                "shutdown_pending": True,
            }
        )
        self.server.gps._handle_line(acknowledged, mode="stm32")
        status, cancel = self.request("POST", "/api/power/shutdown-cancel", {})
        self.assertEqual(status, 200)
        self.assertTrue(cancel["queued"])

    def test_voice_map_api_uses_enum_action_and_confirmation(self) -> None:
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            _, device = self.request("GET", "/api/device")
            if isinstance(device.get("gps"), dict) and device["gps"].get("fix") is True:
                break
            time.sleep(0.02)

        status, error = self.request(
            "POST",
            "/api/voice/commands",
            {"action": "route_basecamp", "lat": 37.5, "lon": 127.0},
        )
        self.assertEqual(status, 422)
        self.assertIn("action과 request_id", str(error["error"]))

        status, proposed = self.request(
            "POST", "/api/voice/commands", {"action": "find_nearest_water"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(proposed["status"], "confirmation_required")
        self.assertIsNone(proposed["device"]["waypoints"]["destination"])
        self.assertNotIn("lat", proposed["pending_destination"])

        status, confirmed = self.request(
            "POST", "/api/voice/commands", {"action": "confirm_destination"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(confirmed["status"], "accepted")
        self.assertEqual(
            confirmed["device"]["waypoints"]["destination"]["source"],
            "demo_offline_catalog",
        )
        self.assertTrue(confirmed["device"]["demo"])

        status, night = self.request(
            "POST", "/api/voice/commands", {"action": "night_on"}
        )
        self.assertEqual(status, 200)
        self.assertTrue(night["ui"]["night"])

        status, voice = self.request("GET", "/api/voice")
        self.assertEqual(status, 200)
        self.assertTrue(voice["contract"]["enum_actions_only"])
        self.assertFalse(voice["contract"]["coordinates_accepted_from_voice"])

    def test_video_screen_is_explicit_demo_and_uses_konkuk_pois(self) -> None:
        connection = HTTPConnection("127.0.0.1", self.port, timeout=5.0)
        try:
            connection.request("GET", "/video/")
            response = connection.getresponse()
            html = response.read().decode("utf-8")
        finally:
            connection.close()
        self.assertEqual(response.status, 200)
        self.assertEqual(html.count("DEMO"), 1)
        self.assertIn("video_app.js", html)
        self.assertIn("공학관", html)
        self.assertIn("일감호", html)
        self.assertIn("LOCATION · TIME", html)
        self.assertIn("서울 광진구", html)
        self.assertIn("대한민국", html)
        self.assertIn("CURRENT COORD", html)
        self.assertNotIn("POSITION", html)
        self.assertNotIn("AGE 1s", html)
        self.assertNotIn("±4.2 m", html)
        self.assertNotIn("tag-offline", html)
        self.assertNotIn("map-topline", html)
        self.assertIn("30.0°", html)
        self.assertIn("55% RH", html)
        self.assertIn("btnCheckpoint", html)
        self.assertIn("btnBasecamp", html)
        self.assertIn("btnNight", html)
        self.assertIn("arrivalCard", html)
        self.assertIn('id="readoutLabel">목적지', html)
        self.assertIn("readoutEta", html)
        self.assertIn("readoutRemainingTime", html)
        self.assertIn("30.0°C (86.0°F)", html)
        self.assertIn("CO 농도", html)
        self.assertIn("0 ppm", html)
        self.assertIn("목적지에 도착하였습니다.", html)
        self.assertIn("destination_arrived.wav", html)
        self.assertNotIn("daylight_detail.wav", html)
        self.assertIn('id="basecampAudio"', html)
        self.assertNotIn('id="warningAudio"', html)
        self.assertNotIn("dialogueCard", html)
        self.assertNotIn("나 목마른데 물 마실 곳 찾아줘", html)

        connection = HTTPConnection("127.0.0.1", self.port, timeout=5.0)
        try:
            connection.request("GET", "/video/video_app.js")
            response = connection.getresponse()
            video_app = response.read().decode("utf-8")
        finally:
            connection.close()
        self.assertEqual(response.status, 200)
        self.assertIn('timeZone: "Asia/Seoul"', video_app)
        self.assertIn('second: "2-digit"', video_app)
        self.assertIn("speedMps: 1.4", video_app)
        self.assertIn("function saveCheckpoint()", video_app)
        self.assertIn("function showBasecampRoute()", video_app)
        self.assertIn("async function startAutoDemo()", video_app)
        self.assertIn('event.key === "a" || event.key === "A"', video_app)
        self.assertIn("const AUTO_DEMO_DELAYS_MS", video_app)
        self.assertIn("function routeOnTrails(", video_app)
        self.assertIn("function selectMapDestination(", video_app)
        self.assertIn('canvas.addEventListener("click", selectMapDestination)', video_app)
        self.assertIn("귀환 권고 시각과 베이스캠프 경로를 확인하세요", video_app)
        self.assertNotIn("돌아가세요", video_app)
        self.assertIn('playFixedAudio("arrival")', video_app)
        self.assertIn('playFixedAudio("basecamp")', video_app)
        self.assertIn("베이스캠프가 등록되었습니다.", video_app)
        self.assertIn("베이스캠프 복귀 경로가 설정되었습니다.", video_app)
        self.assertIn("야간 모드가 활성화되었습니다.", video_app)
        self.assertIn("가장 가까운 지점에 호수가 있습니다.", video_app)
        self.assertIn("이곳을 목적지로 지정할까요?", video_app)
        self.assertIn("네, 목적지로 설정되었습니다.", video_app)
        self.assertIn("Base Camp에 도착하였습니다.", video_app)
        self.assertIn("function solarEventUtcHour(", video_app)
        self.assertIn("function solarEventDate(", video_app)
        self.assertIn("function todayDaylight(", video_app)
        self.assertIn("function daylightForDisplay()", video_app)
        self.assertIn("function daylightWarningText()", video_app)
        self.assertIn("function formatDaylightStatus(daylight)", video_app)
        self.assertIn("일몰 시간이 지났습니다. 귀환 권고 시각과 베이스캠프 경로를 확인하세요.", video_app)
        self.assertIn("분 초과", video_app)
        self.assertIn('startsWith("ko")', video_app)
        self.assertIn("Math.ceil(Math.abs(differenceMs) / 60000)", video_app)
        self.assertIn("귀환 권고 시각과 베이스캠프 경로를 확인하세요.", video_app)
        self.assertNotIn("돌아가세요", video_app)
        self.assertNotIn("VIDEO_SUNRISE", video_app)
        self.assertNotIn('sunset: "19:32"', video_app)
        self.assertIn("function formatDaylightRemaining(minutes)", video_app)
        self.assertIn("function setDaylightGlance(scene)", video_app)
        self.assertIn("function formatCoordinate(value)", video_app)
        self.assertIn("function setCurrentCoordinateGlance(current)", video_app)
        self.assertIn('document.querySelector("#locationClock")', video_app)
        self.assertNotIn('document.querySelector("#mapName")', video_app)
        self.assertIn("const etaTimeFormatter", video_app)
        self.assertIn("remainingSeconds / 60", video_app)
        self.assertIn("예상 도착", video_app)
        self.assertIn("CO 전용 · DEMO", video_app)
        self.assertNotIn('"#glanceRoute"', video_app)
        self.assertIn('const targetLabel = scene.target === "basecamp" ? "BASE CAMP" : "목적지"', video_app)
        self.assertIn('document.querySelector("#currentLatitude")', video_app)
        self.assertIn('document.querySelector("#currentLongitude")', video_app)
        self.assertNotIn("LLM 숫자 생성 안 함", video_app)
        self.assertNotIn("지도 엔진 경로", video_app)
        self.assertIn('routeSub: "목적지"', video_app)
        self.assertIn('routeSub: "BASE CAMP"', video_app)
        self.assertNotIn("일감호 목적지", video_app)
        self.assertNotIn("일감호 경로 이동 재생", video_app)
        self.assertNotIn("BASE CAMP 복귀 경로 재생", video_app)

        for audio_name in (
            "destination_set.wav",
            "destination_arrived.wav",
            "return_to_base.wav",
        ):
            connection = HTTPConnection("127.0.0.1", self.port, timeout=5.0)
            try:
                connection.request("GET", f"/video/{audio_name}")
                response = connection.getresponse()
                audio = response.read()
            finally:
                connection.close()
            self.assertEqual(response.status, 200)
            self.assertGreater(len(audio), 1_000)
            self.assertEqual(audio[:4], b"RIFF")

        connection = HTTPConnection("127.0.0.1", self.port, timeout=5.0)
        try:
            connection.request("GET", "/video/daylight_detail.wav")
            response = connection.getresponse()
            response.read()
        finally:
            connection.close()
        self.assertEqual(response.status, 404)

        connection = HTTPConnection("127.0.0.1", self.port, timeout=5.0)
        try:
            connection.request("GET", "/video/video_map.js")
            response = connection.getresponse()
            map_data = response.read().decode("utf-8")
        finally:
            connection.close()
        self.assertEqual(response.status, 200)
        self.assertIn("relation/7885627", map_data)
        self.assertIn("way/369210727", map_data)
        self.assertIn("map_engine.find_route (A*)", map_data)


if __name__ == "__main__":
    unittest.main()
