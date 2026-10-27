let TERMINALS = { profiles: [], tools: [], recent_directories: [], favorite_directories: [], projects: [] };
let TERMINAL_VIEW = 'history';
let TERMINAL_HISTORY = { sessions: [], warnings: [], truncated: false };
let TERMINAL_HISTORY_LOADING = false;
let TERMINAL_HISTORY_REQUEST = 0;
let TERMINAL_PROJECTS = [];
let TERMINAL_STARTING = false;
let TERMINAL_FILTER = 'all';
let TERMINAL_LOADING = false;
let TERMINAL_DIRTY = false;
let CLI_EDIT = null;
let CLI_SAVING = false;
let CLI_RETURN_FOCUS;
const CLI_NAMES = { claude: 'Claude Code', codex: 'Codex CLI', grok: 'Grok CLI' };
const CLI_BASE_URLS = { claude: 'https://api.anthropic.com', codex: 'https://api.openai.com/v1', grok: 'https://api.x.ai/v1' };

function terminalError(message = '') {
  const el = document.getElementById('terminal-error');
  el.textContent = message; el.hidden = !message;
}

async function refreshTerminals() {
  if (TERMINAL_LOADING) return;
  TERMINAL_LOADING = true;
  document.getElementById('refresh-terminals').disabled = true;
  terminalError();
  try {
    const result = await api().list_cli_profiles();
    if (!result.ok) throw new Error(result.error);
    TERMINALS = result.data;
    const select = document.getElementById('terminal-launch-profile');
    const selected = select.value || TERMINALS.last_profile;
    const profiles = TERMINALS.profiles.filter(p => p.supported);
    select.innerHTML = profiles.length ? profiles.map(p => `<option data-i18n-skip value="${esc(p.name)}">${esc(p.name)} · ${esc(CLI_NAMES[p.type])}</option>`).join('') : '<option value="">请先添加 CLI 配置</option>';
    if (profiles.some(p => p.name === selected)) select.value = selected;
    select.disabled = !profiles.length;
    document.getElementById('terminal-new-session').disabled = !profiles.length;
    if (!TERMINAL_DIRTY) document.getElementById('terminal-directory').value = TERMINALS.directory;
    document.getElementById('terminal-recent').innerHTML = TERMINALS.recent_directories.map(p => `<option value="${esc(p)}"></option>`).join('');
    renderTerminalWorkspace();
    await refreshTerminalHistory();
  } catch (error) { terminalError(error.message || '无法读取 CLI 配置。'); }
  finally { TERMINAL_LOADING = false; document.getElementById('refresh-terminals').disabled = false; }
}

function selectedTerminalProfile() {
  return document.getElementById('terminal-launch-profile').value;
}

function terminalFavorite(directory) {
  return (TERMINALS.favorite_directories || []).includes(directory);
}

function renderTerminalWorkspace() {
  renderTerminalProfiles();
  renderTerminalHistory();
  renderTerminalProjects();
  const favorite = terminalFavorite(document.getElementById('terminal-directory').value);
  const star = document.getElementById('terminal-favorite');
  star.classList.toggle('is-favorite', favorite);
  star.setAttribute('aria-pressed', String(favorite));
  star.title = favorite ? '取消收藏当前项目' : '收藏当前项目';
  star.setAttribute('aria-label', star.title);
}

function setTerminalView(view) {
  TERMINAL_VIEW = view;
  document.getElementById('terminal-history-pane').hidden = view !== 'history';
  document.getElementById('terminal-projects-pane').hidden = view !== 'projects';
  document.getElementById('terminal-profiles').hidden = view !== 'profiles';
  document.getElementById('terminal-filters').hidden = view !== 'profiles';
  document.querySelectorAll('[data-terminal-view]').forEach(button => {
    button.classList.toggle('is-active', button.dataset.terminalView === view);
    button.setAttribute('aria-pressed', String(button.dataset.terminalView === view));
  });
  document.getElementById('terminal-search').placeholder = {history: '搜索会话或项目', projects: '搜索项目文件夹', profiles: '搜索 CLI 配置'}[view];
  renderTerminalWorkspace();
}

async function refreshTerminalHistory() {
  const request = ++TERMINAL_HISTORY_REQUEST;
  const profile = selectedTerminalProfile();
  TERMINAL_HISTORY = {sessions: [], warnings: [], truncated: false};
  TERMINAL_HISTORY_LOADING = Boolean(profile);
  renderTerminalHistory();
  try {
    if (!profile) return;
    const result = await api().list_cli_history(profile);
    if (request !== TERMINAL_HISTORY_REQUEST) return;
    if (!result.ok) throw new Error(result.error);
    TERMINAL_HISTORY = result.data;
  } catch (error) {
    if (request === TERMINAL_HISTORY_REQUEST) terminalError(error.message || '无法读取历史会话。');
  } finally {
    if (request === TERMINAL_HISTORY_REQUEST) {
      TERMINAL_HISTORY_LOADING = false;
      renderTerminalHistory(); renderTerminalProjects();
    }
  }
}

function terminalEmpty(title, description, symbol = 'history') {
  return `<div class="terminal-empty">${icon(symbol)}<h2>${esc(title)}</h2><p>${esc(description)}</p></div>`;
}

function renderTerminalHistory() {
  const list = document.getElementById('terminal-history');
  const note = document.getElementById('terminal-history-note');
  const profile = TERMINALS.profiles.find(p => p.name === selectedTerminalProfile());
  note.textContent = profile ? `读取“${profile.name}”所用目录的本地会话，包含从其他入口启动的记录。` : '选择一条 CLI 配置来查看对应的历史。';
  if (TERMINAL_HISTORY.truncated) note.insertAdjacentHTML('beforeend', '<span> 仅显示最近 200 条。</span>');
  for (const warning of TERMINAL_HISTORY.warnings) note.insertAdjacentHTML('beforeend', `<span> ${esc(warning)}</span>`);
  if (TERMINAL_HISTORY_LOADING) { list.innerHTML = '<p class="terminal-section-note">正在读取本地历史…</p>'; return; }
  const query = document.getElementById('terminal-search').value.trim().toLowerCase();
  const entries = TERMINAL_HISTORY.sessions.map((session, index) => ({session, index})).filter(({session: s}) => `${s.title} ${s.directory} ${s.id}`.toLowerCase().includes(query));
  if (!entries.length) {
    list.innerHTML = terminalEmpty(query ? '没有匹配的会话' : '还没有历史会话', query ? '试试项目名称、会话标题或会话 ID。' : '在上方选择项目和配置，新建会话。CLI 保存记录后会显示在这里。'); return;
  }
  list.innerHTML = entries.map(({session: s, index}) => {
    const date = new Date(s.updated_at);
    const time = Number.isNaN(date.getTime()) ? '' : date.toLocaleString(I18n.locale(), {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'});
    const favorite = terminalFavorite(s.directory);
    return `<article class="terminal-session" data-session-index="${index}"><span class="terminal-session-icon" aria-hidden="true">${profile?.type === 'grok' ? icon('terminal') : appSymbol(profile?.type)}</span><div class="terminal-session-info"><h2 data-i18n-skip title="${esc(s.id)}">${esc(s.title)}</h2><p class="terminal-session-path" data-i18n-skip title="${esc(s.directory)}">${esc(s.directory)}</p><p class="terminal-session-meta">${esc(CLI_NAMES[profile?.type] || '')} · <span data-i18n-skip>${esc(time)}</span>${s.available ? '' : ' · 项目目录已不存在'}</p></div><div class="terminal-session-actions"><button class="icon-button ${favorite ? 'is-favorite' : ''}" type="button" data-session-action="favorite" aria-label="${favorite ? '取消收藏' : '收藏'}项目 ${esc(s.directory)}" aria-pressed="${favorite}" ${!s.available && !favorite ? 'disabled' : ''}>${icon('star')}</button><button class="btn" type="button" data-session-action="directory" ${s.available ? '' : 'disabled'} title="将此项目设为新会话目录">选用目录</button><button class="btn btn--key" type="button" data-session-action="resume" ${s.available ? '' : 'disabled'}>${icon('history')}继续会话</button></div></article>`;
  }).join('');
}

function renderTerminalProjects() {
  const projects = new Map((TERMINALS.projects || []).map(p => [p.directory, {...p}]));
  for (const session of TERMINAL_HISTORY.sessions) {
    if (!projects.has(session.directory)) projects.set(session.directory, {directory:session.directory, name:session.directory.split(/[\\/]/).filter(Boolean).pop() || session.directory, available:session.available, favorite:terminalFavorite(session.directory)});
  }
  TERMINAL_PROJECTS = [...projects.values()].sort((a, b) => Number(b.favorite) - Number(a.favorite));
  const query = document.getElementById('terminal-search').value.trim().toLowerCase();
  const entries = TERMINAL_PROJECTS.map((project, index) => ({project, index})).filter(({project:p}) => p.directory.toLowerCase().includes(query));
  const list = document.getElementById('terminal-projects');
  if (!entries.length) { list.innerHTML = terminalEmpty(query ? '没有匹配的项目' : '还没有常用项目', query ? '试试文件夹名称或完整路径。' : '选择项目目录后点击星标收藏；最近启动的项目也会出现在这里。', 'folder'); return; }
  list.innerHTML = entries.map(({project:p, index}) => `<article class="terminal-project-card" data-project-index="${index}"><div class="terminal-project-card-head">${icon('folder')}<h2 data-i18n-skip>${esc(p.name)}</h2><button class="icon-button ${p.favorite ? 'is-favorite' : ''}" type="button" data-project-action="favorite" aria-label="${p.favorite ? '取消收藏' : '收藏'} ${esc(p.name)}" aria-pressed="${p.favorite}" ${!p.available && !p.favorite ? 'disabled' : ''}>${icon('star')}</button></div><p class="terminal-session-path" data-i18n-skip>${esc(p.directory)}</p><p class="terminal-session-meta">${p.favorite ? '已收藏' : '最近使用'}${p.available ? '' : ' · 项目目录已不存在'}</p><div class="terminal-project-card-actions"><button class="btn btn--key" type="button" data-project-action="new" ${p.available && selectedTerminalProfile() ? '' : 'disabled'}>${icon('plus')}新建会话</button><button class="btn" type="button" data-project-action="directory" ${p.available ? '' : 'disabled'}>选用目录</button><button class="icon-button" type="button" data-project-action="folder" aria-label="打开文件夹 ${esc(p.name)}" ${p.available ? '' : 'disabled'}>${icon('external')}</button></div></article>`).join('');
}

function useTerminalDirectory(directory) {
  document.getElementById('terminal-directory').value = directory;
  TERMINAL_DIRTY = true;
  renderTerminalWorkspace();
  toast('已选用项目目录，可在上方新建会话');
}

async function favoriteTerminalDirectory(directory, button) {
  button.disabled = true; terminalError();
  try {
    const favorite = !terminalFavorite(directory);
    const result = await api().set_terminal_favorite(directory, favorite);
    if (!result.ok) throw new Error(result.error);
    toast(favorite ? '已收藏项目' : '已取消收藏');
    await refreshTerminals();
  } catch (error) { terminalError(error.message || '无法保存项目收藏。'); }
  finally { if (button.isConnected) button.disabled = false; }
}

function renderTerminalProfiles() {
  updateWorkspaceCount();
  const query = document.getElementById('terminal-search').value.trim().toLowerCase();
  const entries = TERMINALS.profiles.map((profile, index) => ({profile, index})).filter(({profile: p}) =>
    (TERMINAL_FILTER === 'all' || p.type === TERMINAL_FILTER) &&
    `${p.name} ${CLI_NAMES[p.type] || p.type} ${p.endpoint || ''}`.toLowerCase().includes(query));
  const grid = document.getElementById('terminal-profiles');
  if (!entries.length) {
    grid.innerHTML = `<div class="terminal-empty">${icon('terminal')}<h2>${TERMINALS.profiles.length ? '没有匹配的配置' : '添加你的第一条 CLI 配置'}</h2><p>${TERMINALS.profiles.length ? '试试其他关键词，或切换工具类型。' : '已有 claudec 配置会自动显示在这里，也可以新建 API 或登录配置。'}</p></div>`;
    return;
  }
  grid.innerHTML = entries.map(({profile: p, index}) => {
    const tool = TERMINALS.tools.find(tool => tool.id === p.type);
    const symbol = p.type === 'grok' ? icon('terminal') : appSymbol(p.type);
    return `<article class="terminal-card" data-profile-index="${index}"><div class="terminal-card-top"><span class="terminal-tool-icon" aria-hidden="true">${symbol}</span><span class="terminal-tool-name">${esc(CLI_NAMES[p.type] || p.type)}</span><span class="terminal-detected ${tool?.installed ? 'is-installed' : ''}">${tool?.installed ? '已检测到' : '未检测到 CLI'}</span></div>` +
      `<h2 data-i18n-skip>${esc(p.name)}</h2><p class="terminal-card-mode">${p.mode === 'login' ? '登录配置目录' : `API · ${p.has_secret ? '已保存密钥' : '未配置密钥'}`}</p>` +
      `<p class="terminal-endpoint" ${p.mode !== 'login' && p.endpoint ? 'data-i18n-skip' : ''}>${esc(p.mode === 'login' ? '使用独立登录目录' : p.endpoint || '默认服务地址')}</p>` +
      `<div class="terminal-card-actions"><button class="btn btn--key" type="button" data-cli-action="launch" ${p.supported ? '' : 'disabled'}>${icon('terminal')}启动终端</button>` +
      `<button class="icon-button" data-cli-action="edit" type="button" aria-label="编辑 ${esc(p.name)}" title="编辑配置">${icon('edit')}</button><button class="icon-button" data-cli-action="copy" type="button" aria-label="复制 ${esc(p.name)}" title="复制配置">${icon('copy')}</button><button class="icon-button terminal-delete" data-cli-action="delete" type="button" aria-label="删除 ${esc(p.name)}" title="删除配置">${icon('trash')}</button></div></article>`;
  }).join('');
}

async function terminalAction(name, button, directory = document.getElementById('terminal-directory').value, sessionId = null) {
  if (button.disabled || TERMINAL_STARTING) return;
  TERMINAL_STARTING = true;
  const label = button.innerHTML;
  button.disabled = true;
  button.textContent = name === null ? '正在打开…' : '正在检查…';
  terminalError();
  try {
    const result = sessionId ? await api().resume_cli_session(name, sessionId) : await api().open_terminal(name, directory);
    if (!result.ok) throw new Error(result.error);
    TERMINAL_DIRTY = false;
    toast(name === null ? '终端已打开' : sessionId ? '已打开终端，将重新检查环境并恢复会话' : '已打开终端，将重新检查配置并启动 CLI');
    await refreshTerminals();
  } catch (error) { terminalError(error.message || '无法打开终端。'); }
  finally { TERMINAL_STARTING = false; if (button.isConnected) { button.disabled = false; button.innerHTML = label; } }
}

function renderCliMode() {
  const login = document.getElementById('cli-mode').value === 'login';
  const manualBrowser = login && document.getElementById('cli-type').value === 'claude';
  document.getElementById('cli-api-fields').hidden = login;
  document.getElementById('cli-login-fields').hidden = !login;
  document.getElementById('cli-manual-browser-row').hidden = !manualBrowser;
  document.getElementById('cli-credentials-path').required = login;
  // Hidden URL inputs must not prevent submitting a login configuration.
  document.getElementById('cli-base-url').disabled = login;
}

function cliFormError(message = '') {
  const el = document.getElementById('cli-form-error'); el.textContent = message; el.hidden = !message;
}

async function openCliEditor(profile = null, remove = false) {
  cliFormError();
  const form = document.getElementById('cli-profile-form');
  form.reset();
  CLI_RETURN_FOCUS = document.activeElement;
  let detail = profile;
  if (profile && !remove) {
    try {
      const result = await api().get_cli_profile(profile.name);
      if (!result.ok) throw new Error(result.error);
      detail = result.data;
    } catch (error) { terminalError(error.message || '无法读取配置。'); return; }
  }
  CLI_EDIT = { original: profile?.name || null, revision: detail?.revision || null, remove };
  document.getElementById('cli-dialog-title').textContent = remove ? '删除 CLI 配置' : profile ? '编辑 CLI 配置' : '新增 CLI 配置';
  document.getElementById('cli-submit').textContent = remove ? '删除配置' : '保存配置';
  document.getElementById('cli-submit').classList.toggle('btn--danger', remove);
  document.getElementById('cli-form-fields').hidden = remove;
  document.getElementById('cli-delete-content').hidden = !remove;
  document.querySelectorAll('#cli-form-fields input, #cli-form-fields select, #cli-form-fields textarea, #cli-form-fields button').forEach(el => { el.disabled = remove; });
  if (remove) document.getElementById('cli-delete-description').textContent = `确定删除“${profile.name}”？`;
  else {
    document.getElementById('cli-name').value = detail?.name || '';
    document.getElementById('cli-type').value = detail?.type || (TERMINAL_FILTER === 'all' ? 'claude' : TERMINAL_FILTER);
    document.getElementById('cli-mode').value = detail?.mode || 'api';
    document.getElementById('cli-base-url').value = detail?.base_url || '';
    document.getElementById('cli-base-url').placeholder = CLI_BASE_URLS[document.getElementById('cli-type').value];
    document.getElementById('cli-credentials-path').value = detail?.credentials_path || '';
    document.getElementById('cli-manual-browser').checked = detail?.manual_browser_login === true;
    document.getElementById('cli-proxy').value = detail?.proxy || '';
    document.getElementById('cli-default-args').value = detail?.default_args?.length ? JSON.stringify(detail.default_args, null, 2) : '';
    document.getElementById('cli-secret').placeholder = detail?.has_secret ? '留空保留已保存的密钥' : '可选：输入 API 密钥或 Token';
    document.getElementById('cli-clear-secret-row').hidden = !detail?.has_secret;
    document.getElementById('cli-secret-hint').textContent = detail?.has_secret ? '已保存密钥。留空保持不变；切换工具或认证方式会清除旧凭据。' : '密钥仅保存在本机配置中，不写入终端命令历史。';
    renderCliMode();
  }
  document.getElementById('cli-profile-dialog').showModal();
  document.getElementById(remove ? 'cli-cancel' : 'cli-name').focus();
}

function closeCliEditor() {
  if (CLI_SAVING) return;
  document.getElementById('cli-profile-dialog').close();
  document.getElementById('cli-secret').value = '';
  if (CLI_RETURN_FOCUS?.isConnected) CLI_RETURN_FOCUS.focus();
}

async function submitCliProfile(event) {
  event.preventDefault();
  if (CLI_SAVING) return;
  cliFormError();
  let payload;
  if (!CLI_EDIT.remove) {
    try {
      const raw = document.getElementById('cli-default-args').value.trim();
      const args = raw ? JSON.parse(raw) : [];
      if (!Array.isArray(args) || args.some(arg => typeof arg !== 'string')) throw new Error();
      payload = {name: document.getElementById('cli-name').value, type: document.getElementById('cli-type').value,
        mode: document.getElementById('cli-mode').value, base_url: document.getElementById('cli-base-url').value,
        secret: document.getElementById('cli-secret').value, clear_secret: document.getElementById('cli-clear-secret').checked,
        credentials_path: document.getElementById('cli-credentials-path').value,
        manual_browser_login: !document.getElementById('cli-manual-browser-row').hidden && document.getElementById('cli-manual-browser').checked,
        proxy: document.getElementById('cli-proxy').value, default_args: args};
    } catch (_) { cliFormError('默认参数需填写 JSON 字符串数组，例如 ["--model", "sonnet"]。'); return; }
  }
  CLI_SAVING = true;
  const buttons = [...document.querySelectorAll('#cli-profile-dialog button')];
  buttons.forEach(button => { button.disabled = true; });
  try {
    const result = CLI_EDIT.remove ? await api().delete_cli_profile(CLI_EDIT.original, CLI_EDIT.revision) :
      await api().save_cli_profile(payload, CLI_EDIT.original, CLI_EDIT.revision);
    if (!result.ok) throw new Error(result.error);
    CLI_SAVING = false;
    closeCliEditor();
    toast(CLI_EDIT.remove ? '配置已删除' : 'CLI 配置已保存');
    await refreshTerminals();
  } catch (error) { cliFormError(error.message || '保存失败，请重试。'); }
  finally { CLI_SAVING = false; buttons.forEach(button => { button.disabled = false; }); }
}

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('refresh-terminals').onclick = refreshTerminals;
  document.getElementById('new-cli-profile').onclick = () => { setTerminalView('profiles'); openCliEditor(); };
  document.getElementById('terminal-search').oninput = renderTerminalWorkspace;
  document.getElementById('terminal-directory').oninput = () => { TERMINAL_DIRTY = true; renderTerminalWorkspace(); };
  document.getElementById('terminal-views').onclick = event => {
    const button = event.target.closest('[data-terminal-view]'); if (button) setTerminalView(button.dataset.terminalView);
  };
  document.getElementById('terminal-launch-profile').onchange = () => { terminalError(); refreshTerminalHistory(); renderTerminalProjects(); };
  document.getElementById('terminal-new-session').onclick = event => { const name = selectedTerminalProfile(); if (name) terminalAction(name, event.currentTarget); };
  document.getElementById('terminal-favorite').onclick = event => favoriteTerminalDirectory(document.getElementById('terminal-directory').value, event.currentTarget);
  document.getElementById('terminal-history').onclick = event => {
    const button = event.target.closest('[data-session-action]'); if (!button || button.disabled) return;
    const session = TERMINAL_HISTORY.sessions[Number(button.closest('[data-session-index]').dataset.sessionIndex)];
    if (button.dataset.sessionAction === 'resume') return terminalAction(selectedTerminalProfile(), button, session.directory, session.id);
    if (button.dataset.sessionAction === 'favorite') return favoriteTerminalDirectory(session.directory, button);
    useTerminalDirectory(session.directory);
  };
  document.getElementById('terminal-projects').onclick = event => {
    const button = event.target.closest('[data-project-action]'); if (!button || button.disabled) return;
    const project = TERMINAL_PROJECTS[Number(button.closest('[data-project-index]').dataset.projectIndex)];
    if (button.dataset.projectAction === 'new') return terminalAction(selectedTerminalProfile(), button, project.directory);
    if (button.dataset.projectAction === 'favorite') return favoriteTerminalDirectory(project.directory, button);
    if (button.dataset.projectAction === 'folder') return openTerminalFolder(project.directory);
    useTerminalDirectory(project.directory);
  };
  document.getElementById('terminal-filters').onclick = event => {
    const filter = event.target.closest('[data-tool]'); if (!filter) return;
    TERMINAL_FILTER = filter.dataset.tool;
    document.querySelectorAll('[data-tool]').forEach(button => {
      const active = button === filter; button.classList.toggle('is-active', active); button.setAttribute('aria-pressed', String(active));
    });
    renderTerminalProfiles();
  };
  document.getElementById('terminal-profiles').onclick = async event => {
    const button = event.target.closest('[data-cli-action]'); if (!button || button.disabled) return;
    const profile = TERMINALS.profiles[Number(button.closest('[data-profile-index]').dataset.profileIndex)];
    const action = button.dataset.cliAction;
    if (action === 'launch') return terminalAction(profile.name, button);
    if (action === 'edit' || action === 'delete') return openCliEditor(profile, action === 'delete');
    button.disabled = true;
    try {
      const result = await api().copy_cli_profile(profile.name, profile.revision);
      if (!result.ok) throw new Error(result.error);
      toast('配置已复制'); await refreshTerminals();
    } catch (error) { terminalError(error.message || '无法复制配置。'); }
    finally { if (button.isConnected) button.disabled = false; }
  };
  document.getElementById('terminal-plain').onclick = event => terminalAction(null, event.currentTarget);
  for (const [id, target] of [['terminal-pick', 'terminal-directory'], ['cli-pick-credentials', 'cli-credentials-path']]) {
    document.getElementById(id).onclick = async () => {
      try {
        const result = await api().pick_terminal_directory();
        if (result.ok) { document.getElementById(target).value = result.path; if (target === 'terminal-directory') { TERMINAL_DIRTY = true; renderTerminalWorkspace(); } }
        else if (!result.cancelled) throw new Error(result.error);
      } catch (error) { target === 'terminal-directory' ? terminalError(error.message) : cliFormError(error.message); }
    };
  }
  document.getElementById('terminal-folder').onclick = () => openTerminalFolder(document.getElementById('terminal-directory').value);
  document.getElementById('cli-profile-form').onsubmit = submitCliProfile;
  for (const id of ['cli-dialog-close', 'cli-cancel']) document.getElementById(id).onclick = closeCliEditor;
  document.getElementById('cli-profile-dialog').addEventListener('cancel', event => { event.preventDefault(); closeCliEditor(); });
  document.getElementById('cli-mode').onchange = renderCliMode;
  document.getElementById('cli-type').onchange = () => { document.getElementById('cli-base-url').placeholder = CLI_BASE_URLS[document.getElementById('cli-type').value]; renderCliMode(); };
});

async function openTerminalFolder(directory) {
  terminalError();
  try { const result = await api().open_project_folder(directory); if (!result.ok) throw new Error(result.error); }
  catch (error) { terminalError(error.message || '无法打开项目文件夹。'); }
}

window.addEventListener('languagechange', () => {
  if (READY) renderTerminalHistory();
});
