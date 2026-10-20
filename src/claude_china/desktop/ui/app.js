const api = () => window.pywebview.api;
let APPS = [];
let SETTINGS = { check_system_proxy: true, env_vars: {} };
const APP_SETTINGS = {}; // id -> { env_vars, path }
let READY = false;
let lastRefresh = 0;
let brandAnimation;
let UPDATE = { phase: "idle" };
let updatePoll;

function animateBrand() {
  const mark = document.getElementById("brand-mark");
  if (!mark || document.hidden || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  if (brandAnimation && brandAnimation.playState === "running") return;
  const frames = Array.from({ length: 14 }, (_, i) => {
    const t = i / 13;
    const breath = Math.sin(Math.PI * t);
    const angle = -12 * Math.sin(2 * Math.PI * t) * breath;
    return { transform: `rotate(${angle}deg) scale(${1 - 0.09 * breath})` };
  });
  brandAnimation = mark.animate(frames, { duration: 960, iterations: 1 });
}

const GEAR_SVG =
  `<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">` +
  `<path fill="currentColor" d="M10.3 2.3h3.4l.4 2.2c.6.2 1.2.5 1.7.9l2.1-.8 1.7 2.9-1.7 1.4c.1.6.2 1.2.2 1.8s-.1 1.2-.2 1.8l1.7 1.4-1.7 2.9-2.1-.8c-.5.4-1.1.7-1.7.9l-.4 2.2h-3.4l-.4-2.2a7 7 0 0 1-1.7-.9l-2.1.8-1.7-2.9 1.7-1.4a7 7 0 0 1-.2-1.8c0-.6.1-1.2.2-1.8L4.4 7.5 6.1 4.6l2.1.8c.5-.4 1.1-.7 1.7-.9l.4-2.2ZM12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z"/>` +
  `</svg>`;

function esc(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#x27;");
}

function findApp(id) { return APPS.find((x) => x.id === id); }

async function init() {
  APPS = await api().list_apps();
  renderApps();
  await Promise.all([loadSettings(), ...APPS.map((a) => loadAppSettings(a.id))]);
  renderUpdate(await api().get_update_status());
  READY = true;
  lastRefresh = Date.now();
  fitWindow();
  animateBrand();
}

// ---- launcher updates (only checked on request) ----
function renderUpdate(state) {
  UPDATE = state;
  const busy = ["checking", "downloading", "installing"].includes(state.phase);
  const button = document.getElementById("update-action");
  const status = document.getElementById("update-status");
  const target = ["available", "downloading", "ready", "installing"].includes(state.phase) && state.latest;
  document.getElementById("update-version").textContent =
    (state.current ? `v${state.current}` : "") + (target ? ` → v${state.latest}` : "");
  let message = state.message;
  if (state.phase === "available" && !state.can_install) message += ` · ${state.reason}`;
  if (state.phase === "downloading") message += ` ${state.progress || 0}%`;
  status.textContent = message;
  document.querySelector(".bay--update").classList.toggle("has-error", state.phase === "error");
  button.disabled = busy || (state.phase === "available" && !state.can_install);
  button.classList.toggle("btn--solid", ["available", "ready"].includes(state.phase));
  button.textContent = ({
    checking: "正在检查…", downloading: "正在下载…", available: "下载更新",
    ready: "安装并重启", installing: "正在重启…", error: "重试检查",
  })[state.phase] || "检查更新";
  document.getElementById("update-cancel").hidden = state.phase !== "downloading";
  const progress = document.getElementById("update-progress");
  progress.hidden = state.phase !== "downloading";
  progress.value = state.progress || 0;
  fitWindow();
  clearTimeout(updatePoll);
  if (busy) updatePoll = setTimeout(refreshUpdate, 500);
}

async function refreshUpdate() {
  try {
    renderUpdate(await api().get_update_status());
  } catch (_) {
    renderUpdate({ ...UPDATE, phase: "error", message: "无法获取更新状态，请重试。" });
  }
}

async function updateAction() {
  const phase = UPDATE.phase;
  if (phase === "ready" && document.querySelector(".editor.is-open")) {
    toast("请先保存或取消正在编辑的设置，再安装更新");
    return;
  }
  document.getElementById("update-action").disabled = true;
  try {
    const action = phase === "available" ? "download_update"
      : phase === "ready" ? "install_update" : "check_for_updates";
    renderUpdate(await api()[action]());
  } catch (_) {
    renderUpdate({ ...UPDATE, phase: "error", message: "无法完成操作，请重试。" });
  }
}

// ---- window fit ----
// The window is a palette: it is always exactly as tall as its content. The
// page measures what it needs and the bridge applies the delta to the window.
function contentHeight() {
  let h = document.getElementById("foot").offsetHeight;
  for (const bay of document.querySelectorAll(".bay")) h += bay.offsetHeight;
  return h;
}

function fitWindow(extra = 0) {
  if (!window.pywebview || !api().fit_window) return;
  const wanted = Math.ceil(contentHeight() + extra);
  api().fit_window({ inner: window.innerHeight, wanted });
}

// ---- app bays ----
function renderApps() {
  const list = document.getElementById("apps");
  list.innerHTML = "";
  for (const a of APPS) {
    const id = esc(a.id);
    const name = esc(a.display);
    const bay = document.createElement("section");
    bay.className = "bay bay--app";
    bay.id = `bay-${id}`;
    bay.innerHTML =
      `<div class="bay-row">` +
      `<div class="bay-lamp" aria-hidden="true"><span class="lamp"></span></div>` +
      `<div class="bay-copy">` +
      `<h2 class="bay-name">${name}</h2>` +
      `<p class="bay-status" id="status-${id}"></p>` +
      `</div>` +
      `<div class="bay-actions">` +
      `<button class="btn btn--key" type="button" id="btn-launch-${id}" data-mode="launch">启动</button>` +
      `<button class="btn btn--stop" type="button" id="btn-stop-${id}" data-mode="stop">中止</button>` +
      `<button class="btn btn--key" type="button" id="btn-config-${id}" data-mode="config">选择路径…</button>` +
      `<button class="gear" type="button" id="gear-${id}" aria-expanded="false" ` +
      `aria-controls="editor-${id}" aria-label="${name} 专有设置" title="${name} 专有设置">${GEAR_SVG}</button>` +
      `</div>` +
      `</div>` +
      `<div class="editor" id="editor-${id}" inert>` +
      `<div class="editor-inner"><div class="editor-body">` +
      `<div class="field">` +
      `<div class="field-head"><span class="field-label">应用路径</span>` +
      `<span class="field-hint">默认自动检测，也可以手动指定可执行文件</span></div>` +
      `<div class="path-row"><code class="path-value" id="path-${id}"></code>` +
      `<button class="btn btn--small" type="button" id="pick-${id}">选择…</button></div>` +
      `</div>` +
      `<div class="field">` +
      `<div class="field-head"><span class="field-label">专有环境变量</span>` +
      `<span class="field-hint">只在启动 ${name} 时注入，与通用变量同名时以这里为准</span></div>` +
      `<div class="env-list" id="env-${id}"></div>` +
      `<button class="add-row" type="button" id="add-${id}">添加变量</button>` +
      `</div>` +
      `<div class="editor-actions">` +
      `<button class="btn" type="button" id="cancel-${id}">取消</button>` +
      `<button class="btn btn--solid" type="button" id="save-${id}">保存</button>` +
      `</div>` +
      `</div></div>` +
      `</div>`;
    list.appendChild(bay);
    updateBay(a.id, a.found, a.running);
    document.getElementById(`btn-launch-${a.id}`).onclick = () => onAction(a.id, "launch");
    document.getElementById(`btn-stop-${a.id}`).onclick = () => onAction(a.id, "stop");
    document.getElementById(`btn-config-${a.id}`).onclick = () => onAction(a.id, "config");
    document.getElementById(`gear-${a.id}`).onclick = () => toggleEditor(a.id);
    document.getElementById(`pick-${a.id}`).onclick = () => onAction(a.id, "config");
    document.getElementById(`add-${a.id}`).onclick = () => addEnvRow(`env-${a.id}`);
    document.getElementById(`cancel-${a.id}`).onclick = () => setEditorOpen(a.id, false);
    document.getElementById(`save-${a.id}`).onclick = () => saveAppSettings(a.id);
  }
}

const BAY_ERRORS = {}; // id -> { msg, timer }

// A failed launch/stop is reported in the bay's own status line, next to the
// key that was pressed, and clears itself after a few seconds.
function setBayError(id, msg) {
  const cur = BAY_ERRORS[id];
  if (cur) clearTimeout(cur.timer);
  BAY_ERRORS[id] = msg ? {
    msg,
    timer: setTimeout(() => { delete BAY_ERRORS[id]; rerenderBay(id); }, 6000),
  } : undefined;
  rerenderBay(id);
}

function rerenderBay(id) {
  const a = findApp(id);
  if (a) updateBay(id, a.found, a.running);
}

function statusText(a) {
  const s = APP_SETTINGS[a.id];
  const n = s ? Object.keys(s.env_vars || {}).length : 0;
  const vars = n ? ` · ${n} 个专有环境变量` : "";
  if (!a.found) return "未检测到安装，选择应用路径后即可启动";
  if (a.running) return "运行中" + vars;
  return "未运行" + vars;
}

function updateBay(id, found, running) {
  const a = findApp(id);
  if (a) { a.found = found; a.running = running; }
  const bay = document.getElementById(`bay-${id}`);
  const status = document.getElementById(`status-${id}`);
  const launch = document.getElementById(`btn-launch-${id}`);
  const stop = document.getElementById(`btn-stop-${id}`);
  const config = document.getElementById(`btn-config-${id}`);
  if (!bay || !status || !launch || !stop || !config) return;
  const err = BAY_ERRORS[id];
  bay.classList.toggle("is-missing", !found);
  bay.classList.toggle("is-running", !!(found && running));
  bay.classList.toggle("has-error", !!err);
  status.textContent = err ? err.msg : statusText(a || { id, found, running });
  // Status can be stale (no background poll), so both keys stay live once the
  // app is found; launch always stops-then-starts, hence "重启" while running.
  launch.hidden = !found;
  stop.hidden = !found;
  config.hidden = found;
  launch.textContent = running ? "重启" : "启动";
}

async function onAction(id, mode) {
  animateBrand();
  if (mode === "config") {
    const r = await api().pick_app_path(id);
    if (r && r.ok) {
      if (APP_SETTINGS[id]) APP_SETTINGS[id].path = r.path;
      renderPath(id);
      fitWindow(); // a long path may wrap
      await refresh();
    }
    return;
  }
  let r = { ok: true };
  if (mode === "launch") r = await api().launch_app(id);
  else if (mode === "stop") r = await api().stop_app(id);
  await refresh();
  setBayError(id, r.ok ? "" : (r.error || "操作失败"));
}

async function refresh() {
  lastRefresh = Date.now();
  APPS = await api().list_apps();
  for (const a of APPS) updateBay(a.id, a.found, a.running);
}

// No background status push (see bridge history); re-check when the window
// comes back to the front instead, which is when a stale lamp would be noticed.
function refreshOnReturn() {
  if (!READY || document.hidden) return;
  if (Date.now() - lastRefresh < 1500) return;
  refresh();
}

// Confirmations surface in the footer status line rather than an overlay.
function toast(msg) {
  const foot = document.getElementById("foot");
  document.getElementById("toast").textContent = msg;
  foot.classList.add("has-msg");
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => foot.classList.remove("has-msg"), 2200);
}

// ---- inline editors ----
function setEditorOpen(id, open) {
  const editor = document.getElementById(`editor-${id}`);
  const gear = document.getElementById(`gear-${id}`);
  if (!editor || !gear) return;
  if (open) {
    // Re-render from the last saved state so a reopened editor never shows
    // edits that were cancelled.
    if (id === "common") renderCommon(); else renderAppEditor(id);
    // Grow the window before the editor unfolds into the new space; the
    // collapsed editor's scrollHeight is exactly the height it is about to take.
    fitWindow(editor.firstElementChild.scrollHeight);
  }
  editor.classList.toggle("is-open", open);
  editor.inert = !open;
  gear.classList.toggle("is-active", open);
  gear.setAttribute("aria-expanded", open ? "true" : "false");
  if (open) {
    // If the screen capped the window, keep the bay being edited in view.
    const bay = editor.closest(".bay");
    setTimeout(() => {
      const panel = bay.closest(".panel");
      const block = bay.offsetHeight > panel.clientHeight ? "start" : "nearest";
      bay.scrollIntoView({ block, behavior: "smooth" });
    }, 300);
  } else {
    // Shrink back once the fold animation has finished.
    setTimeout(fitWindow, 300);
  }
}

function toggleEditor(id) {
  const editor = document.getElementById(`editor-${id}`);
  setEditorOpen(id, !(editor && editor.classList.contains("is-open")));
}

function closeAllEditors() {
  for (const ed of document.querySelectorAll(".editor.is-open")) {
    setEditorOpen(ed.id.replace(/^editor-/, ""), false);
  }
}

// ---- env rows ----
function renderEnv(containerId, vars) {
  const c = document.getElementById(containerId);
  c.innerHTML = "";
  for (const [k, v] of Object.entries(vars || {})) addEnvRow(containerId, k, v, false);
}

function addEnvRow(containerId, k = "", v = "", focus = true) {
  const c = document.getElementById(containerId);
  const row = document.createElement("div");
  row.className = "env-row";
  row.innerHTML =
    `<input class="k" placeholder="KEY" spellcheck="false" autocomplete="off" value="${esc(k)}">` +
    `<span class="eq" aria-hidden="true">=</span>` +
    `<input class="v" placeholder="VALUE" spellcheck="false" autocomplete="off" value="${esc(v)}">` +
    `<button class="del" type="button" aria-label="删除这个变量" title="删除">` +
    `<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">` +
    `<path fill="currentColor" d="M6.4 5 5 6.4 10.6 12 5 17.6 6.4 19 12 13.4 17.6 19 19 17.6 13.4 12 19 6.4 17.6 5 12 10.6 6.4 5Z"/>` +
    `</svg></button>`;
  row.querySelector(".del").onclick = () => { row.remove(); fitWindow(); };
  c.appendChild(row);
  if (focus) {
    fitWindow();
    if (!k) row.querySelector(".k").focus();
  }
}

function collectEnv(containerId) {
  const out = {};
  for (const row of document.querySelectorAll(`#${containerId} .env-row`)) {
    const k = row.querySelector(".k").value.trim();
    const v = row.querySelector(".v").value;
    if (k) out[k] = v;
  }
  return out;
}

// ---- common settings ----
async function loadSettings() {
  SETTINGS = await api().get_settings();
  renderCommon();
}

function renderCommon() {
  document.getElementById("proxy").checked = !!SETTINGS.check_system_proxy;
  renderEnv("common-env", SETTINGS.env_vars);
  const n = Object.keys(SETTINGS.env_vars || {}).length;
  document.getElementById("common-summary").textContent =
    (SETTINGS.check_system_proxy ? "启动前检查系统代理" : "不检查系统代理") +
    " · " + (n ? `${n} 个通用环境变量` : "没有通用环境变量");
}

async function saveSettings() {
  animateBrand();
  const payload = {
    check_system_proxy: document.getElementById("proxy").checked,
    env_vars: collectEnv("common-env"),
  };
  await api().save_settings(payload);
  SETTINGS = payload;
  setEditorOpen("common", false);
  renderCommon();
  toast("已保存");
}

// ---- per-app settings ----
async function loadAppSettings(id) {
  APP_SETTINGS[id] = await api().get_app_settings(id);
  renderAppEditor(id);
  rerenderBay(id);
}

function renderPath(id) {
  const el = document.getElementById(`path-${id}`);
  const s = APP_SETTINGS[id] || {};
  el.textContent = s.path || "自动检测";
  el.classList.toggle("is-auto", !s.path);
}

function renderAppEditor(id) {
  const s = APP_SETTINGS[id] || { env_vars: {}, path: "" };
  renderPath(id);
  renderEnv(`env-${id}`, s.env_vars);
}

async function saveAppSettings(id) {
  animateBrand();
  const env_vars = collectEnv(`env-${id}`);
  await api().save_app_settings(id, { env_vars });
  APP_SETTINGS[id] = { ...(APP_SETTINGS[id] || {}), env_vars };
  setEditorOpen(id, false);
  rerenderBay(id);
  toast("已保存");
}

// ---- wiring ----
document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("gear-common").onclick = () => toggleEditor("common");
  document.getElementById("cancel-common").onclick = () => setEditorOpen("common", false);
  document.getElementById("add-common").onclick = () => addEnvRow("common-env");
  document.getElementById("save-settings").onclick = saveSettings;
  document.getElementById("update-action").onclick = updateAction;
  document.getElementById("update-cancel").onclick = async () => renderUpdate(await api().cancel_update());
  document.getElementById("update-release").onclick = () => api().open_release_page();
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeAllEditors();
  });
  window.addEventListener("focus", refreshOnReturn);
  window.addEventListener("focus", animateBrand);
  document.addEventListener("visibilitychange", refreshOnReturn);
});

window.addEventListener("pywebviewready", init);

if (new URLSearchParams(location.search).has("preview")) {
  document.documentElement.classList.add("preview");
  APPS = [
    { id: "claude", display: "Claude", found: true, running: true },
    { id: "codex", display: "Codex", found: false, running: false },
  ];
  const appSettings = {
    claude: { env_vars: { ANTHROPIC_BASE_URL: "https://api.example.com" }, path: "" },
    codex: { env_vars: {}, path: "" },
  };
  let previewUpdate = {
    phase: "idle", current: "0.3.0", latest: "", can_install: true,
    message: "手动检查新版本", progress: 0,
  };
  let previewTimer;
  window.pywebview = {
    api: {
      get_update_status: async () => previewUpdate,
      check_for_updates: async () => {
        const mode = new URLSearchParams(location.search).get("update");
        previewUpdate = { ...previewUpdate, phase: "checking", message: "正在检查 GitHub Releases…" };
        previewTimer = setTimeout(() => {
          previewUpdate = { ...previewUpdate,
            phase: mode === "error" ? "error" : mode === "latest" ? "latest" : "available",
            latest: "0.4.0", message: mode === "error" ? "GitHub 请求次数受限，请稍后重试。"
              : mode === "latest" ? "当前已是最新版本。" : "发现新版本 0.4.0",
          };
        }, 600);
        return previewUpdate;
      },
      download_update: async () => {
        previewUpdate = { ...previewUpdate, phase: "downloading", progress: 0, message: "正在下载安装包…" };
        const tick = () => {
          previewUpdate = { ...previewUpdate, progress: previewUpdate.progress + 20 };
          if (previewUpdate.progress === 100) {
            previewUpdate = { ...previewUpdate, phase: "ready", message: "更新已就绪，安装后将重新打开 Claude China。" };
          } else previewTimer = setTimeout(tick, 500);
        };
        previewTimer = setTimeout(tick, 500);
        return previewUpdate;
      },
      cancel_update: async () => {
        clearTimeout(previewTimer);
        previewUpdate = { ...previewUpdate, phase: "available", message: "已取消下载，可稍后重试。" };
        return previewUpdate;
      },
      install_update: async () => {
        toast("界面预览：此处会退出启动器，安装并重新打开");
        return previewUpdate;
      },
      open_release_page: async () => ({ ok: true }),
      list_apps: async () => APPS,
      get_settings: async () => ({
        check_system_proxy: true,
        env_vars: { HTTP_PROXY: "http://127.0.0.1:7890", HTTPS_PROXY: "http://127.0.0.1:7890" },
      }),
      save_settings: async () => ({ ok: true }),
      get_app_settings: async (id) => appSettings[id],
      save_app_settings: async () => ({ ok: true }),
      pick_app_path: async () => ({ ok: false }),
      fit_window: async () => ({ ok: true }),
      launch_app: async (id) =>
        id === "claude" ? { ok: true } : { ok: false, error: "系统代理未开启，已取消启动" },
      stop_app: async () => ({ ok: true }),
    },
  };
  document.addEventListener("DOMContentLoaded", init);
}
