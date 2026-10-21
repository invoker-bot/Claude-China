const api = () => window.pywebview.api;
let APPS = [];
let SETTINGS = { check_system_proxy: true, auto_proxy_env: false, env_vars: {} };
const APP_SETTINGS = {};
let READY = false;
let lastRefresh = 0;
let brandAnimation;
let UPDATE = { phase: "idle" };
let updatePoll;
let pendingPanel;
let openingUpdates = false;
let currentPanel = "common";
let MAIN_VIEW = "apps";
let fitted = false;
const BUSY_APPS = new Set();
const BAY_ERRORS = {};

function esc(value) {
  return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#x27;");
}
function findApp(id) { return APPS.find(app => app.id === id); }
function animateBrand() {
  const mark = document.getElementById("brand-mark");
  if (!mark || document.hidden || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  if (brandAnimation && brandAnimation.playState === "running") return;
  brandAnimation = mark.animate([{ transform: "rotate(0)" }, { transform: "rotate(-15deg) scale(.92)" }, { transform: "rotate(0)" }], { duration: 700 });
}
async function init() {
  try {
    await I18n.init();
    await initWindowControls();
    APPS = await api().list_apps();
    renderApps();
    SETTINGS = await api().get_settings();
    renderCommon();
    SAFETY_SETTINGS = await api().get_safety_settings();
    renderSafetySettings();
    await Promise.all(APPS.map(async app => {
      APP_SETTINGS[app.id] = await api().get_app_settings(app.id);
      renderAppEditor(app.id);
      rerenderBay(app.id);
    }));
    await refreshTakeover();
    renderUpdate(await api().get_update_status());
    READY = true;
    lastRefresh = Date.now();
    markDrafts();
    fitWindow();
    animateBrand();
    if (UPDATE.phase === "error" && !pendingPanel) pendingPanel = "update-status";
    if (pendingPanel) { const panel = pendingPanel; pendingPanel = null; window.openLauncherPanel(panel); }
  } catch (_) { toast("无法读取应用设置，请重新打开启动器。"); }
}

window.openLauncherPanel = panel => {
  if (!READY) { pendingPanel = panel; return; }
  if (panel === "settings") showSettings("common");
  else if (panel === "updates" || panel === "update-status") openUpdates(panel === "updates");
  else showSettings(panel);
};
function setMainView(view) {
  const views = { apps: ['launcher-main', 'home-button'], terminals: ['terminals-main', 'terminals-button'], usage: ['usage-main', 'usage-button'], settings: ['settings-main', 'open-settings'] };
  if (!Object.prototype.hasOwnProperty.call(views, view)) return;
  MAIN_VIEW = view;
  for (const [name, [pageId, buttonId]] of Object.entries(views)) {
    const active = name === view;
    document.getElementById(pageId).hidden = !active;
    const button = document.getElementById(buttonId);
    button.classList.toggle('is-active', active);
    if (active) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current');
  }
  if (document.activeElement.closest('[hidden]')) document.getElementById(views[view][1]).focus();
  updateWorkspaceCount();
  markDrafts();
  if (view === 'terminals') refreshTerminals();
  if (view === 'usage') refreshUsage(true);
}
function updateWorkspaceCount() {
  document.getElementById('app-count').textContent = MAIN_VIEW === 'usage' ? '本机统计' : MAIN_VIEW === 'terminals' ? `${TERMINALS.profiles.length} 个配置` : MAIN_VIEW === 'settings' ? '本机设置' : `${APPS.length} 个应用`;
}
function showSettings(panel = currentPanel) {
  if (!READY) { pendingPanel = panel; return; }
  const headings = {
    common: ["通用设置", "应用启动时使用的共同配置。"],
    safety: ["安全检查", "查看本机环境，检查三个应用共用的地区限制规则。"],
    updates: ["版本更新", "获取 Claude China 桌面版的最新版本。"],
    about: ["关于", "你的 AI 桌面应用，集中管理。"],
  };
  if (!headings[panel] && !findApp(panel)) panel = "common";
  currentPanel = panel;
  const app = findApp(panel);
  if (app) refreshTakeover(panel);
  const heading = headings[panel] || [app.display, "管理此应用的启动路径和专有环境变量。"];
  document.getElementById("settings-title").textContent = heading[0];
  document.getElementById("settings-description").textContent = heading[1];
  for (const section of document.querySelectorAll(".settings-panel")) {
    const active = section.id === (panel === "updates" ? "update-panel" : panel === "about" ? "about-panel" : `editor-${panel}`);
    section.hidden = !active;
    section.inert = !active;
    if (section.classList.contains("editor")) section.classList.toggle("is-open", active);
  }
  for (const link of document.querySelectorAll(".settings-link")) {
    const active = link.dataset.panel === panel;
    link.classList.toggle("is-active", active);
    if (active) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  }
  setMainView("settings");
}
// Fit once for the initial layout and small screens. Opening an
// editor or adding rows must never resize a window the user has already sized.
function fitWindow() {
  if (fitted || !window.pywebview || !api().fit_window) return;
  fitted = true;
  api().fit_window({ inner: window.innerHeight, wanted: 680 });
}
function renderApps() {
  const list = document.getElementById("apps");
  list.innerHTML = "";
  for (const app of APPS) {
    const id = esc(app.id), name = esc(app.display);
    const bay = document.createElement("section");
    bay.className = "bay bay--app";
    bay.id = `bay-${id}`;
    bay.setAttribute("aria-labelledby", `name-${id}`);
    bay.innerHTML = `<div class="app-top"><div class="app-symbol app-symbol--${id}" aria-hidden="true">${appSymbol(app.id)}</div>` +
      `<button class="icon-button" type="button" id="gear-${id}" aria-controls="editor-${id}" aria-label="${name} 专有设置" title="${name} 专有设置">${icon("settings")}</button></div>` +
      `<h2 class="bay-name" id="name-${id}">${name}</h2>` +
      `<p class="bay-status"><span class="lamp" aria-hidden="true"></span><span id="status-${id}" role="status"></span></p>` +
      `<p class="app-detail" id="detail-${id}"></p><div class="bay-actions">` +
      `<button class="btn btn--key" id="btn-launch-${id}" type="button">启动</button>` +
      `<button class="btn btn--stop" id="btn-stop-${id}" type="button" aria-label="停止 ${name}" title="停止 ${name}">${icon("stop")}<span class="stop-text">停止</span></button>` +
      `<button class="btn btn-config" id="btn-config-${id}" type="button">${icon("folder")}选择路径</button></div>`;
    list.appendChild(bay);
    document.getElementById(`btn-launch-${app.id}`).onclick = () => onAction(app.id, "launch");
    document.getElementById(`btn-stop-${app.id}`).onclick = () => onAction(app.id, "stop");
    document.getElementById(`btn-config-${app.id}`).onclick = () => showSettings(app.id);
    document.getElementById(`gear-${app.id}`).onclick = () => showSettings(app.id);
    updateBay(app.id, app.found, app.running);
  }
  updateWorkspaceCount();
  renderAppSettingsPanels();
}
function rerenderBay(id) { const app = findApp(id); if (app) updateBay(id, app.found, app.running); }
function updateBay(id, found, running) {
  const app = findApp(id);
  if (app) { app.found = found; app.running = running; }
  const bay = document.getElementById(`bay-${id}`);
  if (!bay) return;
  const error = BAY_ERRORS[id], busy = BUSY_APPS.has(id);
  bay.classList.toggle("is-running", !!(found && running));
  bay.classList.toggle("is-missing", !found);
  bay.classList.toggle("has-error", !!error);
  document.getElementById(`status-${id}`).textContent = error || (busy ? "正在处理…" : !found ? "未检测到安装" : running ? "运行中" : "未运行");
  const count = Object.keys(APP_SETTINGS[id]?.env_vars || {}).length;
  document.getElementById(`detail-${id}`).innerHTML = icon(!found ? "folder" : count ? "document" : "sliders") +
    `<span>${!found ? "选择应用路径后即可启动" : count ? `专有环境变量 · ${count} 项` : "使用通用设置"}</span>`;
  const launch = document.getElementById(`btn-launch-${id}`), stop = document.getElementById(`btn-stop-${id}`);
  launch.hidden = !found; stop.hidden = !found;
  document.getElementById(`btn-config-${id}`).hidden = found;
  launch.innerHTML = icon(running ? "refresh" : "play") + `<span>${running ? "重启" : "启动"}</span>`;
  launch.disabled = busy; stop.disabled = busy;
  bay.setAttribute("aria-busy", String(busy));
}
async function onAction(id, mode) {
  if (BUSY_APPS.has(id)) return;
  BUSY_APPS.add(id); delete BAY_ERRORS[id]; rerenderBay(id); animateBrand();
  try {
    const result = await api()[mode === "stop" ? "stop_app" : "launch_app"](id);
    rememberSafetyReport(id, result.safety);
    if (!result.ok) BAY_ERRORS[id] = result.error || "操作失败，请重试";
    await refresh();
    if (result.ok) toast(mode === "stop" ? `已停止 ${findApp(id).display}` : `已发送 ${findApp(id).display} 启动请求`);
  } catch (_) { BAY_ERRORS[id] = "操作失败，请重试"; }
  finally { BUSY_APPS.delete(id); rerenderBay(id); }
}
async function refresh(redetect = false) {
  lastRefresh = Date.now();
  APPS = await api().list_apps(redetect);
  for (const app of APPS) updateBay(app.id, app.found, app.running);
}
async function refreshOnReturn() {
  if (!READY || document.hidden || Date.now() - lastRefresh < 1500) return;
  try { await refresh(); } catch (_) { toast("暂时无法读取应用状态。"); }
}
function toast(message) {
  const el = document.getElementById("toast");
  el.textContent = message; el.classList.add("is-visible");
  clearTimeout(toast.timer); toast.timer = setTimeout(() => el.classList.remove("is-visible"), 2800);
}
async function openUpdates(check) {
  showSettings("updates");
  document.getElementById("update-warning").hidden = true;
  if (openingUpdates) return;
  openingUpdates = true;
  try {
    const state = await api().get_update_status();
    renderUpdate(check && ["idle", "latest", "error"].includes(state.phase) ? await api().check_for_updates() : state);
  } catch (_) { renderUpdate({ ...UPDATE, phase: "error", message: "无法检查更新，请重试。" }); }
  finally { openingUpdates = false; }
}
function renderUpdate(state) {
  UPDATE = state;
  const busy = ["checking", "downloading", "installing"].includes(state.phase);
  const target = ["available", "downloading", "ready", "installing"].includes(state.phase) && state.latest;
  document.getElementById("update-version").textContent = (state.current ? `v${state.current}` : "") + (target ? ` → v${state.latest}` : "");
  for (const id of ["about-version", "footer-version"]) document.getElementById(id).textContent = state.current ? `v${state.current}` : "";
  let message = state.message || "手动检查新版本";
  if (state.phase === "available" && !state.can_install) message += ` · ${state.reason}`;
  if (state.phase === "downloading") message += ` ${state.progress || 0}%`;
  document.getElementById("update-status").textContent = message;
  document.getElementById("update-panel").classList.toggle("has-error", state.phase === "error");
  document.getElementById("update-hint").textContent = state.phase === "downloading" ? "切换页面后仍会继续下载，可从设置或托盘查看进度。" : "安装更新会重启启动器，已启动的应用不受影响。";
  const button = document.getElementById("update-action");
  button.disabled = busy || (state.phase === "available" && !state.can_install);
  button.textContent = ({checking: "正在检查…", downloading: "正在下载…", available: "下载更新", ready: "安装并重启", installing: "正在重启…", error: "重试检查"})[state.phase] || "检查更新";
  document.getElementById("update-cancel").hidden = state.phase !== "downloading";
  const progress = document.getElementById("update-progress");
  progress.hidden = state.phase !== "downloading"; progress.value = state.progress || 0;
  clearTimeout(updatePoll);
  if (busy) updatePoll = setTimeout(refreshUpdate, 500);
}
async function refreshUpdate() {
  try { renderUpdate(await api().get_update_status()); }
  catch (_) { renderUpdate({ ...UPDATE, phase: "error", message: "无法获取更新状态，请重试。" }); }
}
async function updateAction() {
  const phase = UPDATE.phase;
  if (openingUpdates || ["checking", "downloading", "installing"].includes(phase)) return;
  const warning = document.getElementById("update-warning");
  warning.hidden = true;
  if (phase === "ready" && hasUnsavedSettings()) {
    warning.textContent = "请先保存或取消有修改的设置，再安装更新。"; warning.hidden = false; return;
  }
  document.getElementById("update-action").disabled = true;
  try {
    const action = phase === "available" ? "download_update" : phase === "ready" ? "install_update" : "check_for_updates";
    renderUpdate(await api()[action]());
  } catch (_) { renderUpdate({ ...UPDATE, phase: "error", message: "无法完成操作，请重试。" }); }
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("open-settings").onclick = () => showSettings();
  document.getElementById("gear-common").onclick = () => window.openLauncherPanel("settings");
  document.getElementById("home-button").onclick = () => setMainView("apps");
  document.getElementById("terminals-button").onclick = () => setMainView("terminals");
  document.getElementById("open-updates").onclick = () => window.openLauncherPanel("updates");
  document.getElementById("footer-about").onclick = () => window.openLauncherPanel("about");
  document.getElementById("refresh-apps").onclick = async event => {
    const button = event.currentTarget;
    if (!READY || button.disabled) return;
    button.disabled = true; button.classList.add("is-busy");
    try { await refresh(true); toast("应用状态已刷新"); } catch (_) { toast("无法刷新应用状态，请重试。"); }
    finally { button.disabled = false; button.classList.remove("is-busy"); }
  };
  document.querySelector(".settings-nav").onclick = event => {
    const panel = event.target.closest("[data-panel]")?.dataset.panel;
    if (panel) panel === "updates" ? openUpdates(false) : showSettings(panel);
  };
  document.getElementById("settings-main").addEventListener("input", markDrafts);
  document.getElementById("cancel-common").onclick = () => cancelSettings("common");
  document.getElementById("add-common").onclick = () => addEnvRow("common-env");
  document.getElementById("save-settings").onclick = () => saveEditor("common");
  document.getElementById("update-action").onclick = updateAction;
  document.getElementById("update-cancel").onclick = async () => {
    try { renderUpdate(await api().cancel_update()); } catch (_) { toast("无法取消下载，请重试。"); }
  };
  for (const id of ["update-release", "about-release"]) document.getElementById(id).onclick = async () => {
    try { const result = await api().open_release_page(); if (!result.ok) toast("无法打开发布页面。"); } catch (_) { toast("无法打开发布页面。"); }
  };
  document.getElementById("about-updates").onclick = () => openUpdates(true);
  window.addEventListener("focus", refreshOnReturn);
  window.addEventListener("focus", animateBrand);
  document.addEventListener("visibilitychange", refreshOnReturn);
});
window.addEventListener("pywebviewready", init);
