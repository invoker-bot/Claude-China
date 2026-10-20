let SAFETY_SETTINGS = { enabled: true, block_unknown: true, environment: {} };
const SAFETY_REPORTS = {};
let safetyChecking = false;

function safetyDraft() {
  return { enabled: document.getElementById("safety-enabled").checked,
    block_unknown: document.getElementById("safety-strict").checked };
}
function renderLocalEnvironment(environment) {
  const values = [["系统时区", `${environment.timezone || "未知"} ${environment.utc_offset || ""}`.trim()],
    ["系统语言", environment.language || "未知"], ["系统地区", environment.region || "未知"]];
  document.getElementById("safety-local").innerHTML = values.map(([name, value]) =>
    `<div><dt>${esc(name)}</dt><dd>${esc(value)}</dd></div>`).join("");
}
function renderSafetySettings() {
  document.getElementById("safety-enabled").checked = SAFETY_SETTINGS.enabled;
  document.getElementById("safety-strict").checked = SAFETY_SETTINGS.block_unknown;
  document.getElementById("safety-blocked-regions").textContent =
    (SAFETY_SETTINGS.policy?.blocked_regions || []).map(region => `${region.name}（${region.code}）`).join("、") || "未读取到地区规则";
  renderLocalEnvironment(SAFETY_SETTINGS.environment || {});
  const select = document.getElementById("safety-app");
  if (!select.options.length) select.innerHTML = APPS.map(app => `<option value="${esc(app.id)}">${esc(app.display)}</option>`).join("");
  SAVED_DRAFTS.safety = draftSnapshot("safety");
  renderSafetyReport();
}
function rememberSafetyReport(id, report) {
  if (!report) return;
  SAFETY_REPORTS[id] = report;
  if (document.getElementById("safety-app").value === id) renderSafetyReport();
}
function renderSafetyReport() {
  const report = SAFETY_REPORTS[document.getElementById("safety-app").value];
  const box = document.getElementById("safety-result");
  box.dataset.status = report?.status || "idle";
  if (!report) { box.innerHTML = "<p>尚未检查。启动时会重新检测。</p>"; return; }
  const label = { supported: "地区规则通过", unsupported: "禁止地区", unknown: "无法确认" }[report.status] || "无法确认";
  const blocked = SAFETY_SETTINGS.enabled && (report.status !== "supported" &&
    (report.status !== "unknown" || SAFETY_SETTINGS.block_unknown));
  const effect = !SAFETY_SETTINGS.enabled ? "自动检查已关闭" : blocked ? "将阻止启动" : "地区检查允许启动";
  const network = report.network || {};
  const timestamp = report.checked_at ? new Date(report.checked_at).toLocaleString() : "刚刚";
  box.innerHTML = `<div class="safety-result-head"><strong>${icon("shield")}${label}</strong><span>${esc(effect)}</span></div>` +
    `<p>${esc(report.reason || "")}</p>` +
    `<dl class="safety-details"><div><dt>出口 IP</dt><dd>${esc(network.ip || "未获取")}</dd></div>` +
    `<div><dt>出口地区</dt><dd>${esc([network.country, network.country_code, network.region].filter(Boolean).join(" · ") || "未知")}</dd></div>` +
    `<div><dt>检测连接</dt><dd>${esc(report.route || "尚未确认")}</dd></div></dl>` +
    `<p class="field-hint">上次检查：${esc(timestamp)}${report.policy?.updated_on ? `<br>统一规则更新：${esc(report.policy.updated_on)}` : ""}</p>`;
  if (report.environment) renderLocalEnvironment(report.environment);
}
async function checkSafety() {
  if (safetyChecking) return;
  const id = document.getElementById("safety-app").value;
  safetyChecking = true;
  const button = document.getElementById("safety-check");
  button.disabled = true; button.classList.add("is-busy");
  document.getElementById("safety-app").disabled = true;
  const box = document.getElementById("safety-result");
  box.dataset.status = "checking"; box.innerHTML = "<p>正在检查出口 IP 与地区限制规则…</p>";
  try { rememberSafetyReport(id, await api().check_safety(id)); }
  catch (_) { rememberSafetyReport(id, { status: "unknown", reason: "环境检查失败，请重试。", checked_at: new Date().toISOString() }); }
  finally {
    safetyChecking = false; button.disabled = false; button.classList.remove("is-busy");
    document.getElementById("safety-app").disabled = false;
  }
}
document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("safety-app").onchange = renderSafetyReport;
  document.getElementById("safety-check").onclick = checkSafety;
  document.getElementById("save-safety").onclick = () => saveEditor("safety");
  document.getElementById("cancel-safety").onclick = () => cancelSettings("safety");
  document.getElementById("safety-source").onclick = async () => {
    try { const result = await api().open_safety_source(document.getElementById("safety-app").value); if (!result.ok) toast("无法打开规则页面。"); }
    catch (_) { toast("无法打开规则页面。"); }
  };
});
