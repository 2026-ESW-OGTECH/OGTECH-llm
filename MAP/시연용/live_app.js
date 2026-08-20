/* SafeAid 실시간 제품 화면.
 * 센서·경로·일출몰 값은 /api/device가 계산하며 이 파일은 표시와 명시적 지점 선택만 담당합니다.
 */

"use strict";

const canvas = document.querySelector("#mapCanvas");
const context = canvas.getContext("2d", { alpha: false });
const fallbackMap = window.KONKUK_MAP || {
  name: "오프라인 지도 없음",
  source: "none",
  demo: true,
  bounds: { west: 126.99, east: 127.01, south: 36.99, north: 37.01 },
  trails: [],
  contours: [],
};

const state = {
  map: Object.assign({ demo: true }, fallbackMap),
  device: null,
  connected: false,
  selectingDestination: false,
  night: false,
  eventSource: null,
  voiceEventSource: null,
  lastVoiceSequence: 0,
  announcedArrival: null,
  bootLocked: true,
  bootDiagnosticOverall: "checking",
};

let toastTimer = null;
let voiceChipTimer = null;
let alarmTimer = null;
let audioContext = null;

const kstClockFormatter = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function finite(value) {
  return typeof value === "number" && Number.isFinite(value);
}

function formatNumber(value, digits) {
  return finite(value) ? value.toFixed(digits) : "—";
}

function formatAge(value) {
  if (!finite(value)) return "—";
  if (value < 60) return `${Math.round(value)}s`;
  return `${Math.floor(value / 60)}m`;
}

function formatDuration(minutes) {
  if (!finite(minutes)) return "—";
  if (minutes <= 0) return "0분";
  const hours = Math.floor(minutes / 60);
  const rest = Math.round(minutes % 60);
  return hours ? `${hours}:${String(rest).padStart(2, "0")}` : `${rest}분`;
}

function formatDaylight(minutes) {
  if (!finite(minutes)) return "—";
  if (minutes < 0) return `${Math.abs(Math.round(minutes))}분 초과`;
  return formatDuration(minutes);
}

function formatKstClock(value = null) {
  const parsed = value ? new Date(value) : new Date();
  const now = Number.isNaN(parsed.getTime()) ? new Date() : parsed;
  const parts = Object.fromEntries(
    kstClockFormatter.formatToParts(now)
      .filter((part) => part.type !== "literal")
      .map((part) => [part.type, part.value]),
  );
  return `${parts.month}.${parts.day} ${parts.hour}:${parts.minute}:${parts.second} KST`;
}

function formatCoordinate(value, positive, negative) {
  if (!finite(value)) return "—";
  return `${Math.abs(value).toFixed(6)}° ${value >= 0 ? positive : negative}`;
}

function setGlance(selector, stateName, value, sub) {
  const element = document.querySelector(selector);
  element.dataset.state = stateName;
  element.querySelector("strong").textContent = value;
  element.querySelector(".sub").textContent = sub;
}

function showToast(message, durationMs = 1800) {
  const toast = document.querySelector("#statusToast");
  toast.textContent = message;
  toast.hidden = false;
  if (toastTimer) window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => {
    toast.hidden = true;
  }, durationMs);
}

function applyNight(on) {
  state.night = Boolean(on);
  document.documentElement.dataset.night = state.night ? "on" : "off";
  document.querySelector("#btnNight").setAttribute("aria-pressed", String(state.night));
}

function setNight(on) {
  applyNight(on);
  render();
}

function resizeCanvas() {
  const width = Math.max(1, Math.round(canvas.clientWidth));
  const height = Math.max(1, Math.round(canvas.clientHeight));
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
}

function makeProjector(bounds) {
  const padding = 18;
  const middleLatitude = (bounds.south + bounds.north) / 2;
  const latitudeMeters = 111132.0;
  const longitudeMeters = 111320.0 * Math.max(0.01, Math.cos(middleLatitude * Math.PI / 180));
  const mapWidthM = Math.max(1, (bounds.east - bounds.west) * longitudeMeters);
  const mapHeightM = Math.max(1, (bounds.north - bounds.south) * latitudeMeters);
  const scale = Math.min(
    (canvas.width - padding * 2) / mapWidthM,
    (canvas.height - padding * 2) / mapHeightM,
  );
  const renderedWidth = mapWidthM * scale;
  const renderedHeight = mapHeightM * scale;
  const offsetX = (canvas.width - renderedWidth) / 2;
  const offsetY = (canvas.height - renderedHeight) / 2;
  return {
    project(point) {
      return {
        x: offsetX + (point.lon - bounds.west) * longitudeMeters * scale,
        y: offsetY + (bounds.north - point.lat) * latitudeMeters * scale,
      };
    },
    unproject(x, y) {
      return {
        lon: bounds.west + (x - offsetX) / scale / longitudeMeters,
        lat: bounds.north - (y - offsetY) / scale / latitudeMeters,
      };
    },
    metersToPixels(meters) {
      return meters * scale;
    },
    inside(point) {
      return point.lon >= bounds.west && point.lon <= bounds.east
        && point.lat >= bounds.south && point.lat <= bounds.north;
    },
  };
}

function strokePath(coordinates, projector) {
  coordinates.forEach((raw, index) => {
    const point = Array.isArray(raw)
      ? { lon: Number(raw[0]), lat: Number(raw[1]) }
      : raw;
    const screen = projector.project(point);
    if (index === 0) context.moveTo(screen.x, screen.y);
    else context.lineTo(screen.x, screen.y);
  });
}

function drawMarker(point, label, color, projector, shape) {
  if (!point || !finite(Number(point.lat)) || !finite(Number(point.lon))) return;
  if (!projector.inside({ lat: Number(point.lat), lon: Number(point.lon) })) return;
  const screen = projector.project({ lat: Number(point.lat), lon: Number(point.lon) });
  context.save();
  context.fillStyle = color;
  context.strokeStyle = "#071010";
  context.lineWidth = 3;
  context.beginPath();
  if (shape === "triangle") {
    context.moveTo(screen.x, screen.y - 12);
    context.lineTo(screen.x - 11, screen.y + 10);
    context.lineTo(screen.x + 11, screen.y + 10);
    context.closePath();
  } else if (shape === "square") {
    context.rect(screen.x - 9, screen.y - 9, 18, 18);
  } else {
    context.arc(screen.x, screen.y, 10, 0, Math.PI * 2);
  }
  context.fill();
  context.stroke();
  context.font = "700 15px Arial";
  context.textBaseline = "middle";
  const textWidth = context.measureText(label).width;
  const labelX = Math.min(canvas.width - textWidth - 14, screen.x + 15);
  const labelY = Math.max(14, Math.min(canvas.height - 14, screen.y));
  context.fillStyle = "rgba(7,10,10,0.88)";
  context.fillRect(labelX - 4, labelY - 11, textWidth + 8, 22);
  context.fillStyle = color;
  context.fillText(label, labelX, labelY);
  context.restore();
}

function drawAccuracyRing(point, accuracyM, projector) {
  if (!point || !finite(accuracyM) || accuracyM <= 0 || !projector.inside(point)) return;
  const screen = projector.project(point);
  const radius = Math.max(5, Math.min(180, projector.metersToPixels(accuracyM)));
  context.save();
  context.strokeStyle = cssVar("--green");
  context.fillStyle = "rgba(87,212,123,0.10)";
  context.lineWidth = 2;
  context.beginPath();
  context.arc(screen.x, screen.y, radius, 0, Math.PI * 2);
  context.fill();
  context.stroke();
  context.restore();
}

function drawNorthArrow() {
  context.save();
  context.translate(canvas.width - 34, 42);
  context.fillStyle = cssVar("--text");
  context.font = "700 15px Consolas";
  context.textAlign = "center";
  context.fillText("N", 0, -17);
  context.beginPath();
  context.moveTo(0, -11);
  context.lineTo(-7, 9);
  context.lineTo(0, 5);
  context.lineTo(7, 9);
  context.closePath();
  context.fill();
  context.restore();
}

function updateScaleBar(projector) {
  const candidates = [25, 50, 100, 200, 400, 800, 1600];
  let chosen = candidates[0];
  candidates.forEach((meters) => {
    if (projector.metersToPixels(meters) <= 170) chosen = meters;
  });
  document.querySelector("#scaleLabel").textContent = `${chosen} m`;
  document.querySelector("#scaleBar").style.width = `${Math.round(projector.metersToPixels(chosen))}px`;
}

function draw() {
  resizeCanvas();
  context.fillStyle = cssVar("--map-bg");
  context.fillRect(0, 0, canvas.width, canvas.height);
  const projector = makeProjector(state.map.bounds);

  context.save();
  context.strokeStyle = cssVar("--map-grid");
  context.lineWidth = 1;
  for (let x = 0; x < canvas.width; x += 80) {
    context.beginPath(); context.moveTo(x, 0); context.lineTo(x, canvas.height); context.stroke();
  }
  for (let y = 0; y < canvas.height; y += 80) {
    context.beginPath(); context.moveTo(0, y); context.lineTo(canvas.width, y); context.stroke();
  }
  context.restore();

  context.save();
  context.strokeStyle = cssVar("--map-trail");
  context.lineWidth = 3;
  context.lineJoin = "round";
  context.lineCap = "round";
  (state.map.trails || []).forEach((trail) => {
    if (!Array.isArray(trail) || trail.length < 2) return;
    context.beginPath();
    strokePath(trail, projector);
    context.stroke();
  });
  context.restore();

  const device = state.device;
  const route = device && device.navigation && device.navigation.active_route;
  if (route && route.available && Array.isArray(route.coordinates)) {
    context.save();
    context.strokeStyle = cssVar("--cyan");
    context.lineWidth = 7;
    context.lineJoin = "round";
    context.lineCap = "round";
    context.beginPath();
    strokePath(route.coordinates, projector);
    context.stroke();
    context.restore();
  }

  if (device) {
    const gps = device.gps || {};
    const current = gps.fix && state.connected
      ? { lat: Number(gps.lat), lon: Number(gps.lon) }
      : gps.last_fix
        ? { lat: Number(gps.last_fix.lat), lon: Number(gps.last_fix.lon) }
        : null;
    const waypoints = device.waypoints || {};
    if (waypoints.destination) drawMarker(waypoints.destination, "목적지", cssVar("--cyan"), projector, "square");
    if (waypoints.basecamp) drawMarker(waypoints.basecamp, "베이스캠프", cssVar("--amber"), projector, "triangle");
    if (gps.fix && state.connected && current) {
      drawAccuracyRing(current, Number(gps.acc_m), projector);
      drawMarker(current, "현재", gps.demo ? cssVar("--cyan") : cssVar("--green"), projector, "circle");
    } else if (current) {
      drawMarker(current, "마지막 확정", cssVar("--grey"), projector, "circle");
    }
  }

  drawNorthArrow();
  updateScaleBar(projector);
  return projector;
}

function renderGps(device) {
  const gps = device.gps || {};
  if (!state.connected) {
    setGlance("#glanceGps", "none", gps.mode === "off" ? "연동 전" : "연결 끊김", "SAT — · AGE —");
    return;
  }
  if (gps.fix) {
    const accuracy = finite(gps.acc_m) ? `±${gps.acc_m.toFixed(1)} m` : "±—";
    setGlance(
      "#glanceGps",
      gps.demo ? "normal" : "live",
      accuracy,
      `SAT ${gps.satellites ?? "—"} · AGE ${formatAge(gps.age_s)}`,
    );
  } else {
    setGlance(
      "#glanceGps",
      "none",
      "미수신",
      `SAT ${gps.last_fix && gps.last_fix.satellites != null ? gps.last_fix.satellites : "—"} · 마지막 ${formatAge(gps.last_age_s)}`,
    );
  }
}

function renderEnvironment(device) {
  const env = device.environment || {};
  const co = device.co || {};
  if (!state.connected || (!env.valid && !env.pressure_valid && !co.valid)) {
    const value = co.warming_up ? "CO 예열" : "연동 전";
    setGlance("#glanceEnv", "none", value, "RH — · P — · CO —");
    return;
  }
  let stateName = device.demo ? "normal" : "live";
  if (co.level === "warning") stateName = "caution";
  if (co.alarm) stateName = "warn";
  const temp = env.valid ? `${formatNumber(env.temp_c, 1)}°C` : "—";
  const humidity = env.valid ? `${Math.round(env.humidity_pct)}%` : "—";
  const trendMark = { rising: "↑", steady: "→", falling: "↓" }[env.press_trend] || "";
  const pressure = env.pressure_valid && finite(env.press_hpa)
    ? `${Math.round(env.press_hpa)}${trendMark}`
    : "—";
  const coValue = co.valid && finite(co.ppm) ? `${formatNumber(co.ppm, 1)}` : co.warming_up ? "예열" : "—";
  setGlance("#glanceEnv", stateName, temp, `RH ${humidity} · P ${pressure} · CO ${coValue}`);
}

function renderPositionDetails(device) {
  const element = document.querySelector("#positionDetails");
  const gps = device.gps || {};
  const deviceClock = device.clock || {};
  const clock = `${formatKstClock(deviceClock.iso_utc)} · ${deviceClock.confirmed ? "RTC" : "SYS"}`;
  if (state.connected && gps.fix) {
    const accuracy = finite(gps.acc_m) ? `±${gps.acc_m.toFixed(1)} m` : "±—";
    element.dataset.state = gps.demo ? "normal" : "live";
    element.textContent =
      `현재 ${formatCoordinate(gps.lat, "N", "S")} · ${formatCoordinate(gps.lon, "E", "W")} · ` +
      `${accuracy} · SAT ${gps.satellites ?? "—"} · ${clock}`;
    return;
  }
  const last = gps.last_fix;
  element.dataset.state = "none";
  if (last && finite(last.lat) && finite(last.lon)) {
    const accuracy = finite(last.acc_m) ? `±${last.acc_m.toFixed(1)} m` : "±—";
    element.textContent =
      `마지막 확정 ${formatCoordinate(last.lat, "N", "S")} · ${formatCoordinate(last.lon, "E", "W")} · ` +
      `${accuracy} · SAT ${last.satellites ?? "—"} · AGE ${formatAge(gps.last_age_s)} · ${clock}`;
    return;
  }
  element.textContent = `좌표 데이터 없음 · ${clock}`;
}

function renderSun(device) {
  const sun = device.sun || {};
  if (!sun.computed) {
    setGlance("#glanceSun", "none", "계산 불가", "GPS 위치 필요");
  } else {
    const stateName = sun.reference !== "current_fix"
      ? "none"
      : sun.level === "danger"
        ? "warn"
        : sun.level === "caution"
          ? "caution"
          : "normal";
    setGlance(
      "#glanceSun",
      stateName,
      formatDaylight(sun.remaining_min),
      `일몰 ${sun.sunset_clock || "—"} · 귀환 ${sun.return_by_clock || "—"}`,
    );
  }
  const reference = sun.reference === "last_fix" ? " · 마지막 좌표 기준" : "";
  document.querySelector("#sunDetails").textContent =
    `일출 ${sun.sunrise_clock || "—"} · 일몰 ${sun.sunset_clock || "—"} · 귀환 권고 ${sun.return_by_clock || "—"}${reference}`;
}

function renderBattery(device) {
  const power = device.power || {};
  if (!power.valid) {
    setGlance("#glanceBattery", "none", "연동 전", "배터리 계측 없음");
    return;
  }
  const days = finite(power.days_left) ? `${formatNumber(power.days_left, 1)}일` : "—";
  const percent = finite(power.percent) ? `${Math.round(power.percent)}%` : "—";
  setGlance("#glanceBattery", device.demo ? "normal" : "live", days, `${percent} · 감시 모드`);
}

function renderTrail(device) {
  const trail = device.trail || {};
  const offset = finite(trail.offset_m) ? `${Math.round(trail.offset_m)} m` : "—";
  const states = {
    on_trail: ["live", "경로 위", `이탈 ${offset}`],
    off_trail: ["warn", "이탈", `${offset} 벗어남`],
    off_trail_estimate: ["caution", "이탈 추정", `${offset} · 정확도 없음`],
    accuracy_unknown: ["caution", "정확도 없음", `이탈 ${offset} · ±—`],
    uncertain: ["caution", "경계 구간", `${offset} · 오차 포함`],
    last_fix_only: ["none", "확인 불가", `마지막 위치 ${offset}`],
    unavailable: ["none", "확인 불가", "지도 또는 GPS 없음"],
  };
  const chosen = states[trail.status] || states.unavailable;
  setGlance("#glanceTrail", chosen[0], chosen[1], chosen[2]);
}

function renderReadout(device) {
  const card = document.querySelector("#readout");
  const route = device.navigation && device.navigation.active_route;
  if (!route || !route.available || !device.gps.fix || !state.connected) {
    card.hidden = true;
    return;
  }
  card.hidden = false;
  const target = route.target || {};
  document.querySelector("#readoutLabel").textContent = String(target.kind || "TARGET").toUpperCase();
  document.querySelector("#readoutBearing").textContent = `${String(Math.round(route.bearing_deg)).padStart(3, "0")}°`;
  document.querySelector("#readoutDistance").textContent = `${Math.round(route.distance_m)} m`;
  document.querySelector("#readoutSub").textContent =
    `경로 ${Math.round(route.distance_m)} m · 예상 ${Math.round(route.eta_min || 0)}분 · 직선 ${Math.round(route.straight_m)} m`;
}

function renderArrival(device) {
  const arrival = device.navigation && device.navigation.arrival;
  if (!arrival || !arrival.arrived) {
    state.announcedArrival = null;
    return;
  }
  const target = arrival.target || {};
  const key = String(target.id || target.kind || "target");
  if (state.announcedArrival === key) return;
  state.announcedArrival = key;
  showToast(`${target.name || "목적지"}에 도착했습니다`, 5000);
}

function renderAlert(device) {
  const alertBox = document.querySelector("#alert");
  if (device.alert) {
    document.querySelector("#alertText").textContent = device.alert.text;
    alertBox.hidden = false;
  } else {
    alertBox.hidden = true;
  }
  document.querySelector(".map").classList.toggle("has-alert", Boolean(device.alert));
  if (device.alert && device.alert.sound && state.connected) startAlarmSound();
  else stopAlarmSound();
}

function render() {
  const device = state.device;
  if (!device) {
    setGlance("#glanceGps", "none", "연결 중", "SAT — · AGE —");
    setGlance("#glanceSun", "none", "계산 대기", "GPS 위치 필요");
    setGlance("#glanceBattery", "none", "연동 전", "배터리 계측 없음");
    setGlance("#glanceTrail", "none", "확인 불가", "지도 또는 GPS 없음");
    setGlance("#glanceEnv", "none", "연동 전", "RH — · P — · CO —");
    renderPositionDetails({});
    document.querySelector("#demoChip").hidden = !state.map.demo;
    draw();
    return;
  }
  if (device.interface && typeof device.interface.night === "boolean") {
    applyNight(device.interface.night);
  }
  renderGps(device);
  renderPositionDetails(device);
  renderSun(device);
  renderBattery(device);
  renderTrail(device);
  renderEnvironment(device);
  renderReadout(device);
  renderArrival(device);
  renderAlert(device);
  document.querySelector("#mapName").textContent = device.map.name || state.map.name;
  document.querySelector("#demoChip").hidden = !device.demo;
  document.querySelector("#btnDestination").setAttribute("aria-pressed", String(state.selectingDestination));
  const selected = device.waypoints && device.waypoints.selected_target;
  document.querySelector("#btnBasecamp").setAttribute("aria-pressed", String(selected === "basecamp"));
  document.querySelector(".map").classList.toggle("selecting", state.selectingDestination);
  draw();
}

function beep() {
  if (!audioContext || audioContext.state !== "running") return;
  const oscillator = audioContext.createOscillator();
  const gain = audioContext.createGain();
  oscillator.type = "square";
  oscillator.frequency.setValueAtTime(880, audioContext.currentTime);
  oscillator.frequency.setValueAtTime(660, audioContext.currentTime + 0.14);
  gain.gain.setValueAtTime(0.0001, audioContext.currentTime);
  gain.gain.exponentialRampToValueAtTime(0.20, audioContext.currentTime + 0.015);
  gain.gain.setValueAtTime(0.20, audioContext.currentTime + 0.25);
  gain.gain.exponentialRampToValueAtTime(0.0001, audioContext.currentTime + 0.34);
  oscillator.connect(gain);
  gain.connect(audioContext.destination);
  oscillator.start();
  oscillator.stop(audioContext.currentTime + 0.35);
}

function startAlarmSound() {
  if (alarmTimer) return;
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) return;
  audioContext = audioContext || new AudioContextClass();
  audioContext.resume().then(beep).catch(() => {});
  alarmTimer = window.setInterval(beep, 900);
}

function stopAlarmSound() {
  if (alarmTimer) window.clearInterval(alarmTimer);
  alarmTimer = null;
}

async function postWaypoint(payload) {
  const response = await fetch("/api/waypoints", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store",
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "저장 지점 요청 실패");
  state.device = result;
  state.connected = true;
  render();
  return result;
}

function applyVoiceEvent(payload, showMessage = true) {
  if (!payload || typeof payload !== "object") return;
  if (payload.device) {
    state.device = payload.device;
    state.connected = true;
  }
  if (payload.ui && typeof payload.ui.night === "boolean") {
    applyNight(payload.ui.night);
  }
  if (Number.isFinite(payload.sequence)) {
    state.lastVoiceSequence = Math.max(state.lastVoiceSequence, payload.sequence);
  }
  const chip = document.querySelector("#voiceChip");
  if (payload.status) {
    chip.textContent = payload.status === "accepted" ? "VOICE · OK" :
      payload.status === "confirmation_required" ? "VOICE · 확인" : "VOICE · 보류";
    chip.dataset.status = payload.status;
    chip.hidden = false;
    if (voiceChipTimer) window.clearTimeout(voiceChipTimer);
    voiceChipTimer = window.setTimeout(() => { chip.hidden = true; }, 4200);
  }
  if (showMessage && payload.message) showToast(payload.message, 3800);
  render();
}

async function postVoiceCommand(action) {
  const response = await fetch("/api/voice/commands", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
    cache: "no-store",
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "음성 지도 명령 실패");
  applyVoiceEvent(result);
  return result;
}

document.querySelector("#btnDestination").addEventListener("click", () => {
  state.selectingDestination = !state.selectingDestination;
  showToast(state.selectingDestination ? "지도에서 목적지를 터치하세요" : "목적지 지정을 취소했습니다");
  render();
});

canvas.addEventListener("pointerup", async (event) => {
  if (!state.selectingDestination) return;
  const rect = canvas.getBoundingClientRect();
  const projector = makeProjector(state.map.bounds);
  const point = projector.unproject(
    (event.clientX - rect.left) * canvas.width / rect.width,
    (event.clientY - rect.top) * canvas.height / rect.height,
  );
  try {
    await postWaypoint({ action: "set", kind: "destination", lat: point.lat, lon: point.lon });
    state.selectingDestination = false;
    showToast("목적지를 지정했습니다");
  } catch (error) {
    showToast(error.message, 2600);
  }
  render();
});

document.querySelector("#btnCheckpoint").addEventListener("click", async () => {
  try {
    await postWaypoint({ action: "save_current", kind: "checkpoint" });
    showToast("현재 위치를 체크포인트로 저장했습니다");
  } catch (error) {
    showToast(error.message, 2600);
  }
});

document.querySelector("#btnBasecamp").addEventListener("click", async () => {
  try {
    const basecamp = state.device && state.device.waypoints && state.device.waypoints.basecamp;
    if (basecamp) {
      await postWaypoint({ action: "select", id: "basecamp" });
      showToast("베이스캠프 귀환 경로를 불러왔습니다");
    } else {
      await postWaypoint({ action: "save_current", kind: "basecamp" });
      showToast("현재 위치를 베이스캠프로 저장했습니다");
    }
  } catch (error) {
    showToast(error.message, 2600);
  }
});

document.querySelector("#btnNight").addEventListener("click", async () => {
  try {
    await postVoiceCommand(state.night ? "night_off" : "night_on");
  } catch (error) {
    showToast(error.message, 2600);
  }
});

document.addEventListener("pointerdown", () => {
  if (audioContext && audioContext.state === "suspended") audioContext.resume().catch(() => {});
}, { passive: true });

window.addEventListener("keydown", (event) => {
  if (state.bootLocked) {
    event.preventDefault();
    const notice = document.querySelector("#bootNotice");
    const button = document.querySelector("#bootAcknowledge");
    if (event.key === "Tab" && !button.disabled) button.focus();
    else notice.focus();
    return;
  }
  if (event.key === "n" || event.key === "N") {
    postVoiceCommand(state.night ? "night_off" : "night_on").catch((error) => {
      showToast(error.message, 2600);
    });
  }
  if (event.key === "Escape" && state.selectingDestination) {
    state.selectingDestination = false;
    render();
  }
});

window.addEventListener("resize", render);

async function loadMap() {
  try {
    const response = await fetch("/api/map", { cache: "no-store" });
    if (!response.ok) return;
    const payload = await response.json();
    if (!payload.bounds || !Array.isArray(payload.edges)) return;
    state.map = {
      name: payload.name || payload.source_name || "오프라인 보행 지도",
      source: payload.source_name,
      demo: Boolean(payload.demo),
      bounds: payload.bounds,
      trails: payload.edges,
      contours: [],
    };
  } catch (error) {
    state.map.demo = true;
  }
  render();
}

async function loadDevice() {
  try {
    const response = await fetch("/api/device", { cache: "no-store" });
    if (!response.ok) throw new Error("장치 상태 요청 실패");
    state.device = await response.json();
    state.connected = true;
  } catch (error) {
    state.connected = false;
  }
  render();
}

async function loadVoice() {
  try {
    const response = await fetch("/api/voice", { cache: "no-store" });
    if (!response.ok) return;
    const payload = await response.json();
    if (payload.ui && typeof payload.ui.night === "boolean") {
      applyNight(payload.ui.night);
    }
    if (Number.isFinite(payload.sequence)) state.lastVoiceSequence = payload.sequence;
  } catch (error) {
    // 지도와 센서 화면은 음성 브리지 장애와 독립적으로 계속 동작합니다.
  }
  render();
}

function connectEvents() {
  if (!("EventSource" in window)) return;
  if (state.eventSource) state.eventSource.close();
  const source = new EventSource("/api/device/events");
  state.eventSource = source;
  source.onmessage = (event) => {
    try {
      state.device = JSON.parse(event.data);
      state.connected = true;
      render();
    } catch (error) {
      state.connected = false;
      render();
    }
  };
  source.onerror = () => {
    state.connected = false;
    stopAlarmSound();
    render();
  };
}

function connectVoiceEvents() {
  if (!("EventSource" in window)) return;
  if (state.voiceEventSource) state.voiceEventSource.close();
  const source = new EventSource("/api/voice/events");
  state.voiceEventSource = source;
  source.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data);
      if (Number.isFinite(payload.sequence) && payload.sequence <= state.lastVoiceSequence) return;
      applyVoiceEvent(payload);
    } catch (error) {
      showToast("음성 지도 명령을 화면에 반영하지 못했습니다", 2600);
    }
  };
}

function setupBootNotice() {
  const notice = document.querySelector("#bootNotice");
  const screen = document.querySelector("#screen");
  const button = document.querySelector("#bootAcknowledge");
  const label = document.querySelector("#bootCountdown");
  screen.inert = true;
  screen.setAttribute("aria-hidden", "true");
  notice.focus();
  let remaining = 5;
  const finishCountdown = () => {
    if (state.bootDiagnosticOverall === "checking") {
      button.disabled = true;
      label.textContent = "부팅 자가진단 결과를 기다리는 중입니다";
      return;
    }
    button.disabled = false;
    label.textContent = state.bootDiagnosticOverall === "ready"
      ? "별도 비상 통신 수단 준비를 확인했습니다"
      : state.bootDiagnosticOverall === "demo"
        ? "DEMO·대기 상태를 확인하고 계속합니다"
        : "성능저하·대기 상태를 확인하고 계속합니다";
    button.focus();
  };
  document.addEventListener("safeaid:diagnostics", () => {
    if (remaining <= 0) finishCountdown();
  });
  const update = () => {
    if (remaining > 0) {
      label.textContent = `${remaining}초 동안 내용을 확인하세요`;
      remaining -= 1;
      window.setTimeout(update, 1000);
      return;
    }
    finishCountdown();
  };
  button.addEventListener("click", () => {
    if (button.disabled) return;
    state.bootLocked = false;
    screen.inert = false;
    screen.removeAttribute("aria-hidden");
    notice.hidden = true;
    document.querySelector("#btnDestination").focus();
  });
  update();
}

async function loadBootDiagnostics() {
  const summary = document.querySelector("#bootDiagnosticSummary");
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 3000);
  try {
    const response = await fetch("/api/diagnostics", {
      cache: "no-store",
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    for (const check of payload.checks || []) {
      const item = document.querySelector(`[data-check="${check.id}"]`);
      if (!item) continue;
      item.dataset.state = check.state;
      const value = item.querySelector("strong");
      value.textContent = check.state === "pass"
        ? "정상"
        : check.state === "demo"
          ? "DEMO"
          : check.state === "waiting"
            ? "대기"
            : "실패";
      item.title = check.detail || "";
      item.querySelector("small").textContent = check.detail || "상세 정보 없음";
    }
    state.bootDiagnosticOverall = payload.overall || "degraded";
    summary.textContent = payload.overall === "ready"
      ? "부팅 자가진단 · 모든 연결 확인"
      : payload.overall === "demo"
        ? "부팅 자가진단 · DEMO/대기 상태"
        : payload.overall === "waiting"
          ? "부팅 자가진단 · 장치 연결 대기"
          : "부팅 자가진단 · 성능저하 확인 필요";
  } catch (error) {
    state.bootDiagnosticOverall = "degraded";
    summary.textContent = "부팅 자가진단 · 서버 연결 실패";
    document.querySelectorAll("#bootChecks li").forEach((item) => {
      item.dataset.state = "fail";
      item.querySelector("strong").textContent = "실패";
      item.querySelector("small").textContent = "진단 서버 연결 실패";
    });
  } finally {
    window.clearTimeout(timeout);
    document.dispatchEvent(new CustomEvent("safeaid:diagnostics"));
  }
}

setNight(false);
setupBootNotice();
loadBootDiagnostics();
Promise.all([loadMap(), loadDevice(), loadVoice()]).then(() => {
  connectEvents();
  connectVoiceEvents();
});

// 장치 상태를 재폴링하지 않고 화면의 로컬 KST 시각만 갱신합니다.
window.setInterval(() => {
  renderPositionDetails(state.device || {});
}, 1000);
