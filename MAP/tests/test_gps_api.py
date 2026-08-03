"""로컬 GNSS API와 지도 경로 연계 통합 테스트."""

from __future__ import annotations

from http.client import HTTPConnection
import json
import threading
import time
import unittest

from app import build_server


class GpsApiIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.server = build_server(
            "127.0.0.1",
            0,
            gps_configuration={"mode": "replay"},
        )
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2.0)

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


if __name__ == "__main__":
    unittest.main()
