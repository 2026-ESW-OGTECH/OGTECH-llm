/* SafeAid 시연용 지도 화면 — 1024x600
 *
 * 안전 계약이 이 파일에 거는 제약
 *   1) 방위·거리·경로는 여기(코드)에서 계산합니다. LLM이 만들지 않습니다.
 *   4) GPS 미수신을 위치 추정으로 덮지 않습니다. 마지막 확정 좌표 + 경과 시간만 표시하고
 *      정확도(±m·위성 수)를 항상 같이 표시합니다.
 *   8) 모의 값이 섞여 있으므로 DEMO 배지를 숨기지 않습니다.
 *
 * 데이터는 내장 고정값입니다. 하드웨어 없이 촬영·검토할 수 있어야 하기 때문입니다.
 * 실제 백엔드가 떠 있으면 /api/map 을 먼저 시도하고, 실패하면 내장값으로 돌아갑니다.
 */

"use strict";

// ---------------------------------------------------------------
// 내장 시연 데이터 (건국대 언덕 가정)
// ---------------------------------------------------------------

/* 가로 500 m x 세로 300 m 규모의 언덕. 서쪽 들머리(베이스캠프) -> 동쪽 정상.
 * 종횡비를 캔버스(1024x420, 약 2.4:1)에 맞춰 잡았습니다.
 * 정사각형에 가까운 좌표 범위를 쓰면 지도가 화면 가운데 좁게 갇힙니다. */
const DEMO_MAP = {
  name: "건국대 언덕 · 보행로",
  bounds: { west: 127.0742, east: 127.0808, south: 37.5407, north: 37.5435 },
  trails: [
    // 주능선
    [[127.0749, 37.5415], [127.0761, 37.5418], [127.0772, 37.5421], [127.0783, 37.5423], [127.0794, 37.5426], [127.0801, 37.5428]],
    // 북쪽 갈래
    [[127.0772, 37.5421], [127.0776, 37.5427], [127.078, 37.5431]],
    // 남쪽 우회로
    [[127.0761, 37.5418], [127.0764, 37.5412], [127.0776, 37.5411], [127.0787, 37.5414], [127.0795, 37.5419], [127.0801, 37.5428]],
    // 연결로
    [[127.0783, 37.5423], [127.0785, 37.5418], [127.0787, 37.5414]],
    // 북쪽 능선길
    [[127.078, 37.5431], [127.079, 37.5431], [127.0798, 37.543], [127.0801, 37.5428]],
  ],
  // 등고선. 언덕이라는 것을 그림으로 알리는 장치이며 측량값이 아닙니다.
  contours: [
    { lon: 127.0796, lat: 37.5425, rx: 0.0013, ry: 0.00055 },
    { lon: 127.0798, lat: 37.5426, rx: 0.00085, ry: 0.00036 },
    { lon: 127.0799, lat: 37.5427, rx: 0.00045, ry: 0.00019 },
  ],
  basecamp: { lon: 127.0749, lat: 37.5415 },
  destination: { lon: 127.0801, lat: 37.5428 },
  onTrail: { lon: 127.0783, lat: 37.5423 },
  offTrail: { lon: 127.0782, lat: 37.54263 },
  routeToGoal: [[127.0783, 37.5423], [127.0794, 37.5426], [127.0801, 37.5428]],
  routeToCamp: [[127.0783, 37.5423], [127.0772, 37.5421], [127.0761, 37.5418], [127.0749, 37.5415]],
};

// 촬영 장면. 숫자키로 전환합니다.
const SCENES = {
  1: {
    title: "기본",
    current: "onTrail", fix: true, accuracy: 4.2, satellites: 9, ageSeconds: 1,
    target: null, route: null,
    daylight: 134, sunset: "19:41", batteryDays: 11, batteryPct: 78,
    trailOffset: 0, alert: null,
  },
  2: {
    title: "목적지 지정 · 컷 3",
    current: "onTrail", fix: true, accuracy: 4.2, satellites: 9, ageSeconds: 1,
    target: "destination", route: "routeToGoal",
    daylight: 134, sunset: "19:41", batteryDays: 11, batteryPct: 78,
    trailOffset: 0, alert: null,
  },
  3: {
    title: "일조 시간 경고 · 컷 4",
    current: "onTrail", fix: true, accuracy: 5.1, satellites: 8, ageSeconds: 2,
    target: "destination", route: "routeToGoal",
    daylight: 38, sunset: "19:41", batteryDays: 11, batteryPct: 76,
    trailOffset: 0, alert: "귀환 권고 시각 도달 · 베이스캠프 경로를 확인하세요.",
  },
  4: {
    title: "베이스캠프 역추적 · 컷 5",
    current: "onTrail", fix: true, accuracy: 4.8, satellites: 9, ageSeconds: 1,
    target: "basecamp", route: "routeToCamp",
    daylight: 31, sunset: "19:41", batteryDays: 10, batteryPct: 74,
    trailOffset: 0, alert: null,
  },
  5: {
    title: "트레일 이탈",
    current: "offTrail", fix: true, accuracy: 6.3, satellites: 7, ageSeconds: 1,
    target: "basecamp", route: "routeToCamp",
    daylight: 29, sunset: "19:41", batteryDays: 10, batteryPct: 73,
    trailOffset: 38, alert: "트레일에서 38 m 벗어났습니다.",
  },
  6: {
    title: "GPS 미수신",
    current: "onTrail", fix: false, accuracy: null, satellites: 0, ageSeconds: 47,
    target: "basecamp", route: null,
    daylight: 27, sunset: "19:41", batteryDays: 10, batteryPct: 73,
    trailOffset: null, alert: null,
  },
};

/* konkuk_map.js 가 먼저 로드되면 실제 캠퍼스 보행망을 씁니다.
 * 위의 DEMO_MAP 은 그 파일이 없을 때를 위한 폴백이며, 화면 배치를 검토할 때 씁니다. */
const state = {
  map: window.KONKUK_MAP || DEMO_MAP,
  scene: SCENES[1],
  sceneKey: "1",
  night: false,
};

/* 보행 재생.
 *
 * Air530 이 아직 없어서 현재 위치가 실시간으로 갱신되지 않는다. 촬영에서 필요한 것은
 * "마커가 경로를 따라 움직이고 남은 거리가 줄어드는" 그림 하나뿐이므로, 계산된 경로 위를
 * 보행 속도로 지나가게 한다.
 *
 * 이것은 합성 궤적이며 측위가 아니다. 그래서
 *   - DEMO 배지를 계속 띄운다 (안전 계약 8)
 *   - 정확도·위성 수는 시나리오에 적힌 고정값을 그대로 쓴다. 그럴듯하게 흔들지 않는다
 *   - GPS 가 도착하면 실측 트랙 재생으로 교체한다
 */
const walk = {
  playing: false,
  meters: 0,
  speedMps: 1.3,      // 보통 보행 속도
  lastFrame: 0,
  position: null,
};

const canvas = document.querySelector("#mapCanvas");
const context = canvas.getContext("2d");

// ---------------------------------------------------------------
// 계산 — 방위·거리는 여기서 나옵니다 (안전 계약 1)
// ---------------------------------------------------------------

const EARTH_RADIUS_M = 6371008.8;
const toRad = (deg) => (deg * Math.PI) / 180;
const toDeg = (rad) => (rad * 180) / Math.PI;

function distanceMeters(from, to) {
  const dLat = toRad(to.lat - from.lat);
  const dLon = toRad(to.lon - from.lon);
  const lat1 = toRad(from.lat);
  const lat2 = toRad(to.lat);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(a)));
}

function bearingDegrees(from, to) {
  const lat1 = toRad(from.lat);
  const lat2 = toRad(to.lat);
  const dLon = toRad(to.lon - from.lon);
  const y = Math.sin(dLon) * Math.cos(lat2);
  const x =
    Math.cos(lat1) * Math.sin(lat2) -
    Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLon);
  return (toDeg(Math.atan2(y, x)) + 360) % 360;
}

/** 폴리라인을 따라 meters 만큼 간 지점. 끝을 넘으면 마지막 점을 돌려준다. */
function pointAlong(coordinates, meters) {
  let remaining = meters;
  for (let i = 1; i < coordinates.length; i += 1) {
    const from = { lon: coordinates[i - 1][0], lat: coordinates[i - 1][1] };
    const to = { lon: coordinates[i][0], lat: coordinates[i][1] };
    const segment = distanceMeters(from, to);
    if (remaining <= segment) {
      const ratio = segment === 0 ? 0 : remaining / segment;
      return {
        lon: from.lon + (to.lon - from.lon) * ratio,
        lat: from.lat + (to.lat - from.lat) * ratio,
        done: false,
      };
    }
    remaining -= segment;
  }
  const last = coordinates[coordinates.length - 1];
  return { lon: last[0], lat: last[1], done: true };
}

function pathLengthMeters(coordinates) {
  let total = 0;
  for (let i = 1; i < coordinates.length; i += 1) {
    total += distanceMeters(
      { lon: coordinates[i - 1][0], lat: coordinates[i - 1][1] },
      { lon: coordinates[i][0], lat: coordinates[i][1] }
    );
  }
  return total;
}

// ---------------------------------------------------------------
// 투영
// ---------------------------------------------------------------

function projection() {
  const bounds = state.map.bounds;
  const rect = canvas.getBoundingClientRect();
  const padding = 40;
  const midLat = (bounds.south + bounds.north) / 2;
  const lonFactor = Math.max(0.15, Math.cos(toRad(midLat)));
  const worldWidth = Math.max(1e-9, (bounds.east - bounds.west) * lonFactor);
  const worldHeight = Math.max(1e-9, bounds.north - bounds.south);
  const scale = Math.min(
    (rect.width - padding * 2) / worldWidth,
    (rect.height - padding * 2) / worldHeight
  );
  const offsetX = (rect.width - worldWidth * scale) / 2;
  const offsetY = (rect.height - worldHeight * scale) / 2;
  return {
    rect,
    scale,
    toScreen(lon, lat) {
      return [
        offsetX + (lon - bounds.west) * lonFactor * scale,
        offsetY + (bounds.north - lat) * scale,
      ];
    },
    metersToPixels(meters) {
      return (meters / 111320) * scale;
    },
  };
}

// ---------------------------------------------------------------
// 그리기
// ---------------------------------------------------------------

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function strokePath(coordinates, projector) {
  coordinates.forEach((point, index) => {
    const [x, y] = projector.toScreen(point[0], point[1]);
    if (index === 0) context.moveTo(x, y);
    else context.lineTo(x, y);
  });
}

function drawGrid(width, height) {
  context.strokeStyle = cssVar("--map-grid");
  context.lineWidth = 1;
  context.beginPath();
  for (let x = 0; x < width; x += 48) {
    context.moveTo(x, 0);
    context.lineTo(x, height);
  }
  for (let y = 0; y < height; y += 48) {
    context.moveTo(0, y);
    context.lineTo(width, y);
  }
  context.stroke();
}

function drawContours(projector) {
  context.strokeStyle = cssVar("--map-contour");
  context.lineWidth = 1.5;
  state.map.contours.forEach((ring) => {
    const [cx, cy] = projector.toScreen(ring.lon, ring.lat);
    const [ex] = projector.toScreen(ring.lon + ring.rx, ring.lat);
    const [, ey] = projector.toScreen(ring.lon, ring.lat - ring.ry);
    context.beginPath();
    context.ellipse(cx, cy, Math.abs(ex - cx), Math.abs(ey - cy), 0, 0, Math.PI * 2);
    context.stroke();
  });
}

function drawAccuracyRing(point, meters, projector) {
  if (!point || !meters) return;
  const [x, y] = projector.toScreen(point.lon, point.lat);
  const radius = Math.max(14, projector.metersToPixels(meters));
  context.save();
  context.globalAlpha = 0.14;
  context.fillStyle = cssVar("--green");
  context.beginPath();
  context.arc(x, y, radius, 0, Math.PI * 2);
  context.fill();
  context.globalAlpha = 0.7;
  context.strokeStyle = cssVar("--green");
  context.lineWidth = 2;
  context.stroke();
  context.restore();
}

function drawMarker(point, label, color, projector, shape) {
  if (!point) return;
  const [x, y] = projector.toScreen(point.lon, point.lat);
  context.save();
  context.translate(x, y);
  context.fillStyle = cssVar("--map-bg");
  context.strokeStyle = color;
  context.lineWidth = 4;
  context.beginPath();
  if (shape === "square") {
    context.rect(-11, -11, 22, 22);
  } else if (shape === "triangle") {
    context.moveTo(0, -13);
    context.lineTo(12, 9);
    context.lineTo(-12, 9);
    context.closePath();
  } else {
    context.arc(0, 0, 12, 0, Math.PI * 2);
  }
  context.fill();
  context.stroke();

  context.font = "800 20px 'Malgun Gothic', sans-serif";
  context.textAlign = "center";
  context.lineWidth = 4;
  context.strokeStyle = cssVar("--map-bg");
  context.strokeText(label, 0, -22);
  context.fillStyle = color;
  context.fillText(label, 0, -22);
  context.restore();
}

// 아래 띠는 축척·범례·판독 카드가 쓰므로 방위 표시는 오른쪽 위에 둡니다.
function drawNorthArrow(projector) {
  const x = projector.rect.width - 44;
  const y = 44;
  context.save();
  context.translate(x, y);
  context.strokeStyle = cssVar("--muted");
  context.fillStyle = cssVar("--muted");
  context.lineWidth = 2;
  context.beginPath();
  context.moveTo(0, -18);
  context.lineTo(8, 12);
  context.lineTo(0, 5);
  context.lineTo(-8, 12);
  context.closePath();
  context.fill();
  context.font = "700 15px Consolas, monospace";
  context.textAlign = "center";
  context.fillText("N", 0, -24);
  context.restore();
}

function draw() {
  const rect = canvas.getBoundingClientRect();
  const ratio = Math.min(2, window.devicePixelRatio || 1);
  canvas.width = Math.max(1, Math.round(rect.width * ratio));
  canvas.height = Math.max(1, Math.round(rect.height * ratio));
  context.setTransform(ratio, 0, 0, ratio, 0, 0);

  context.fillStyle = cssVar("--map-bg");
  context.fillRect(0, 0, rect.width, rect.height);
  drawGrid(rect.width, rect.height);

  const projector = projection();
  drawContours(projector);

  context.strokeStyle = cssVar("--map-trail");
  context.lineWidth = 3;
  context.lineJoin = "round";
  context.beginPath();
  state.map.trails.forEach((trail) => strokePath(trail, projector));
  context.stroke();

  const scene = state.scene;
  const current = currentPoint();

  if (scene.route) {
    const coordinates = state.map[scene.route];
    context.lineCap = "round";
    context.strokeStyle = cssVar("--map-bg");
    context.lineWidth = 11;
    context.beginPath();
    strokePath(coordinates, projector);
    context.stroke();
    context.strokeStyle = cssVar("--cyan");
    context.lineWidth = 5;
    context.beginPath();
    strokePath(coordinates, projector);
    context.stroke();
    context.lineCap = "butt";
  }

  drawNorthArrow(projector);

  // 목적지·베이스캠프
  if (scene.target === "destination") {
    drawMarker(state.map.destination, "목적지", cssVar("--cyan"), projector, "square");
  }
  drawMarker(state.map.basecamp, "베이스캠프", cssVar("--amber"), projector, "triangle");

  // 현재 위치. fix가 없으면 녹색을 쓰지 않습니다 (색 규율)
  if (scene.fix) {
    drawAccuracyRing(current, scene.accuracy, projector);
    drawMarker(current, "현재", cssVar("--green"), projector, "circle");
  } else {
    drawMarker(current, "마지막 확정", cssVar("--grey"), projector, "circle");
  }

  updateScaleBar(projector);
}

function updateScaleBar(projector) {
  const candidates = [25, 50, 100, 200, 400];
  let chosen = candidates[0];
  candidates.forEach((meters) => {
    if (projector.metersToPixels(meters) <= 170) chosen = meters;
  });
  document.querySelector("#scaleLabel").textContent = `${chosen} m`;
  document.querySelector("#scaleBar").style.width =
    `${Math.round(projector.metersToPixels(chosen))}px`;
}

// ---------------------------------------------------------------
// 화면 갱신
// ---------------------------------------------------------------

/** 보행 재생 중이면 합성 위치, 아니면 장면에 고정된 지점. */
function currentPoint() {
  return walk.position || state.map[state.scene.current];
}

function walkFrame(timestamp) {
  if (!walk.playing) return;
  const elapsed = walk.lastFrame ? (timestamp - walk.lastFrame) / 1000 : 0;
  walk.lastFrame = timestamp;
  walk.meters += elapsed * walk.speedMps;

  const coordinates = state.map[state.scene.route];
  const next = pointAlong(coordinates, walk.meters);
  walk.position = { lon: next.lon, lat: next.lat };
  if (next.done) stopWalk({ keepPosition: true });

  render();
  if (walk.playing) window.requestAnimationFrame(walkFrame);
}

function startWalk() {
  if (!state.scene.route) return;   // 경로가 없는 장면에서는 걸을 데가 없다
  walk.playing = true;
  walk.meters = 0;
  walk.lastFrame = 0;
  window.requestAnimationFrame(walkFrame);
}

function stopWalk(options) {
  walk.playing = false;
  walk.lastFrame = 0;
  if (!options || !options.keepPosition) {
    walk.position = null;
    walk.meters = 0;
  }
}

function setGlance(id, stateName, value, sub) {
  const element = document.querySelector(id);
  element.dataset.state = stateName;
  element.querySelector("strong").textContent = value;
  element.querySelector(".sub").textContent = sub;
}

function formatDaylight(minutes) {
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return hours > 0 ? `${hours}:${String(rest).padStart(2, "0")}` : `${rest}분`;
}

function render() {
  const scene = state.scene;
  const current = currentPoint();

  // 측위 — 정확도와 위성 수를 항상 같이 표시합니다 (안전 계약 4)
  if (scene.fix) {
    setGlance("#glanceGps", "live", `±${scene.accuracy.toFixed(1)} m`,
      `SAT ${scene.satellites} · AGE ${scene.ageSeconds}s`);
  } else {
    // 위성 수는 fix가 없어도 표시합니다 (안전 계약 4).
    // 문구가 길면 셀에서 잘리므로 셀 폭 256px 안에 들어가게 줄였습니다.
    setGlance("#glanceGps", "none", "미수신",
      `SAT 0 · 마지막 ${scene.ageSeconds}초 전`);
  }

  // 남은 일조 시간 — 45분 미만이면 경고
  const sunCritical = scene.daylight < 45;
  setGlance("#glanceSun", sunCritical ? "warn" : "normal",
    formatDaylight(scene.daylight), `일몰 ${scene.sunset}`);

  setGlance("#glanceBattery", "normal", `${scene.batteryDays}일`,
    `${scene.batteryPct}% · 감시 모드`);

  // 트레일 이탈
  if (scene.trailOffset === null) {
    setGlance("#glanceTrail", "none", "확인 불가", "측위 없음");
  } else if (scene.trailOffset > 0) {
    setGlance("#glanceTrail", "warn", "이탈", `${scene.trailOffset} m 벗어남`);
  } else {
    setGlance("#glanceTrail", "live", "경로 위", "이탈 0 m");
  }

  // 경고 배너. 지도 제목이 배너에 가리지 않도록 has-alert 를 같이 겁니다
  const alertBox = document.querySelector("#alert");
  if (scene.alert) {
    document.querySelector("#alertText").textContent = scene.alert;
    alertBox.hidden = false;
  } else {
    alertBox.hidden = true;
  }
  document.querySelector(".map").classList.toggle("has-alert", Boolean(scene.alert));

  // 방위·거리 — 코드가 계산합니다
  const readout = document.querySelector("#readout");
  const target = scene.target ? state.map[scene.target] : null;
  if (!target) {
    readout.hidden = true;
  } else {
    readout.hidden = false;
    document.querySelector("#readoutLabel").textContent =
      scene.target === "basecamp" ? "BASECAMP" : "DESTINATION";

    if (!scene.fix) {
      // 미수신 상태에서 확정값처럼 그리지 않습니다
      document.querySelector("#readoutBearing").textContent = "—";
      document.querySelector("#readoutDistance").textContent = "—";
      document.querySelector("#readoutSub").textContent =
        "측위 없음. 마지막 확정 좌표 기준으로도 계산하지 않습니다.";
    } else {
      const bearing = bearingDegrees(current, target);
      const straight = distanceMeters(current, target);
      // 걷는 동안에는 남은 거리가 줄어야 한다. 촬영에서 이게 보이는 그림이 필요하다.
      let along = null;
      if (scene.route) {
        const total = pathLengthMeters(state.map[scene.route]);
        along = Math.max(0, total - walk.meters);
      }
      document.querySelector("#readoutBearing").textContent =
        `${String(Math.round(bearing)).padStart(3, "0")}°`;
      document.querySelector("#readoutDistance").textContent =
        `${Math.round(along ?? straight)} m`;
      document.querySelector("#readoutSub").textContent = along
        ? `경로 따라 ${Math.round(along)} m · 직선 ${Math.round(straight)} m`
        : `직선거리 ${Math.round(straight)} m`;
    }
  }

  document.querySelector("#mapName").textContent = state.map.name;
  document.querySelector("#btnDestination")
    .setAttribute("aria-pressed", String(scene.target === "destination"));
  document.querySelector("#btnBasecamp")
    .setAttribute("aria-pressed", String(scene.target === "basecamp"));

  draw();
}

function setScene(key) {
  if (!SCENES[key]) return;
  stopWalk();
  state.sceneKey = key;
  state.scene = SCENES[key];
  render();
}

function setNight(on) {
  state.night = on;
  document.documentElement.dataset.night = on ? "on" : "off";
  document.querySelector("#btnNight").setAttribute("aria-pressed", String(on));
  render();
}

// ---------------------------------------------------------------
// 입력
// ---------------------------------------------------------------

document.querySelector("#btnDestination").addEventListener("click", () => setScene("2"));
document.querySelector("#btnBasecamp").addEventListener("click", () => setScene("4"));
document.querySelector("#btnNight").addEventListener("click", () => setNight(!state.night));
document.querySelector("#btnCheckpoint").addEventListener("click", (event) => {
  const button = event.currentTarget;
  const label = button.querySelector(".label");
  label.textContent = "저장됨";
  window.setTimeout(() => { label.textContent = "체크포인트"; }, 1400);
});

window.addEventListener("keydown", (event) => {
  if (SCENES[event.key]) setScene(event.key);
  else if (event.key === "w" || event.key === "W") {
    if (walk.playing) stopWalk({ keepPosition: true });
    else startWalk();
  } else if (event.key === "n" || event.key === "N") setNight(!state.night);
  else if (event.key === "h" || event.key === "H") {
    const panel = document.querySelector("#director");
    panel.hidden = !panel.hidden;
  }
});

window.addEventListener("resize", () => draw());

/* 구운 캠퍼스 데이터가 없을 때만 백엔드를 찾습니다.
 * konkuk_map.js 는 캔버스 종횡비에 맞춰 잘라 둔 창이라, /api/map 의 캠퍼스 전체 범위로
 * 덮어쓰면 지도가 다시 화면 가운데 좁게 갇힙니다. */
async function tryLiveMap() {
  if (window.KONKUK_MAP) return;
  try {
    const response = await fetch("/api/map", { cache: "no-store" });
    if (!response.ok) return;
    const live = await response.json();
    if (!live || !live.bounds || !Array.isArray(live.edges)) return;
    state.map = Object.assign({}, DEMO_MAP, {
      name: live.name || DEMO_MAP.name,
      bounds: live.bounds,
      trails: live.edges,
      contours: [],
    });
    render();
  } catch (error) {
    // 오프라인·파일 열기에서는 정상입니다. 내장 데이터로 진행합니다.
  }
}

setNight(false);
setScene("1");
tryLiveMap();
