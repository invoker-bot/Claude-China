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
  let state = { phase: "idle", current: "0.4.0", latest: "", can_install: true, message: "手动检查新版本", progress: 0 };
  let timer;
  let maximized = false;
  const clone = value => JSON.parse(JSON.stringify(value));
  let cliRevision = 1;
  let cliProfiles = modes.has('empty-terminals') ? [] : [
    {name:'日常开发', type:'claude', mode:'api', base_url:'https://api.anthropic.com', has_secret:true, default_args:['--model', 'sonnet'], revision:'preview-claude'},
    {name:'工作项目', type:'codex', mode:'api', base_url:'https://api.openai.com/v1', has_secret:true, default_args:[], revision:'preview-codex'},
    {name:'个人账号', type:'grok', mode:'login', credentials_path:'~/.claudec/accounts/personal', has_secret:false, default_args:[], revision:'preview-grok'},
  ];
  let terminalDirectory = 'D:\\Projects\\my-project';
  let terminalRecent = [terminalDirectory, 'D:\\Projects\\docs-site'];
  let terminalFavorites = [terminalDirectory];
  const terminalSessions = [
    {id:'019a1111-2222-7333-8444-555555555555',title:'完善项目登录与权限流程',directory:terminalDirectory,updated_at:'2026-10-21T08:30:00Z',available:true},
    {id:'019a1111-2222-7333-8444-666666666666',title:'整理文档站点与导航',directory:'D:\\Projects\\docs-site',updated_at:'2026-10-20T09:15:00Z',available:true},
    {id:'019a1111-2222-7333-8444-777777777777',title:'旧版页面探索',directory:'D:\\Archived\\old-project',updated_at:'2026-10-18T03:00:00Z',available:false},
  ];
  const cliPublic = p => ({...clone(p), supported:true, endpoint:p.base_url ? new URL(p.base_url).hostname : ''});
  const cliFailure = () => ({ok:false, error:'此配置已发生变化，请重新打开后再操作。'});
  const takeoverEnabled = {};
  const takeoverState = id => id !== 'grok-bot' ? ({ app_id: id, supported: false, enabled: false,
    can_disable: false, mode: 'msix-unavailable', message: 'MSIX 安装暂不支持原入口接管，尚不能保证更新后的检查和包激活上下文。（预览）' }) :
    ({ app_id: id, supported: true, enabled: Boolean(takeoverEnabled[id]), can_disable: Boolean(takeoverEnabled[id]),
      message: takeoverEnabled[id] ? '已接管此 EXE 原入口及同路径更新重启；每次重新检查并注入变量。（预览）' : '未接管原入口。仅覆盖固定 EXE 路径及同路径更新。（预览）' });
  window.pywebview = { api: {
    list_cli_profiles: async () => ({ok:true, data:{directory:terminalDirectory, recent_directories:clone(terminalRecent),favorite_directories:clone(terminalFavorites),
      projects:[...new Set([...terminalFavorites,...terminalRecent])].map(directory=>({directory,name:directory.split('\\').pop(),favorite:terminalFavorites.includes(directory),available:true})),
      tools:[{id:'claude',display:'Claude Code',installed:true},{id:'codex',display:'Codex CLI',installed:true},{id:'grok',display:'Grok CLI',installed:false}],
      profiles:cliProfiles.map(cliPublic)}}),
    list_cli_history: async name => {
      const profile=cliProfiles.find(p=>p.name===name);if(!profile)return cliFailure();
      if(modes.get('history')==='error')return {ok:false,error:'无法读取历史目录（预览）'};
      return {ok:true,data:{sessions:modes.has('empty-history')||profile.type==='grok'?[]:clone(terminalSessions),warnings:[],truncated:false}};
    },
    set_terminal_favorite: async (directory, favorite) => {
      if(!directory.trim())return {ok:false,error:'请选择项目目录。'};
      terminalFavorites=terminalFavorites.filter(p=>p!==directory);if(favorite)terminalFavorites.unshift(directory);return {ok:true};
    },
    resume_cli_session: async (name, id) => {
      const session=terminalSessions.find(s=>s.id===id);if(!session?.available)return {ok:false,error:'此会话的项目目录已不存在。'};
      return window.pywebview.api.open_terminal(name,session.directory);
    },
    get_cli_profile: async name => {const p=cliProfiles.find(p=>p.name===name);return p?{ok:true,data:cliPublic(p)}:cliFailure();},
    save_cli_profile: async (payload, original, revision) => {
      if (modes.get('save')==='error') return {ok:false,error:'保存失败（预览）'};
      const old=cliProfiles.find(p=>p.name===original);
      if (original && (!old || old.revision!==revision)) return cliFailure();
      if (!payload.name.trim() || cliProfiles.some(p=>p.name===payload.name.trim() && p.name!==original)) return {ok:false,error:'配置名称已存在或为空。'};
      const record={...clone(payload),name:payload.name.trim(),revision:'preview-'+cliRevision++,
        has_secret:!payload.clear_secret && Boolean(payload.secret || (old?.type===payload.type && old?.mode===payload.mode && old?.has_secret))};
      delete record.secret;delete record.clear_secret;
      if(record.mode==='login')record.has_secret=false;
      cliProfiles=cliProfiles.filter(p=>p.name!==original);cliProfiles.push(record);
      return {ok:true,data:cliPublic(record)};
    },
    copy_cli_profile: async (name, revision) => {
      const p=cliProfiles.find(p=>p.name===name);if(!p || p.revision!==revision)return cliFailure();
      let copied=name+' 副本', index=2;while(cliProfiles.some(p=>p.name===copied))copied=name+' 副本 '+index++;
      const record={...clone(p),name:copied,revision:'preview-'+cliRevision++};cliProfiles.push(record);return {ok:true,data:cliPublic(record)};
    },
    delete_cli_profile: async (name, revision) => {const p=cliProfiles.find(p=>p.name===name);if(!p || p.revision!==revision)return cliFailure();cliProfiles=cliProfiles.filter(p=>p.name!==name);return {ok:true};},
    pick_terminal_directory: async () => ({ok:true,path:'D:\\Projects\\demo project'}),
    open_project_folder: async () => {toast('界面预览：打开项目文件夹');return {ok:true};},
    open_terminal: async (name, directory) => {
      if(!directory.trim())return {ok:false,error:'请选择项目目录。'};
      if(name && modes.get('safety') && modes.get('safety')!=='supported')return {ok:false,error:'安全检查未通过：无法确认环境，已取消启动。'};
      terminalDirectory=directory;terminalRecent=[directory,...terminalRecent.filter(p=>p!==directory)].slice(0,20);return {ok:true};
    },
    get_takeover_status: async (id = 'grok-bot') => takeoverState(id),
    set_takeover: async (id, enabled) => {
      if (!takeoverState(id).supported) return { ok: false, error: takeoverState(id).message };
      takeoverEnabled[id] = enabled; return { ok: true, state: takeoverState(id) };
    },
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
          latest: mode === "latest" ? "0.4.0" : "0.4.1", message: mode === "error" ? "GitHub 请求次数受限，请稍后重试。" : mode === "latest" ? "当前已是最新版本。" : "发现新版本 0.4.1（预览）" };
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
