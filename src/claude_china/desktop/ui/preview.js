// Browser-only preview. Native builds always use the real pywebview bridge.
if (new URLSearchParams(location.search).has("preview")) {
  const modes = new URLSearchParams(location.search);
  const apps = [
    { id: "claude", display: "Claude", found: true, running: true },
    { id: "codex", display: "Codex", found: false, running: false },
    { id: "grok-bot", display: "Grok Bot", found: true, running: false },
  ];
  let settings = { check_system_proxy: true, auto_proxy_env: false, env_vars: { HTTPS_PROXY: "http://127.0.0.1:7890" } };
  let safetySettings = { enabled: true, block_unknown: true,
    policy: { kind: "blocked_regions", updated_on: "2026-10-21", blocked_regions:
      [["CN", "中国大陆"], ["HK", "香港"], ["MO", "澳门"], ["RU", "俄罗斯"], ["IR", "伊朗"], ["KP", "朝鲜"]].map(([code, name]) => ({ code, name })) },
    environment: { timezone: "Asia/Shanghai", utc_offset: "+0800", language: "zh-CN", region: "CN" } };
  const safetyReport = id => {
    const status = modes.get("safety") || "supported";
    return { app_id: id, status, environment: safetySettings.environment, checked_at: new Date().toISOString(),
      policy: safetySettings.policy, route: "系统 HTTP 代理（预览示例）",
      network: status === "unknown" ? {} : { ip: "203.0.113.24", country: status === "unsupported" ? "China" : "Singapore", country_code: status === "unsupported" ? "CN" : "SG" },
      reason: status === "unknown" ? "无法确认出口地区（预览示例）。" : status === "unsupported" ? "出口位于统一禁止地区：中国大陆，禁止启动。" : "出口地区已识别，未命中统一禁止名单，符合当前地区限制规则。" };
  };
  const perApp = {
    claude: { path: "", env_vars: { ANTHROPIC_BASE_URL: "https://api.example.com" } },
    codex: { path: "", env_vars: {} }, "grok-bot": { path: "", env_vars: {} },
  };
  let state = { phase: "idle", current: "0.3.0", latest: "", can_install: true, message: "手动检查新版本", progress: 0 };
  let timer;
  let maximized = false;
  const clone = value => JSON.parse(JSON.stringify(value));
  let takeoverEnabled = false;
  const takeoverState = () => ({ supported: true, enabled: takeoverEnabled,
    message: takeoverEnabled ? '已接管原入口；每次启动和更新后重启都会重新检查并注入变量。（预览）' : '未接管原入口。（预览）' });
  window.pywebview = { api: {
    get_takeover_status: async () => takeoverState(),
    set_grok_takeover: async enabled => { takeoverEnabled = enabled; return { ok: true, state: takeoverState() }; },
    get_window_state: async () => ({ custom_titlebar: true, maximized }),
    window_action: async action => {
      if (action === "maximize") maximized = !maximized;
      else toast(action === "minimize" ? "界面预览：最小化窗口" : "界面预览：关闭窗口");
      return { ok: true, custom_titlebar: true, maximized };
    },
    begin_window_resize: async () => ({ ok: true }),
    move_window: async () => ({ ok: true }),
    list_apps: async () => clone(apps),
    get_settings: async () => clone(settings),
    get_safety_settings: async () => clone(safetySettings),
    save_safety_settings: async payload => {
      if (modes.get("save") === "error") return { ok: false };
      safetySettings = { ...safetySettings, ...clone(payload) }; return { ok: true };
    },
    check_safety: async id => clone(safetyReport(id)),
    open_safety_source: async () => ({ ok: true }),
    get_app_settings: async id => clone(perApp[id]),
    save_settings: async payload => {
      if (modes.get("save") === "error") return { ok: false };
      settings = clone(payload); return { ok: true };
    },
    save_app_settings: async (id, payload) => {
      if (modes.get("save") === "error") return { ok: false };
      perApp[id] = clone(payload);
      if (payload.path) apps.find(a => a.id === id).found = true;
      return { ok: true };
    },
    pick_app_path: async id => ({ ok: true, path: `C:/Applications/${apps.find(a => a.id === id).display}.exe` }),
    launch_app: async id => {
      if (settings.auto_proxy_env && modes.get("proxy") === "invalid") return { ok: false, error: "系统代理格式无效，请检查主机地址和端口（1–65535）。已取消启动。" };
      if (modes.get("launch") === "error") return { ok: false, error: "系统代理未开启，已取消启动" };
      const report = safetyReport(id);
      if (safetySettings.enabled && (report.status === "unsupported" || report.status === "unknown" && safetySettings.block_unknown)) {
        return { ok: false, error: "安全检查未通过：" + report.reason + " 已取消启动。", safety: report };
      }
      apps.find(a => a.id === id).running = true; return { ok: true };
    },
    stop_app: async id => { apps.find(a => a.id === id).running = false; return { ok: true }; },
    fit_window: async () => ({ ok: true }),
    get_update_status: async () => clone(state),
    check_for_updates: async () => {
      state = { ...state, phase: "checking", message: "正在检查 GitHub Releases…" };
      timer = setTimeout(() => {
        const mode = modes.get("update");
        state = { ...state, phase: mode === "error" ? "error" : mode === "latest" ? "latest" : "available",
          latest: "0.4.0", message: mode === "error" ? "GitHub 请求次数受限，请稍后重试。" : mode === "latest" ? "当前已是最新版本。" : "发现新版本 0.4.0" };
      }, 600);
      return clone(state);
    },
    download_update: async () => {
      state = { ...state, phase: "downloading", progress: 0, message: "正在下载安装包…" };
      const tick = () => {
        state = { ...state, progress: state.progress + 20 };
        if (state.progress >= 100) state = { ...state, phase: "ready", message: "更新已就绪，安装后将重新打开 Claude China。" };
        else timer = setTimeout(tick, 500);
      };
      timer = setTimeout(tick, 500);
      return clone(state);
    },
    cancel_update: async () => { clearTimeout(timer); state = { ...state, phase: "available", message: "已取消下载，可稍后重试。" }; return clone(state); },
    install_update: async () => { toast("界面预览：此处会退出启动器，安装并重新打开"); return clone(state); },
    open_release_page: async () => ({ ok: true }),
  } };
  document.addEventListener("DOMContentLoaded", init);
}
