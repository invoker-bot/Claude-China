let SAFETY_SETTINGS = { enabled: true, block_unknown: true, environment: {} };
const SAFETY_REPORTS = {};
let environmentChecking = false;

let PRIVACY_REPORT = null;
let PRIVACY_REPAIRS = [];
let privacyRepairsLoaded = false;
let privacyRepairsRevision = 0;
const NETWORK_GUARDS = {};
let networkGuardBusy = false;
let networkGuardRevision = 0;
const NETWORK_DRAFTS = {};

function networkGuardTarget() {
  return document.getElementById("network-guard-target").value || document.getElementById("safety-app").value;
}
function renderNetworkControls() {
  const id = networkGuardTarget(), state = NETWORK_GUARDS[id];
  if (!state) return;
  const draft = NETWORK_DRAFTS[id] ||= {mode: state.mode || "proxy", guid: state.tunnel?.guid || "", paths: (state.browser_paths || []).join("\n"), includeCli: state.include_cli === true};
  document.getElementById("network-guard-mode").value = draft.mode;
  const tunnels = document.getElementById("network-guard-tunnel");
  const records = state.tunnels || [];
  tunnels.innerHTML = `<option value="">${esc(I18n.text("请选择隧道"))}</option>` + records.map(item =>
    `<option value="${esc(item.guid)}" ${item.up && item.addresses?.length ? "" : "disabled"}>${esc(item.name)}${item.up ? "" : ` · ${esc(I18n.text("已断开"))}`}</option>`).join("");
  tunnels.value = draft.guid;
  document.getElementById("network-guard-tunnel-field").hidden = draft.mode !== "tun";
  document.getElementById("network-guard-browser-field").hidden = id !== "playwright";
  document.getElementById("network-guard-browser-paths").value = draft.paths;
  document.getElementById("network-guard-cli-field").hidden = id !== "playwright";
  document.getElementById("network-guard-cli").checked = draft.includeCli;
}

function safetyDraft() {
  return { enabled: document.getElementById("safety-enabled").checked,
    block_unknown: document.getElementById("safety-strict").checked,
    router_mode: document.getElementById("safety-router").checked };
}
function renderLocalEnvironment(environment) {
  const values = [["系统时区", `${environment.timezone || "未知"} ${environment.utc_offset || ""}`.trim()],
    ["系统语言", environment.language || "未知"], ["系统地区", environment.region || "未知"]];
  document.getElementById("safety-local").innerHTML = values.map(([name, value]) =>
    `<div><dt>${esc(name)}</dt><dd ${value === "未知" ? "" : "data-i18n-skip"}>${esc(value)}</dd></div>`).join("");
}
function renderSafetySettings() {
  document.getElementById("safety-enabled").checked = SAFETY_SETTINGS.enabled;
  document.getElementById("safety-strict").checked = SAFETY_SETTINGS.block_unknown;
  document.getElementById("safety-router").checked = SAFETY_SETTINGS.router_mode === true;
  document.getElementById("safety-blocked-regions").innerHTML =
    (SAFETY_SETTINGS.policy?.blocked_regions || []).map(region => `<span>${esc(region.name)}</span> (${esc(region.code)})`).join(", ") || "未读取到地区规则";
  renderLocalEnvironment(SAFETY_SETTINGS.environment || {});
  const select = document.getElementById("safety-app");
  if (!select.options.length) select.innerHTML = APPS.map(app => `<option value="${esc(app.id)}">${esc(app.display)}</option>`).join("");
  const target = document.getElementById("network-guard-target");
  if (!target.options.length) target.innerHTML = APPS.map(app => `<option value="${esc(app.id)}">${esc(app.display)}</option>`).join("") + `<option value="playwright">${esc(I18n.text("CLI / Playwright 浏览器"))}</option>`;
  SAVED_DRAFTS.safety = draftSnapshot("safety");
  renderEnvironmentReport();
  loadPrivacyRepairs();
  loadNetworkGuard();
}
async function loadNetworkGuard() {
  const id = networkGuardTarget();
  if (!id || networkGuardBusy) return;
  const revision = networkGuardRevision;
  try {
    const result = await api().get_network_guard(id);
    if (revision !== networkGuardRevision) return;
    NETWORK_GUARDS[id] = result.ok ? result.state : { message: result.error || "无法读取系统网络防护状态。" };
    renderNetworkControls();
  } catch (_) {
    NETWORK_GUARDS[id] = { message: "无法读取系统网络防护状态。" };
  }
  renderEnvironmentReport();
}
async function loadPrivacyRepairs() {
  if (privacyRepairsLoaded) return;
  const revision = privacyRepairsRevision;
  try {
    const result = await api().get_privacy_repairs();
    if (revision !== privacyRepairsRevision) return;
    if (!result.ok) {
      if (result.error) toast(result.error);
      return;
    }
    PRIVACY_REPAIRS = result.repairs || [];
    privacyRepairsLoaded = true;
    renderEnvironmentReport();
  } catch (_) { /* the restore button appears after the next check */ }
}
function rememberSafetyReport(id, report) {
  if (!report) return;
  SAFETY_REPORTS[id] = report;
  if (document.getElementById("safety-app").value === id) renderEnvironmentReport();
}

const REGION_LABELS = { supported: "地区规则通过", unsupported: "禁止地区", unknown: "无法确认" };
const ENVIRONMENT_HEADS = {
  unsupported: ["禁止地区", "将阻止启动"],
  warn: ["存在暴露风险", "建议修复"],
  unknown: ["无法确认", "需要手动确认"],
  ok: ["检查通过", "允许启动"],
};
const PRIVACY_MODES = {
  system_proxy: "系统代理", tun: "TUN / 虚拟网卡", env_proxy: "环境变量代理",
  direct: "直连", unknown: "未知",
};
const PRIVACY_POLICY_STATES = {
  unset: "未设置", disabled: "已限制", public_only: "仅公网接口",
  exposed: "默认（可能暴露）", default: "默认（可能暴露）", custom: "自定义", unknown: "未知",
};
const BROWSER_NAMES = { chrome: "Chrome", edge: "Edge" };

// A blocked region always wins; anything unconfirmed keeps the summary honest.
function environmentStatus(safety, privacy) {
  if (safety?.status === "unsupported") return "unsupported";
  if (safety?.router?.dns?.status === "warning") return "warn";
  const guard = NETWORK_GUARDS[document.getElementById("safety-app").value];
  if (guard?.enabled && !guard.verified) return "warn";
  if (safety?.router) return safety.status === "supported" ? "ok" : "unknown";
  if (privacy?.level === "warn" && !guard?.verified) return "warn";
  if (!safety || !privacy || safety.status === "unknown" || privacy.level === "unknown") return "unknown";
  return "ok";
}
function privacyPolicyLabel(browser) {
  const policy = PRIVACY_REPORT?.policies?.browsers?.[browser] || {};
  const state = I18n.text(PRIVACY_POLICY_STATES[policy.state] || PRIVACY_POLICY_STATES.unknown);
  const managed = policy.source === "machine" ? ` · ${I18n.text("组织管理")}` : "";
  return `${BROWSER_NAMES[browser]}: ${state}${managed}`;
}
function privacyIpv6Label(ipv6) {
  if (!ipv6 || ipv6.default === null || ipv6.default === undefined) return I18n.text("未知");
  if (ipv6.default === false) return I18n.text("未检测到默认路由");
  if (ipv6.tunnel === true) return I18n.text("经隧道");
  return I18n.text("非隧道默认路由（可能泄露）");
}
function updatePrivacyReason(message) {
  if (!PRIVACY_REPORT) return;
  PRIVACY_REPORT.reasons = (PRIVACY_REPORT.reasons || []).filter(reason =>
    !reason.startsWith("未检测到浏览器 WebRTC 限制策略") &&
    !reason.startsWith("已限制浏览器 WebRTC") &&
    !reason.startsWith("策略已"));
  PRIVACY_REPORT.reasons.push(message);
}
function environmentRows(safety, privacy) {
  const rows = [];
  if (safety) {
    const network = safety.network || {};
    const region = REGION_LABELS[safety.status] || REGION_LABELS.unknown;
    const effect = !SAFETY_SETTINGS.enabled && !SAFETY_SETTINGS.router_mode ? "自动检查已关闭"
      : (safety.status !== "supported" && (safety.status !== "unknown" || SAFETY_SETTINGS.block_unknown))
        ? "将阻止启动" : "地区检查允许启动";
    rows.push(["启动规则", `${I18n.text(region)} · ${I18n.text(effect)}`]);
    rows.push(["出口 IP", network.ip || "未获取", !network.ip]);
    rows.push(["出口地区", [network.country, network.country_code, network.region].filter(Boolean).join(" · ") || "未知", !network.country_code]);
    rows.push(["检测连接", safety.route || "尚未确认"]);
    if (safety.router) {
      const labels = {match: "一致", mismatch: "不一致", unavailable: "未检测到默认路由", unknown: "无法判断"};
      for (const service of safety.router.services || [])
        rows.push([`${service.host} (IPv${service.family})`, service.status === "ok"
          ? `${service.ip} · ${service.country_code}` : I18n.text("无法判断"), true]);
      for (const family of [4, 6]) {
        const probe = safety.router[`udp${family}`] || {};
        rows.push([`UDP IPv${family}`, `${I18n.text(labels[probe.status] || "无法判断")}${probe.ip ? ` · ${probe.ip}` : ""}`, true]);
      }
      const dns = safety.router.dns;
      rows.push(["DNS 解析器（单次参考）", dns && typeof dns === "object"
        ? `${dns.ip} · ${dns.country_code} · AS${dns.asn}${dns.status === "warning" ? ` · ${I18n.text("需要复核")}` : ""}`
        : I18n.text("无法判断"), true]);
      rows.push(["浏览器 WebRTC", I18n.text("未验证目标浏览器")]);
      rows.push(["IP 信誉", I18n.text("未查询")]);
    }
  }
  if (privacy) {
    const network = privacy.https || {};
    const udp = privacy.udp || {};
    const consistent = privacy.consistent === true ? "一致" : privacy.consistent === false ? "不一致" : "无法判断";
    rows.push(["代理模式", I18n.text(PRIVACY_MODES[privacy.mode] || PRIVACY_MODES.unknown)]);
    rows.push(["HTTPS 出口", network.ok ? `${network.ip}${network.country ? ` · ${network.country}` : ""}` : "未获取", !network.ip]);
    rows.push(["启动器 UDP 出口（辅助）", udp.ok ? udp.ip : "未获取", !udp.ip]);
    rows.push(["出口一致性", I18n.text(consistent)]);
    rows.push(["浏览器策略", ["chrome", "edge"].map(privacyPolicyLabel).join(" · ")]);
    rows.push(["IPv6", privacyIpv6Label(privacy.ipv6)]);
  }
  return rows;
}
function renderEnvironmentActions(privacy) {
  const actions = document.getElementById("safety-actions");
  if (!actions) return;
  actions.innerHTML = "";
  const id = networkGuardTarget(), guard = NETWORK_GUARDS[id], draft = NETWORK_DRAFTS[id];
  if (guard) {
    const message = document.createElement("p");
    message.className = "field-hint";
    message.textContent = I18n.text(guard.message || "无法读取系统网络防护状态。");
    actions.appendChild(message);
    if (guard.supported) {
      const enable = document.createElement("button");
      enable.type = "button";
      enable.className = "btn";
      enable.id = "network-guard-enable";
      enable.textContent = I18n.text(guard.enabled ? "重新应用网络防护" : "启用网络防护");
      const selected = (guard.tunnels || []).find(item => item.guid === draft?.guid);
      const canApply = draft?.mode === "tun" ? guard.found && selected?.up && selected.addresses?.length &&
        (id !== "playwright" || guard.browser_count || draft.paths.trim()) : guard.can_apply;
      enable.disabled = !canApply || networkGuardBusy || environmentChecking;
      enable.onclick = () => changeNetworkGuard(true);
      actions.appendChild(enable);
    }
    if (guard.can_restore) {
      const restore = document.createElement("button");
      restore.type = "button";
      restore.className = "btn";
      restore.id = "network-guard-restore";
      restore.textContent = I18n.text("还原网络防护");
      restore.disabled = networkGuardBusy || environmentChecking;
      restore.onclick = () => changeNetworkGuard(false);
      actions.appendChild(restore);
    }
    if (guard.verified && guard.proxy) {
      const endpoint = document.createElement("p");
      endpoint.className = "field-hint";
      endpoint.dataset.i18nSkip = "";
      endpoint.textContent = `TCP ${guard.proxy.addresses.join(" / ")} : ${guard.proxy.port} · ${guard.executables.length} EXE`;
      actions.appendChild(endpoint);
    }
    if (guard.tunnel) {
      const tunnel = document.createElement("p");
      tunnel.className = "field-hint"; tunnel.dataset.i18nSkip = "";
      tunnel.textContent = `${guard.tunnel.name} · ${guard.tunnel.guid} · ${guard.executables.length} EXE`;
      actions.appendChild(tunnel);
    }
  }
  if (PRIVACY_REPAIRS.length) {
    const restore = document.createElement("button");
    restore.type = "button";
    restore.className = "btn";
    restore.id = "safety-restore";
    restore.textContent = I18n.text("还原浏览器策略");
    restore.onclick = restoreEnvironment;
    actions.appendChild(restore);
  }
}
async function changeNetworkGuard(enabled) {
  if (networkGuardBusy) return;
  const select = document.getElementById("network-guard-target");
  const id = select.value;
  networkGuardBusy = true;
  networkGuardRevision += 1;
  select.disabled = true;
  for (const element of ["safety-app", "network-guard-mode", "network-guard-tunnel", "network-guard-browser-paths", "network-guard-cli"])
    document.getElementById(element).disabled = true;
  document.getElementById("safety-check").disabled = true;
  renderEnvironmentActions(PRIVACY_REPORT);
  try {
    const draft = NETWORK_DRAFTS[id];
    const options = {mode: draft.mode, tunnel_guid: draft.guid};
    if (id === "playwright") {
      options.browser_paths = draft.paths.split("\n").map(value => value.trim()).filter(Boolean);
      options.include_cli = draft.includeCli;
    }
    const result = await (enabled ? api().apply_network_guard(id, options) : api().restore_network_guard(id));
    if (!result.ok) toast(result.error || "系统网络防护操作失败，请重试。");
    else {
      NETWORK_GUARDS[id] = result.state;
      toast(enabled ? (result.state.verified ? "网络防护已启用，WebRTC 保持启用。" : result.state.message) : "网络防护已还原。");
    }
  } catch (_) { toast("系统网络防护操作失败，请重试。"); }
  finally {
    networkGuardBusy = false;
    select.disabled = false;
    for (const element of ["safety-app", "network-guard-mode", "network-guard-tunnel", "network-guard-browser-paths", "network-guard-cli"])
      document.getElementById(element).disabled = false;
    document.getElementById("safety-check").disabled = false;
    await loadNetworkGuard();
  }
}
function renderEnvironmentReport() {
  const box = document.getElementById("safety-result");
  if (!box) return;
  const safety = SAFETY_REPORTS[document.getElementById("safety-app").value] || null;
  const privacy = PRIVACY_REPORT;
  if (!safety && !privacy) {
    box.dataset.status = "idle";
    box.innerHTML = "<p>尚未检查。启动时会重新检测地区。</p>";
    renderEnvironmentActions(null);
    return;
  }
  const status = environmentStatus(safety, privacy);
  box.dataset.status = status;
  const [label, effect] = ENVIRONMENT_HEADS[status];
  const rows = environmentRows(safety, privacy);
  const reasons = [];
  if (safety?.reason) reasons.push(I18n.text(safety.reason));
  for (const reason of privacy?.reasons || []) reasons.push(I18n.text(reason));
  const stamps = [safety?.checked_at, privacy?.checked_at].filter(Boolean).sort();
  const checkedAt = stamps.length ? new Date(stamps[stamps.length - 1]).toLocaleString(I18n.locale()) : "刚刚";
  box.innerHTML = `<div class="safety-result-head"><strong>${icon("shield")}${esc(I18n.text(label))}</strong><span>${esc(I18n.text(effect))}</span></div>` +
    `<dl class="safety-details">${rows.map(([name, value, skip]) =>
      `<div><dt>${esc(name)}</dt><dd ${skip ? "data-i18n-skip" : ""}>${esc(value)}</dd></div>`).join("")}</dl>` +
    (reasons.length ? `<p class="field-hint">${reasons.map(reason => esc(reason)).join("<br>")}</p>` : "") +
    `<p class="field-hint">上次检查：${esc(checkedAt)}${safety?.policy?.updated_on ? `<br>统一规则更新：${esc(safety.policy.updated_on)}` : ""}</p>`;
  renderEnvironmentActions(privacy);
}

async function checkEnvironment() {
  if (environmentChecking || networkGuardBusy) return;
  const id = document.getElementById("safety-app").value;
  environmentChecking = true;
  const button = document.getElementById("safety-check");
  button.disabled = true; button.classList.add("is-busy");
  document.getElementById("safety-app").disabled = true;
  const box = document.getElementById("safety-result");
  box.dataset.status = "checking"; box.innerHTML = "<p>正在检查出口地区与 WebRTC 出口…</p>";
  const [safetyResult, privacyResult] = await Promise.allSettled([
    api().check_safety(id), SAFETY_SETTINGS.router_mode ? Promise.resolve(null) : api().check_privacy()]);
  if (safetyResult.status === "fulfilled") SAFETY_REPORTS[id] = safetyResult.value;
  else SAFETY_REPORTS[id] = { status: "unknown", reason: "环境检查失败，请重试。", checked_at: new Date().toISOString() };
  if (SAFETY_SETTINGS.router_mode) {
    PRIVACY_REPORT = null;
  } else if (privacyResult.status === "fulfilled") {
    PRIVACY_REPORT = privacyResult.value.report || null;
    PRIVACY_REPAIRS = privacyResult.value.repairs || [];
    privacyRepairsLoaded = true;
    privacyRepairsRevision += 1;
    if (privacyResult.value.warning) toast(privacyResult.value.warning);
  } else {
    PRIVACY_REPORT = { level: "unknown", mode: "unknown", https: {}, udp: {},
      consistent: null, policies: { supported: true, browsers: {} },
      ipv6: { default: null, tunnel: null }, reasons: ["检查失败，请重试。"] };
  }
  environmentChecking = false;
  button.disabled = false; button.classList.remove("is-busy");
  document.getElementById("safety-app").disabled = false;
  await loadNetworkGuard();
  renderEnvironmentReport();
}
async function restoreEnvironment() {
  const repairs = PRIVACY_REPAIRS.slice();
  if (!repairs.length) return;
  const names = repairs.map(item => BROWSER_NAMES[item.browser] || item.browser).join(" / ");
  const message = I18n.text("确认还原环境？将删除本应用为 {0} 写入的 WebRTC 策略。").replace("{0}", names);
  if (!window.confirm(message)) return;
  const button = document.getElementById("safety-restore");
  if (button) { button.disabled = true; button.classList.add("is-busy"); }
  let failed = 0;
  for (const repair of repairs) {
    try {
      const result = await api().restore_privacy_fix(repair.browser);
      if (!result.ok) { failed += 1; toast(result.error || "还原失败，请重试。"); continue; }
      PRIVACY_REPAIRS = result.repairs || [];
      const browsers = PRIVACY_REPORT?.policies?.browsers;
      if (browsers && browsers[repair.browser]) {
        browsers[repair.browser] = { value: null, source: null, state: "unset", editable: true };
      }
    } catch (_) { failed += 1; toast("还原失败，请重试。"); }
  }
  if (!failed) {
    updatePrivacyReason("策略已还原；建议重新检查。");
    toast("已还原。");
  }
  renderEnvironmentReport();
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("safety-app").onchange = () => { document.getElementById("network-guard-target").value = document.getElementById("safety-app").value; renderEnvironmentReport(); loadNetworkGuard(); };
  document.getElementById("network-guard-target").onchange = () => loadNetworkGuard();
  for (const [element, key] of [["network-guard-mode", "mode"], ["network-guard-tunnel", "guid"], ["network-guard-browser-paths", "paths"]]) {
    document.getElementById(element).onchange = event => {
      const draft = NETWORK_DRAFTS[networkGuardTarget()];
      if (!draft) return;
      draft[key] = event.target.value;
      renderNetworkControls(); renderEnvironmentReport();
    };
  }
  document.getElementById("network-guard-cli").onchange = event => {
    const draft = NETWORK_DRAFTS[networkGuardTarget()];
    if (draft) draft.includeCli = event.target.checked;
  };
  document.getElementById("safety-check").onclick = checkEnvironment;
  document.getElementById("save-safety").onclick = () => saveEditor("safety");
  document.getElementById("cancel-safety").onclick = () => cancelSettings("safety");
  document.getElementById("safety-source").onclick = async () => {
    try { const result = await api().open_safety_source(document.getElementById("safety-app").value); if (!result.ok) toast("无法打开规则页面。"); }
    catch (_) { toast("无法打开规则页面。"); }
  };
});

window.addEventListener('languagechange', () => {
  if (READY && !environmentChecking) renderEnvironmentReport();
});
