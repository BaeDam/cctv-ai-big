/* CCTV AI 에이전트 — 관제 화면
 *
 * - 백엔드(FastAPI)에 연결되면 LIVE 모드: 카메라 목록·이벤트·신고 사건을 서버에서 받는다.
 * - index.html 을 파일로 바로 열거나 서버가 없으면 DEMO 모드: 가상 영상과 로컬 시뮬레이션으로 동작.
 */
(() => {
  "use strict";

  const LEVEL_RANK = { info: 0, warning: 1, danger: 2, critical: 3 };
  const TYPE_LABEL = {
    fall: "쓰러짐 감지",
    unresponsive: "쓰러진 후 무반응 (중상 의심)",
    fire: "화재 감지",
    smoke: "연기 감지",
    zone_intrusion: "위험구역 진입",
    no_helmet: "안전모 미착용",
    violence: "폭행/싸움 의심",
  };
  const TYPE_SEVERITY = {
    fall: "danger", unresponsive: "critical", fire: "critical", smoke: "critical",
    zone_intrusion: "warning", no_helmet: "warning", violence: "critical",
  };
  // 쓰러짐은 감지 즉시 신고 창을 띄운다 (무반응이 확인되면 같은 창이 '긴급'으로 격상)
  const TYPE_EMERGENCY = { fall: "119", unresponsive: "119", fire: "119", smoke: "119", violence: "112" };
  const FAMILY = { fall: "person_down", unresponsive: "person_down", fire: "fire", smoke: "fire" };
  const family = (t) => FAMILY[t] || t;
  const DEMO_CAMERAS = [
    "정문 출입구", "자재 야적장", "타워크레인 하부", "1층 작업장", "2층 작업장", "계단실",
    "지하 주차장", "후문", "가설 사무실", "옥상", "장비 주기장", "용접 작업장",
  ].map((name, i) => ({ id: `cam${String(i + 1).padStart(2, "0")}`, name, stream: null }));
  const DEMO_UNRESPONSIVE_DELAY = 6000; // 시연용: 쓰러진 뒤 무반응 판정까지 (실제 기본 10초)

  const $ = (id) => document.getElementById(id);
  const state = {
    live: false,
    site: { name: "OO건설 1공구 (데모)" },
    cameras: DEMO_CAMERAS,
    cols: 3,
    rows: 3,
    page: 0,
    viewerIndex: null,
    events: [],
    camAlert: {}, // camId → { level, message, until }
    camSim: {}, // camId → { mode, since } (가상 영상 연출용)
    incidents: new Map(), // id → incident (+ localDeadline)
    countdownSec: 15,
    demoIncidentId: 1,
  };

  // ------------------------------------------------------------- 저장소 유틸
  const store = {
    get(key, fallback) {
      try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; } catch { return fallback; }
    },
    set(key, value) {
      try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* 사생활 모드 등 */ }
    },
  };

  const camById = (id) => state.cameras.find((c) => c.id === id);
  const camName = (id) => (camById(id) || { name: id }).name;
  const fmtClock = (d) => d.toLocaleTimeString("en-GB", { hour12: false });
  const fmtTime = (ts) => fmtClock(new Date(ts * 1000));
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  };

  // ------------------------------------------------------------ 가상 영상
  const liveCanvases = new Set();

  function hash(str) {
    let h = 2166136261;
    for (const ch of str) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
    return h >>> 0;
  }
  function rng(seed) {
    return () => ((seed = Math.imul(seed ^ (seed >>> 15), 2246822507) + 0x9e3779b9) >>> 0) / 4294967296;
  }
  const sceneCache = {};
  function scene(camId) {
    if (sceneCache[camId]) return sceneCache[camId];
    const r = rng(hash(camId));
    const people = Array.from({ length: 2 + Math.floor(r() * 3) }, () => ({
      x: r(), y: 0.55 + r() * 0.35, v: (r() - 0.5) * 0.05, s: 0.8 + r() * 0.4,
      vest: ["#f97316", "#facc15", "#22d3ee"][Math.floor(r() * 3)],
    }));
    return (sceneCache[camId] = { hue: Math.floor(r() * 60) + 190, people });
  }

  function createFeed(cam) {
    if (cam.stream) {
      const img = new Image();
      img.src = cam.stream;
      img.alt = cam.name;
      return img;
    }
    const c = document.createElement("canvas");
    c.dataset.cam = cam.id;
    liveCanvases.add(c);
    return c;
  }

  function drawScene(canvas, t) {
    const rect = canvas.getBoundingClientRect();
    const w = Math.max(1, Math.round(rect.width));
    const h = Math.max(1, Math.round(rect.height));
    if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
    const ctx = canvas.getContext("2d");
    const camId = canvas.dataset.cam;
    const sc = scene(camId);
    const sim = state.camSim[camId];

    const g = ctx.createLinearGradient(0, 0, 0, h);
    g.addColorStop(0, `hsl(${sc.hue} 18% 16%)`);
    g.addColorStop(1, `hsl(${sc.hue} 10% 7%)`);
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, w, h);

    // 바닥 원근선
    ctx.strokeStyle = "rgba(255,255,255,.06)";
    ctx.lineWidth = 1;
    for (let i = -6; i <= 6; i++) {
      ctx.beginPath(); ctx.moveTo(w / 2 + i * w * 0.04, h * 0.45); ctx.lineTo(w / 2 + i * w * 0.25, h); ctx.stroke();
    }
    for (let i = 0; i < 6; i++) {
      const y = h * 0.45 + (h * 0.55) * (i / 6) ** 1.6;
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
    }

    // 위험구역 표시
    if (sim && sim.mode === "zone_intrusion") {
      ctx.fillStyle = "rgba(250,204,21,.15)";
      ctx.strokeStyle = "rgba(250,204,21,.8)";
      ctx.setLineDash([6, 4]);
      ctx.beginPath();
      ctx.moveTo(w * 0.3, h * 0.6); ctx.lineTo(w * 0.7, h * 0.6); ctx.lineTo(w * 0.8, h); ctx.lineTo(w * 0.2, h);
      ctx.closePath(); ctx.fill(); ctx.stroke(); ctx.setLineDash([]);
    }

    const unit = Math.min(w, h) / 6;
    sc.people.forEach((p, i) => {
      let x = (((p.x + p.v * t) % 1) + 1) % 1;
      let y = p.y;
      const size = unit * p.s;
      let fallen = false, color = "#22c55e", helmet = true;
      if (sim && i === 0) {
        if (sim.mode === "fall" || sim.mode === "unresponsive") { fallen = true; x = 0.5; color = sim.mode === "unresponsive" ? "#ef4444" : "#fb923c"; }
        if (sim.mode === "no_helmet") { helmet = false; color = "#facc15"; }
        if (sim.mode === "zone_intrusion") { x = 0.5; y = 0.8; color = "#facc15"; }
        if (sim.mode === "violence") { x = 0.48 + Math.sin(t * 12) * 0.01; color = "#ef4444"; }
      }
      if (sim && sim.mode === "violence" && i === 1) { x = 0.53 + Math.cos(t * 11) * 0.012; y = sc.people[0].y; color = "#ef4444"; }
      drawPerson(ctx, x * w, y * h, size, p.vest, fallen, helmet, color, i + 1);
    });

    if (sim && (sim.mode === "fire" || sim.mode === "smoke")) drawFire(ctx, w, h, t);

    // 타임스탬프, REC
    ctx.font = `${Math.max(10, Math.round(h / 22))}px monospace`;
    ctx.fillStyle = "rgba(255,255,255,.75)";
    ctx.textAlign = "right";
    ctx.fillText(fmtClock(new Date()), w - 8, h - 8);
    if (Math.floor(t * 2) % 2 === 0) {
      ctx.fillStyle = "#ef4444";
      ctx.beginPath(); ctx.arc(w - 14, 14, 5, 0, Math.PI * 2); ctx.fill();
    }
    ctx.textAlign = "left";
  }

  function drawPerson(ctx, x, y, s, vest, fallen, helmet, color, id) {
    ctx.save();
    ctx.translate(x, y);
    let bw = s * 0.45, bh = s * 1.1;
    if (fallen) { ctx.rotate(Math.PI / 2); }
    ctx.fillStyle = "#3f4a5a";
    ctx.fillRect(-s * 0.12, -s * 0.35, s * 0.08, s * 0.35); // 다리
    ctx.fillRect(s * 0.04, -s * 0.35, s * 0.08, s * 0.35);
    ctx.fillStyle = vest;
    ctx.fillRect(-s * 0.16, -s * 0.8, s * 0.32, s * 0.46); // 몸통(조끼)
    ctx.fillStyle = "#e0b896";
    ctx.beginPath(); ctx.arc(0, -s * 0.92, s * 0.11, 0, Math.PI * 2); ctx.fill(); // 머리
    if (helmet) {
      ctx.fillStyle = "#f8fafc";
      ctx.beginPath(); ctx.arc(0, -s * 0.95, s * 0.12, Math.PI, 0); ctx.fill();
    }
    ctx.restore();

    // AI 박스
    if (fallen) { [bw, bh] = [bh, bw]; }
    const bx = fallen ? x - s * 0.05 : x - bw / 2;
    const by = fallen ? y - bh * 0.6 : y - bh;
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.strokeRect(bx, by, bw, bh);
    ctx.fillStyle = color;
    ctx.font = `${Math.max(9, Math.round(s / 7))}px sans-serif`;
    ctx.fillText(`#${id} person`, bx, by - 3);
  }

  function drawFire(ctx, w, h, t) {
    const cx = w * 0.7, cy = h * 0.75;
    for (let i = 0; i < 14; i++) {
      const a = t * 6 + i;
      const r = (Math.sin(a) * 0.5 + 1) * Math.min(w, h) * 0.05;
      ctx.fillStyle = `rgba(${240 + Math.sin(a) * 15},${90 + i * 8},20,.55)`;
      ctx.beginPath(); ctx.arc(cx + Math.sin(a * 1.3) * w * 0.04, cy - i * h * 0.015, r, 0, Math.PI * 2); ctx.fill();
    }
    ctx.fillStyle = "rgba(120,120,120,.25)";
    for (let i = 0; i < 6; i++) {
      ctx.beginPath(); ctx.arc(cx + Math.sin(t + i) * w * 0.05, cy - h * 0.25 - i * h * 0.05, Math.min(w, h) * 0.07, 0, Math.PI * 2); ctx.fill();
    }
    ctx.strokeStyle = "#ef4444"; ctx.lineWidth = 2;
    ctx.strokeRect(cx - w * 0.08, cy - h * 0.32, w * 0.16, h * 0.36);
    ctx.fillStyle = "#ef4444"; ctx.fillText("fire", cx - w * 0.08, cy - h * 0.32 - 3);
  }

  let lastDraw = 0;
  function renderLoop(now) {
    requestAnimationFrame(renderLoop);
    if (now - lastDraw < 66) return; // ~15fps
    lastDraw = now;
    const t = now / 1000;
    for (const c of liveCanvases) {
      if (!c.isConnected) { liveCanvases.delete(c); continue; }
      drawScene(c, t);
    }
  }

  // --------------------------------------------------------------- 그리드
  const pageSize = () => state.cols * state.rows;
  const pageCount = () => Math.max(1, Math.ceil(state.cameras.length / pageSize()));

  function setLayout(cols, rows) {
    cols = Math.min(8, Math.max(1, cols | 0));
    rows = Math.min(8, Math.max(1, rows | 0));
    const firstIndex = state.page * pageSize();
    state.cols = cols;
    state.rows = rows;
    state.page = Math.floor(firstIndex / pageSize());
    store.set("cctv.layout", { cols, rows });
    renderGrid();
  }

  function renderGrid() {
    const grid = $("grid");
    state.page = Math.min(state.page, pageCount() - 1);
    grid.style.gridTemplateColumns = `repeat(${state.cols}, minmax(0, 1fr))`;
    grid.style.gridTemplateRows = `repeat(${state.rows}, minmax(0, 1fr))`;
    grid.replaceChildren();
    const start = state.page * pageSize();
    for (let i = 0; i < pageSize(); i++) {
      const cam = state.cameras[start + i];
      const tile = el("div", "tile");
      if (!cam) {
        tile.classList.add("empty");
        grid.appendChild(tile);
        continue;
      }
      tile.dataset.cam = cam.id;
      tile.appendChild(createFeed(cam));
      tile.appendChild(el("div", "tile-label", cam.name));
      const alert = el("div", "tile-alert");
      alert.hidden = true;
      tile.appendChild(alert);
      tile.addEventListener("click", () => openViewer(start + i));
      grid.appendChild(tile);
    }
    $("pageInfo").textContent = `${state.page + 1} / ${pageCount()}`;
    document.querySelectorAll("[data-layout]").forEach((b) => {
      b.classList.toggle("active", b.dataset.layout === `${state.cols}x${state.rows}`);
    });
    $("colsInput").value = state.cols;
    $("rowsInput").value = state.rows;
    updateTileAlerts();
  }

  function changePage(delta) {
    state.page = (state.page + delta + pageCount()) % pageCount();
    renderGrid();
  }

  function currentAlert(camId) {
    const a = state.camAlert[camId];
    if (!a) return null;
    if (a.until < Date.now()) { delete state.camAlert[camId]; delete state.camSim[camId]; return null; }
    return a;
  }

  function updateTileAlerts() {
    document.querySelectorAll(".tile[data-cam]").forEach((tile) => {
      const a = currentAlert(tile.dataset.cam);
      const alert = tile.querySelector(".tile-alert");
      if (a) {
        tile.dataset.level = a.level;
        alert.textContent = a.message;
        alert.hidden = false;
      } else {
        delete tile.dataset.level;
        alert.hidden = true;
      }
    });
  }

  // ------------------------------------------------------------- 확대 보기
  function openViewer(index) {
    state.viewerIndex = index;
    $("viewer").hidden = false;
    renderViewer();
  }
  function closeViewer() {
    state.viewerIndex = null;
    $("viewer").hidden = true;
    $("viewerStage").replaceChildren();
  }
  function renderViewer() {
    const cam = state.cameras[state.viewerIndex];
    if (!cam) return closeViewer();
    $("viewerName").textContent = cam.name;
    $("viewerIndex").textContent = `${state.viewerIndex + 1} / ${state.cameras.length}`;
    $("viewerStage").replaceChildren(createFeed(cam));
    renderEventList($("viewerEvents"), state.events.filter((e) => e.camera_id === cam.id).slice(0, 20));
  }
  function moveViewer(delta) {
    if (state.viewerIndex == null) return;
    const stage = $("viewerStage");
    stage.classList.add(delta > 0 ? "slide-left" : "slide-right");
    setTimeout(() => {
      const n = state.cameras.length;
      state.viewerIndex = (state.viewerIndex + delta + n) % n;
      renderViewer();
      stage.classList.remove("slide-left", "slide-right");
    }, 150);
  }

  // ---------------------------------------------------------- 이벤트 목록
  function renderEventList(list, events) {
    list.replaceChildren();
    if (!events.length) {
      list.appendChild(el("li", "empty-msg", "감지된 이벤트 없음"));
      return;
    }
    for (const ev of events) {
      const li = el("li", `event ${ev.severity}`);
      const top = el("div", "ev-top");
      top.append(el("span", null, camName(ev.camera_id)), el("span", null, fmtTime(ev.timestamp)));
      li.append(top, el("div", "ev-msg", ev.message));
      if (ev.emergency) li.appendChild(el("div", "ev-call", `☎ ${ev.emergency} 신고 절차`));
      li.addEventListener("click", () => {
        const idx = state.cameras.findIndex((c) => c.id === ev.camera_id);
        if (idx >= 0) openViewer(idx);
      });
      list.appendChild(li);
    }
  }

  function addEvent(ev) {
    state.events.unshift(ev);
    state.events = state.events.slice(0, 200);
    renderEventList($("eventList"), state.events);
    if (state.viewerIndex != null && state.cameras[state.viewerIndex]?.id === ev.camera_id) renderViewer();

    const prev = currentAlert(ev.camera_id);
    if (!prev || LEVEL_RANK[ev.severity] >= LEVEL_RANK[prev.level]) {
      state.camAlert[ev.camera_id] = {
        level: ev.severity,
        message: ev.message,
        until: Date.now() + (ev.severity === "critical" ? 60000 : 15000),
      };
    }
    if (!state.camSim[ev.camera_id] || ev.type === "unresponsive") {
      state.camSim[ev.camera_id] = { mode: ev.type, since: Date.now() };
    }
    updateTileAlerts();
    if (ev.severity !== "critical") toast(`${camName(ev.camera_id)} · ${ev.message}`, ev.severity);

    if (!state.live && ev.emergency) {
      // 같은 카메라에서 대기 중인 같은 계열 사건이 있으면 새 창 대신 격상
      const open = pendingIncidents().find((i) => i.event.camera_id === ev.camera_id && family(i.event.type) === family(ev.type));
      if (open) {
        if (LEVEL_RANK[ev.severity] > LEVEL_RANK[open.event.severity]) upsertIncident({ ...open, event: ev });
        return;
      }
      upsertIncident({
        id: state.demoIncidentId++,
        event: ev,
        target: ev.emergency,
        created_at: Date.now() / 1000,
        deadline: Date.now() / 1000 + state.countdownSec,
        status: "pending",
      });
    }
  }

  // ---------------------------------------------------------- 긴급 신고
  function upsertIncident(inc) {
    const prev = state.incidents.get(inc.id);
    const localDeadline = prev?.localDeadline ?? Date.now() + (inc.deadline - inc.created_at) * 1000;
    state.incidents.set(inc.id, { ...inc, localDeadline });
    if (prev && prev.status === "pending" && inc.status !== "pending") {
      if (inc.status === "dispatched") toast(`☎ ${inc.target} 신고 발송 완료 (${inc.resolved_by === "auto" ? "자동" : "관리자"}) · ${camName(inc.event.camera_id)}`, "critical");
      if (inc.status === "cancelled") toast(`신고 취소됨 (오탐) · ${camName(inc.event.camera_id)}`, "ok");
      if (inc.status === "failed") toast(`⚠ ${inc.target} 신고 실패 — 직접 전화하세요!`, "critical");
    }
    renderEmergency();
  }

  const pendingIncidents = () =>
    [...state.incidents.values()].filter((i) => i.status === "pending").sort((a, b) => a.id - b.id);

  let shownIncidentId = null;
  function renderEmergency() {
    const pending = pendingIncidents();
    const modal = $("emergency");
    if (!pending.length) {
      modal.hidden = true;
      shownIncidentId = null;
      $("emFeed").replaceChildren();
      return;
    }
    const inc = pending[0];
    modal.hidden = false;
    if (shownIncidentId !== inc.id) {
      shownIncidentId = inc.id;
      const cam = camById(inc.event.camera_id);
      $("emFeed").replaceChildren(cam ? createFeed(cam) : el("div"));
    }
    // 내용은 매번 갱신 (쓰러짐 → 무반응 격상, AI 판단 도착)
    const critical = inc.event.severity === "critical";
    $("emTarget").textContent = inc.target;
    $("emTitle").textContent = inc.target === "112" ? "긴급 상황 — 112 경찰"
      : critical ? "긴급 상황 — 119 구급/소방" : "쓰러짐 감지 — 119 신고 대기";
    $("emMessage").textContent = inc.event.message;
    $("emCamera").textContent = `${camName(inc.event.camera_id)} · ${fmtTime(inc.event.timestamp)}`;
    renderAi(inc.ai);
    $("emQueue").textContent = pending.length > 1 ? `대기 중인 긴급 상황 ${pending.length - 1}건 더 있음` : "";
    tickEmergency();
  }

  function renderAi(ai) {
    const box = $("emAi");
    box.className = "em-ai";
    if (!ai) { box.hidden = true; return; }
    box.hidden = false;
    if (ai.pending) { box.textContent = "AI(Gemini)가 장면을 확인하는 중…"; return; }
    if (ai.error) { box.classList.add("muted"); box.textContent = `AI 판단 사용 불가: ${ai.error}`; return; }
    box.classList.add(ai.is_emergency ? "alert" : "calm");
    box.replaceChildren(
      el("b", null, `AI 판단: ${ai.is_emergency ? "위급 상황으로 보임" : "위급하지 않을 수 있음"} · 심각도 ${ai.severity} · 권고 ${ai.call}`),
      el("div", null, ai.observation),
      el("div", "em-ai-reason", `근거: ${ai.reason}`),
    );
  }

  function tickEmergency() {
    const now = Date.now();
    for (const inc of pendingIncidents()) {
      if (!state.live && now >= inc.localDeadline) resolveDemo(inc.id, "dispatched", "auto");
    }
    const inc = state.incidents.get(shownIncidentId);
    if (!inc || inc.status !== "pending") return;
    const total = (inc.deadline - inc.created_at) * 1000;
    const left = Math.max(0, inc.localDeadline - now);
    $("emSeconds").textContent = Math.ceil(left / 1000);
    $("emBar").style.width = `${(left / total) * 100}%`;
  }

  function resolveDemo(id, status, by) {
    const inc = state.incidents.get(id);
    if (!inc || inc.status !== "pending") return;
    upsertIncident({ ...inc, status, resolved_by: by });
  }

  async function actOnIncident(action) {
    const id = shownIncidentId;
    if (id == null) return;
    if (!state.live) return resolveDemo(id, action === "cancel" ? "cancelled" : "dispatched", "operator");
    try {
      const res = await fetch(`/api/incidents/${id}/${action}`, { method: "POST" });
      if (res.ok) upsertIncident(await res.json());
    } catch {
      toast("서버 연결 실패 — 직접 신고하세요", "critical");
    }
  }

  // ---------------------------------------------------------- 시뮬레이션
  async function emit(camId, type) {
    if (state.live) {
      try {
        await fetch("/api/simulate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ camera_id: camId, type }),
        });
      } catch { toast("서버 연결 실패", "critical"); }
      return; // 이벤트는 WebSocket 으로 돌아온다
    }
    addEvent({
      camera_id: camId,
      type,
      severity: TYPE_SEVERITY[type],
      message: TYPE_LABEL[type] + " (시뮬레이션)",
      timestamp: Date.now() / 1000,
      track_id: null,
      emergency: TYPE_EMERGENCY[type] || null,
    });
  }

  function runSimulation(camId, type) {
    state.camSim[camId] = { mode: type, since: Date.now() };
    emit(camId, type);
    if (type === "fall") {
      // 쓰러진 뒤 움직임이 없으면 무반응 → 119
      setTimeout(() => {
        if (state.camSim[camId]?.mode === "fall") emit(camId, "unresponsive");
      }, DEMO_UNRESPONSIVE_DELAY);
    }
  }

  function startAmbientDemo() {
    const loop = () => {
      setTimeout(() => {
        if (!state.live && pendingIncidents().length === 0) {
          const cam = state.cameras[Math.floor(Math.random() * state.cameras.length)];
          if (!currentAlert(cam.id)) runSimulation(cam.id, Math.random() < 0.5 ? "no_helmet" : "zone_intrusion");
        }
        loop();
      }, 20000 + Math.random() * 20000);
    };
    loop();
  }

  // ------------------------------------------------------------- 토스트
  function toast(text, level = "info") {
    const t = el("div", `toast ${level}`, text);
    $("toasts").appendChild(t);
    setTimeout(() => t.remove(), 5000);
  }

  // ---------------------------------------------------------- 서버 연결
  async function connect() {
    if (!location.protocol.startsWith("http")) return false;
    try {
      const res = await fetch("/api/config");
      if (!res.ok) return false;
      const cfg = await res.json();
      state.live = true;
      state.site = cfg.site || state.site;
      state.cameras = cfg.cameras.length ? cfg.cameras : DEMO_CAMERAS;
      state.countdownSec = cfg.countdown_sec;
      const [events, incidents] = await Promise.all([
        fetch("/api/events").then((r) => r.json()),
        fetch("/api/incidents").then((r) => r.json()),
      ]);
      state.events = events.slice().reverse();
      incidents.forEach((inc) => state.incidents.set(inc.id, { ...inc, localDeadline: Date.now() + Math.max(0, inc.deadline - Date.now() / 1000) * 1000 }));
      openSocket();
      return true;
    } catch {
      return false;
    }
  }

  function openSocket() {
    const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
    ws.onopen = () => setBadge(true);
    ws.onmessage = (m) => {
      const msg = JSON.parse(m.data);
      if (msg.kind === "event") addEvent(msg.data);
      if (msg.kind === "incident") upsertIncident(msg.data);
      if (msg.kind === "events_cleared") { state.events = []; renderEventList($("eventList"), []); }
    };
    ws.onclose = () => {
      setBadge(false, "재연결 중");
      setTimeout(openSocket, 2000);
    };
  }

  function setBadge(live, text) {
    const b = $("connBadge");
    b.className = `badge ${live ? "live" : "demo"}`;
    b.textContent = text || (live ? "LIVE" : "DEMO");
  }

  // ---------------------------------------------------------------- 초기화
  function bindUI() {
    document.querySelectorAll("[data-layout]").forEach((b) =>
      b.addEventListener("click", () => {
        const [c, r] = b.dataset.layout.split("x").map(Number);
        setLayout(c, r);
      })
    );
    $("applyCustom").addEventListener("click", () => setLayout(+$("colsInput").value, +$("rowsInput").value));
    $("prevPage").addEventListener("click", () => changePage(-1));
    $("nextPage").addEventListener("click", () => changePage(1));
    $("viewerClose").addEventListener("click", closeViewer);
    $("viewerPrev").addEventListener("click", () => moveViewer(-1));
    $("viewerNext").addEventListener("click", () => moveViewer(1));
    $("emCancel").addEventListener("click", () => actOnIncident("cancel"));
    $("emConfirm").addEventListener("click", () => actOnIncident("confirm"));
    $("clearEvents").addEventListener("click", async () => {
      state.events = [];
      renderEventList($("eventList"), []);
      if (state.live) { try { await fetch("/api/events", { method: "DELETE" }); } catch { /* 화면에서는 이미 지움 */ } }
      toast("AI 이벤트 목록을 지웠습니다", "ok");
    });
    $("simRun").addEventListener("click", () => runSimulation($("simCamera").value, $("simType").value));

    document.addEventListener("keydown", (e) => {
      if (e.target.matches("input, select")) return;
      if (!$("emergency").hidden) return;
      if (state.viewerIndex != null) {
        if (e.key === "Escape") closeViewer();
        if (e.key === "ArrowLeft") moveViewer(-1);
        if (e.key === "ArrowRight") moveViewer(1);
      } else {
        if (e.key === "ArrowLeft") changePage(-1);
        if (e.key === "ArrowRight") changePage(1);
      }
    });

    // 확대 화면 스와이프 (모바일/태블릿)
    let startX = null;
    const stage = $("viewerStage");
    stage.addEventListener("pointerdown", (e) => { startX = e.clientX; });
    stage.addEventListener("pointerup", (e) => {
      if (startX == null) return;
      const dx = e.clientX - startX;
      startX = null;
      if (Math.abs(dx) > 50) moveViewer(dx < 0 ? 1 : -1);
    });
  }

  function fillSimCameras() {
    const sel = $("simCamera");
    sel.replaceChildren(...state.cameras.map((c) => {
      const o = el("option", null, c.name);
      o.value = c.id;
      return o;
    }));
  }

  async function init() {
    bindUI();
    const layout = store.get("cctv.layout", { cols: 3, rows: 3 });
    state.cols = layout.cols;
    state.rows = layout.rows;

    const live = await connect();
    setBadge(live);
    $("siteName").textContent = state.site.name || "현장";
    fillSimCameras();
    renderGrid();
    renderEventList($("eventList"), state.events);
    renderEmergency();
    if (!live) startAmbientDemo();

    setInterval(() => { $("clock").textContent = fmtClock(new Date()); }, 1000);
    setInterval(updateTileAlerts, 500);
    setInterval(tickEmergency, 250);
    requestAnimationFrame(renderLoop);
  }

  init();
})();
