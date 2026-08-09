"""konkuk_walk.graphml -> 시연용 화면이 읽는 konkuk_map.js 를 만든다.

시연 화면은 백엔드 없이 혼자 돌아야 한다. 촬영 일정이 서버 기동에 묶이면 안 되기 때문이다.
그래서 실제 보행망을 미리 한 번 변환해 정적 파일로 굽는다.

경로·거리는 여기서도 map_engine 이 계산한다. 화면 쪽 JS 는 결과를 그리기만 한다.

    cd smartaid-llm/MAP
    .venv/Scripts/python.exe 시연용/build_map_data.py
"""

from __future__ import annotations

import json
import sys
from math import atan2, cos, degrees, radians, sin
from pathlib import Path

MAP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(MAP_DIR))

from map_engine import OfflineMap, haversine_m  # noqa: E402

SOURCE = MAP_DIR / "sample_data" / "konkuk_walk.graphml"
OUTPUT = MAP_DIR / "시연용" / "konkuk_map.js"

# 시연 시나리오 거리. 3분짜리 영상에서 걸어서 보여 줄 수 있는 규모로 잡았다.
DESTINATION_TARGET_M = 180.0
BASECAMP_TARGET_M = 260.0
OFF_TRAIL_M = 38.0

# 캠퍼스 전체를 그대로 넣지 않고 시나리오 주변만 잘라 쓴다. 이유가 둘이다.
#   1) 캠퍼스 전체 종횡비가 0.74(세로형)이라 1024x420(2.44) 캔버스에서 가운데 좁게 갇힌다
#   2) 전체를 넣으면 보행로가 실오라기처럼 가늘어져 7인치에서 판독이 안 된다
CANVAS_ASPECT = 1024 / 420
CROP_MARGIN_M = 70.0


def bearing_deg(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    phi1, phi2 = radians(lat1), radians(lat2)
    dlon = radians(lon2 - lon1)
    y = sin(dlon) * cos(phi2)
    x = cos(phi1) * sin(phi2) - sin(phi1) * cos(phi2) * cos(dlon)
    return (degrees(atan2(y, x)) + 360.0) % 360.0


def angle_gap(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def main() -> int:
    if not SOURCE.exists():
        print(f"FAIL: 원본이 없습니다: {SOURCE}")
        return 1

    offline_map = OfflineMap.from_graphml(SOURCE)
    bounds = offline_map.bounds

    # 연결이 보장된 성분에서만 고른다. 경로가 안 나오는 지점을 시연에 쓸 수 없다.
    component = [
        (node, offline_map.graph.nodes[node])
        for node in offline_map._largest_strong_component  # noqa: SLF001
    ]
    if not component:
        print("FAIL: 강연결 성분이 비어 있습니다")
        return 1

    mid_lon = (bounds["west"] + bounds["east"]) / 2
    mid_lat = (bounds["south"] + bounds["north"]) / 2

    # 현재 위치 = 캠퍼스 한가운데. 지도 어느 쪽으로 움직여도 화면 안에 남는다.
    current_node, current_data = min(
        component,
        key=lambda item: haversine_m(mid_lon, mid_lat, item[1]["x"], item[1]["y"]),
    )
    current = {"lon": current_data["x"], "lat": current_data["y"]}

    def pick_at(target_m: float, prefer_bearing: float):
        """목표 거리에 가깝고 원하는 방위에 가까운 노드.

        방위를 지정하는 이유는 구도 때문이다. 목적지와 베이스캠프가 남북으로 벌어지면
        시나리오를 담는 창이 세로형이 되고, 그것을 2.44 캔버스에 맞추려고 가로를 늘리면
        1.6 km짜리 창이 나온다. 동서 축으로 잡으면 창이 시나리오에 딱 맞는다.
        """
        best = None
        best_score = None
        for node, data in component:
            if node == current_node:
                continue
            distance = haversine_m(current["lon"], current["lat"], data["x"], data["y"])
            heading = bearing_deg(current["lon"], current["lat"], data["x"], data["y"])
            score = abs(distance - target_m) + angle_gap(heading, prefer_bearing) * 2.0
            if best_score is None or score < best_score:
                best_score = score
                best = (node, data)
        return best

    # 동쪽으로 나아가고 서쪽으로 되돌아온다
    _, destination_data = pick_at(DESTINATION_TARGET_M, prefer_bearing=90.0)
    destination = {"lon": destination_data["x"], "lat": destination_data["y"]}

    _, basecamp_data = pick_at(BASECAMP_TARGET_M, prefer_bearing=270.0)
    basecamp = {"lon": basecamp_data["x"], "lat": basecamp_data["y"]}

    to_goal = bearing_deg(current["lon"], current["lat"], destination["lon"], destination["lat"])

    route_to_goal = offline_map.find_route(
        start_lat=current["lat"], start_lon=current["lon"],
        goal_lat=destination["lat"], goal_lon=destination["lon"],
    )
    route_to_camp = offline_map.find_route(
        start_lat=current["lat"], start_lon=current["lon"],
        goal_lat=basecamp["lat"], goal_lon=basecamp["lon"],
    )

    # 트레일 이탈 지점: 진행 방향의 직각으로 OFF_TRAIL_M 만큼 밀어낸 좌표.
    off_bearing = radians((to_goal + 90.0) % 360.0)
    d_lat = (OFF_TRAIL_M * cos(off_bearing)) / 111_320.0
    d_lon = (OFF_TRAIL_M * sin(off_bearing)) / (111_320.0 * cos(radians(current["lat"])))
    off_trail = {"lon": current["lon"] + d_lon, "lat": current["lat"] + d_lat}

    # --- 시나리오를 감싸는 가로형 창 계산 -------------------------------
    focus = [
        (current["lon"], current["lat"]),
        (destination["lon"], destination["lat"]),
        (basecamp["lon"], basecamp["lat"]),
        (off_trail["lon"], off_trail["lat"]),
        *((float(lon), float(lat)) for lon, lat in route_to_goal.coordinates),
        *((float(lon), float(lat)) for lon, lat in route_to_camp.coordinates),
    ]
    center_lat = sum(point[1] for point in focus) / len(focus)
    center_lon = sum(point[0] for point in focus) / len(focus)
    lat_scale = 111_320.0
    lon_scale = 111_320.0 * cos(radians(center_lat))

    half_lat_m = max(abs(point[1] - center_lat) * lat_scale for point in focus) + CROP_MARGIN_M
    half_lon_m = max(abs(point[0] - center_lon) * lon_scale for point in focus) + CROP_MARGIN_M

    # 캔버스 종횡비에 맞춰 부족한 축을 늘린다. 줄이면 시나리오가 화면 밖으로 나간다.
    if half_lon_m / half_lat_m < CANVAS_ASPECT:
        half_lon_m = half_lat_m * CANVAS_ASPECT
    else:
        half_lat_m = half_lon_m / CANVAS_ASPECT

    crop = {
        "west": center_lon - half_lon_m / lon_scale,
        "east": center_lon + half_lon_m / lon_scale,
        "south": center_lat - half_lat_m / lat_scale,
        "north": center_lat + half_lat_m / lat_scale,
    }

    def inside(lon: float, lat: float) -> bool:
        return crop["west"] <= lon <= crop["east"] and crop["south"] <= lat <= crop["north"]

    seen_pairs: set[tuple[str, str]] = set()
    trails: list[list[list[float]]] = []
    for u, v, _, data in offline_map.graph.edges(keys=True, data=True):
        pair = tuple(sorted((str(u), str(v))))
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        coordinates = [
            (float(lon), float(lat))
            for lon, lat in offline_map._edge_coordinates(str(u), str(v), data)  # noqa: SLF001
        ]
        # 한 점이라도 창 안에 있으면 그린다. 창 경계에서 선이 끊겨 보이지 않게 하려는 것이다.
        if any(inside(lon, lat) for lon, lat in coordinates):
            trails.append(coordinates)

    def round_pairs(pairs):
        return [[round(float(lon), 6), round(float(lat), 6)] for lon, lat in pairs]

    def round_point(point):
        return {"lon": round(point["lon"], 6), "lat": round(point["lat"], 6)}

    payload = {
        "name": "건국대학교 캠퍼스 · 보행로",
        "source": SOURCE.name,
        "bounds": {key: round(float(value), 6) for key, value in crop.items()},
        "trails": [round_pairs(edge) for edge in trails],
        "contours": [],
        "basecamp": round_point(basecamp),
        "destination": round_point(destination),
        "onTrail": round_point(current),
        "offTrail": round_point(off_trail),
        "routeToGoal": round_pairs(route_to_goal.coordinates),
        "routeToCamp": round_pairs(route_to_camp.coordinates),
        "computed": {
            "engine": "map_engine.find_route (A*)",
            "toGoalMeters": round(route_to_goal.distance_m, 1),
            "toCampMeters": round(route_to_camp.distance_m, 1),
            "offTrailMeters": OFF_TRAIL_M,
        },
    }

    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    OUTPUT.write_text(
        "/* 자동 생성 파일 — 직접 고치지 마세요.\n"
        " * 만든 명령: .venv/Scripts/python.exe 시연용/build_map_data.py\n"
        f" * 원본: sample_data/{SOURCE.name}\n"
        " * 경로·거리는 map_engine 의 A* 결과이며 LLM이 만든 값이 아닙니다. */\n"
        f"window.KONKUK_MAP = {body};\n",
        encoding="utf-8",
    )

    print(f"source   : {SOURCE.name}")
    print(f"graph    : {offline_map.graph.number_of_nodes()} nodes / "
          f"{offline_map.graph.number_of_edges()} edges")
    print(f"drawn    : {len(trails)} polylines (창 안에 걸친 것만)")
    print(f"window   : {half_lon_m * 2:.0f} m x {half_lat_m * 2:.0f} m  "
          f"aspect {half_lon_m / half_lat_m:.2f} (canvas {CANVAS_ASPECT:.2f})")
    print(f"goal     : {route_to_goal.distance_m:.0f} m along path")
    print(f"basecamp : {route_to_camp.distance_m:.0f} m along path")
    print(f"output   : {OUTPUT.name}  ({OUTPUT.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
