// Each category keeps its DOM draft until saved or explicitly cancelled.
// Switching pages and categories never writes user configuration.
const DRAFT_PATHS = {};
const SAVED_DRAFTS = {};
const SAVING = new Set();

function renderAppSettingsPanels() {
  const editors = document.getElementById("app-editors");
  const nav = document.getElementById("settings-app-nav");
  editors.innerHTML = ""; nav.innerHTML = "";
  for (const app of APPS) {
    const id = esc(app.id), name = esc(app.display);
    nav.insertAdjacentHTML("beforeend", `<button class="settings-link" id="nav-${id}" data-panel="${id}" type="button"><span class="nav-app-symbol">${appSymbol(app.id)}</span>${name}<span class="draft-dot" aria-hidden="true"></span></button>`);
    editors.insertAdjacentHTML("beforeend",
      `<section class="editor settings-panel" id="editor-${id}" hidden inert><div class="editor-body">` +
      `<div class="field"><h3 class="field-label">应用路径</h3><p class="field-hint">默认自动检测，也可以手动选择。保存后生效。</p>` +
      `<div class="path-row"><code class="path-value" id="path-${id}"></code><button class="btn" id="pick-${id}" type="button">${icon("folder")}选择路径</button></div>` +
      `<button class="text-button path-reset" id="reset-${id}" type="button">恢复自动检测</button></div>` +
      `<div class="field"><h3 class="field-label">接管原入口</h3><p class="field-hint">受支持的安装方式可在原入口启动和同路径更新重启时，使用已保存的检查和环境变量。此开关独立生效；Windows 会请求管理员授权。</p><p id="takeover-status-${id}" role="status">正在读取接管状态…</p><button class="btn" id="takeover-toggle-${id}" type="button" disabled>启用接管</button><p class="form-error" id="takeover-error-${id}" role="alert" hidden></p></div>` +
      `<div class="field"><h3 class="field-label">专有环境变量</h3><p class="field-hint">只对 ${name} 生效，同名变量优先于通用设置。</p>` +
      `<div class="env-columns" aria-hidden="true"><span>变量名</span><span>值</span></div><div class="env-list" id="env-${id}"></div>` +
      `<button class="add-row" id="add-${id}" type="button">${icon("plus")}添加变量</button></div>` +
      `<p class="form-error" id="error-${id}" role="alert" hidden></p></div>` +
      `<div class="editor-actions"><span class="save-state" id="save-state-${id}">仅保存在当前设备</span><button class="btn" id="cancel-${id}" type="button">取消修改</button><button class="btn btn--solid" id="save-${id}" type="button">保存设置</button></div></section>`);
    document.getElementById(`pick-${app.id}`).onclick = () => pickPath(app.id);
    document.getElementById(`reset-${app.id}`).onclick = () => {
      DRAFT_PATHS[app.id] = ""; renderPath(app.id); markDrafts();
    };
    document.getElementById(`add-${app.id}`).onclick = () => addEnvRow(`env-${app.id}`);
    document.getElementById(`cancel-${app.id}`).onclick = () => cancelSettings(app.id);
    document.getElementById(`save-${app.id}`).onclick = () => saveEditor(app.id);
    document.getElementById(`takeover-toggle-${app.id}`).onclick = () => toggleTakeover(app.id);
  }
}

const TAKEOVER = {};
const TAKEOVER_REQUESTS = {};
const TAKEOVER_BUSY = new Set();
function renderTakeover(id) {
  const state = TAKEOVER[id] || {};
  document.getElementById(`takeover-status-${id}`).textContent = state.message || '正在读取接管状态…';
  const button = document.getElementById(`takeover-toggle-${id}`);
  button.textContent = state.can_disable || state.enabled ? '停用接管' : '启用接管';
  button.disabled = TAKEOVER_BUSY.has(id) || SAVING.has(id) || !(state.supported || state.can_disable);
}
async function refreshTakeover(id) {
  if (!id) return Promise.all(APPS.map(app => refreshTakeover(app.id)));
  const button = document.getElementById(`takeover-toggle-${id}`);
  if (!button) return;
  const request = TAKEOVER_REQUESTS[id] = (TAKEOVER_REQUESTS[id] || 0) + 1;
  button.disabled = true;
  let state;
  try { state = await api().get_takeover_status(id); }
  catch (_) { state = { supported: false, enabled: false, message: '无法读取接管状态。' }; }
  if (request !== TAKEOVER_REQUESTS[id]) return;
  TAKEOVER[id] = state;
  renderTakeover(id);
}
async function toggleTakeover(id) {
  if (TAKEOVER_BUSY.has(id)) return;
  const error = document.getElementById(`takeover-error-${id}`);
  error.hidden = true;
  if (hasUnsavedSettings()) {
    error.textContent = '请先保存或取消修改，再设置原入口接管。'; error.hidden = false; return;
  }
  TAKEOVER_BUSY.add(id);
  TAKEOVER_REQUESTS[id] = (TAKEOVER_REQUESTS[id] || 0) + 1;
  renderTakeover(id);
  try {
    const state = TAKEOVER[id] || {};
    const result = await api().set_takeover(id, !(state.can_disable || state.enabled));
    if (!result.ok) throw new Error(result.error || '无法修改接管设置。');
  } catch (reason) { error.textContent = reason.message; error.hidden = false; }
  finally { TAKEOVER_BUSY.delete(id); await refreshTakeover(id); }
}

function envContainer(id) { return id === "common" ? "common-env" : `env-${id}`; }
function draftSnapshot(id) {
  if (id === "safety") return JSON.stringify(safetyDraft());
  return JSON.stringify({
    setting: id === "common" ? {
      check_system_proxy: document.getElementById("proxy").checked,
      auto_proxy_env: document.getElementById("auto-proxy-env").checked,
    } : DRAFT_PATHS[id] || "",
    rows: Array.from(document.querySelectorAll(`#${envContainer(id)} .env-row`), row =>
      [row.querySelector(".k").value, row.querySelector(".v").value]),
  });
}
function isDirty(id) { return SAVED_DRAFTS[id] !== undefined && draftSnapshot(id) !== SAVED_DRAFTS[id]; }
function hasUnsavedSettings() { return SAVING.size > 0 || ["common", "safety", ...APPS.map(a => a.id)].some(isDirty); }
function markDrafts() {
  for (const id of ["common", "safety", ...APPS.map(a => a.id)]) {
    const dirty = isDirty(id);
    const nav = document.getElementById(`nav-${id}`);
    if (nav) nav.dataset.dirty = String(dirty);
    const state = document.getElementById(`save-state-${id}`);
    if (state) state.textContent = dirty ? "有未保存的修改" : "仅保存在当前设备";
  }
  document.getElementById("open-settings").dataset.dirty = String(hasUnsavedSettings());
}
function renderCommon() {
  document.getElementById("proxy").checked = !!SETTINGS.check_system_proxy;
  document.getElementById("auto-proxy-env").checked = !!SETTINGS.auto_proxy_env;
  renderEnv("common-env", SETTINGS.env_vars);
  const summary = [];
  if (SETTINGS.check_system_proxy) summary.push("启动前检查系统代理");
  if (SETTINGS.auto_proxy_env) summary.push("自动添加代理环境变量");
  document.getElementById("common-summary").textContent = summary.join(" · ") || "启动时不检查系统代理";
  SAVED_DRAFTS.common = draftSnapshot("common");
}
function renderAppEditor(id) {
  const settings = APP_SETTINGS[id] || { env_vars: {}, path: "" };
  DRAFT_PATHS[id] = settings.path || "";
  renderPath(id);
  renderEnv(`env-${id}`, settings.env_vars);
  SAVED_DRAFTS[id] = draftSnapshot(id);
}
function renderPath(id) {
  const el = document.getElementById(`path-${id}`);
  el.toggleAttribute('data-i18n-skip', Boolean(DRAFT_PATHS[id]));
  el.textContent = DRAFT_PATHS[id] || "自动检测";
  el.classList.toggle("is-auto", !DRAFT_PATHS[id]);
  document.getElementById(`reset-${id}`).hidden = !DRAFT_PATHS[id];
}
async function pickPath(id) {
  const button = document.getElementById(`pick-${id}`);
  button.disabled = true;
  try {
    const result = await api().pick_app_path(id, false);
    if (result && result.ok) { DRAFT_PATHS[id] = result.path; renderPath(id); markDrafts(); }
  } catch (_) { showFormError(id, "无法选择应用路径，请重试。"); }
  finally { button.disabled = false; }
}
function renderEnv(containerId, vars) {
  document.getElementById(containerId).innerHTML = "";
  for (const [key, value] of Object.entries(vars || {})) addEnvRow(containerId, key, value, false);
}
function addEnvRow(containerId, key = "", value = "", focus = true) {
  const row = document.createElement("div");
  row.className = "env-row";
  row.innerHTML = `<input class="k" aria-label="变量名" placeholder="变量名" spellcheck="false" autocomplete="off" value="${esc(key)}">` +
    `<input class="v" aria-label="值" placeholder="值" spellcheck="false" autocomplete="off" value="${esc(value)}">` +
    `<button class="icon-button del" type="button" aria-label="删除这个变量" title="删除">${icon("close")}</button>`;
  row.querySelector(".del").onclick = () => { row.remove(); markDrafts(); };
  document.getElementById(containerId).appendChild(row);
  if (focus) { row.querySelector(".k").focus(); markDrafts(); }
}
function collectEnv(containerId) {
  const vars = Object.create(null);
  for (const row of document.querySelectorAll(`#${containerId} .env-row`)) {
    const key = row.querySelector(".k").value.trim(), value = row.querySelector(".v").value;
    if (!key && !value) continue;
    if (!key || key.includes("=") || key.includes("\0") || value.includes("\0")) {
      row.querySelector(".k").focus();
      throw new Error("请填写有效的变量名，且不要包含等号或空字符。");
    }
    if (Object.prototype.hasOwnProperty.call(vars, key)) {
      row.querySelector(".k").focus(); throw new Error(`变量 ${key} 重复，请合并后保存。`);
    }
    vars[key] = value;
  }
  return vars;
}
function showFormError(id, message) {
  const error = document.getElementById(`error-${id}`);
  error.textContent = message; error.hidden = !message;
}
function cancelSettings(id) {
  if (SAVING.has(id)) return;
  if (id === "common") renderCommon(); else if (id === "safety") renderSafetySettings(); else renderAppEditor(id);
  showFormError(id, ""); markDrafts();
}
async function saveEditor(id) {
  if (SAVING.has(id)) return;
  showFormError(id, "");
  let payload;
  try {
    payload = id === "safety" ? safetyDraft() : { env_vars: collectEnv(envContainer(id)) };
    if (id === "common") {
      payload.check_system_proxy = document.getElementById("proxy").checked;
      payload.auto_proxy_env = document.getElementById("auto-proxy-env").checked;
    }
    else if (id !== "safety") payload.path = DRAFT_PATHS[id] || "";
  } catch (error) { showFormError(id, error.message); return; }
  SAVING.add(id);
  const editor = document.getElementById(`editor-${id}`);
  const controls = Array.from(editor.querySelectorAll("input, button"));
  controls.forEach(el => { el.disabled = true; });
  try {
    const result = id === "common" ? await api().save_settings(payload) : id === "safety" ? await api().save_safety_settings(payload) : await api().save_app_settings(id, payload);
    if (!result || !result.ok) throw new Error("保存失败");
    if (id === "common") { SETTINGS = payload; renderCommon(); }
    else if (id === "safety") { SAFETY_SETTINGS = { ...SAFETY_SETTINGS, ...payload }; renderSafetySettings(); }
    else { APP_SETTINGS[id] = payload; renderAppEditor(id); rerenderBay(id); }
    animateBrand(); toast("设置已保存");
    try { await refresh(); } catch (_) { toast("设置已保存，应用状态暂时无法刷新。"); }
  } catch (_) { showFormError(id, "保存失败，修改仍已保留，请重试。"); }
  finally {
    SAVING.delete(id);
    controls.forEach(el => { el.disabled = false; });
    markDrafts();
    if (APPS.some(app => app.id === id)) await refreshTakeover(id);
  }
}
