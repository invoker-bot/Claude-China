let TERMINALS = { profiles: [], tools: [], recent_directories: [] };
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
    if (!TERMINAL_DIRTY) document.getElementById('terminal-directory').value = TERMINALS.directory;
    document.getElementById('terminal-recent').innerHTML = TERMINALS.recent_directories.map(p => `<option value="${esc(p)}"></option>`).join('');
    renderTerminalProfiles();
  } catch (error) { terminalError(error.message || '无法读取 CLI 配置。'); }
  finally { TERMINAL_LOADING = false; document.getElementById('refresh-terminals').disabled = false; }
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
      `<h2>${esc(p.name)}</h2><p class="terminal-card-mode">${p.mode === 'login' ? '登录配置目录' : `API · ${p.has_secret ? '已保存密钥' : '未配置密钥'}`}</p>` +
      `<p class="terminal-endpoint">${esc(p.mode === 'login' ? '使用独立登录目录' : p.endpoint || '默认服务地址')}</p>` +
      `<div class="terminal-card-actions"><button class="btn btn--key" type="button" data-cli-action="launch" ${p.supported ? '' : 'disabled'}>${icon('terminal')}启动终端</button>` +
      `<button class="icon-button" data-cli-action="edit" type="button" aria-label="编辑 ${esc(p.name)}" title="编辑配置">${icon('edit')}</button><button class="icon-button" data-cli-action="copy" type="button" aria-label="复制 ${esc(p.name)}" title="复制配置">${icon('copy')}</button><button class="icon-button terminal-delete" data-cli-action="delete" type="button" aria-label="删除 ${esc(p.name)}" title="删除配置">${icon('trash')}</button></div></article>`;
  }).join('');
}

async function terminalAction(name, button) {
  if (button.disabled) return;
  const label = button.innerHTML;
  button.disabled = true;
  button.textContent = name === null ? '正在打开…' : '正在检查…';
  terminalError();
  try {
    const result = await api().open_terminal(name, document.getElementById('terminal-directory').value);
    if (!result.ok) throw new Error(result.error);
    TERMINAL_DIRTY = false;
    toast(name === null ? '终端已打开' : '已打开终端，将重新检查配置并启动 CLI');
    await refreshTerminals();
  } catch (error) { terminalError(error.message || '无法打开终端。'); }
  finally { if (button.isConnected) { button.disabled = false; button.innerHTML = label; } }
}

function renderCliMode() {
  const login = document.getElementById('cli-mode').value === 'login';
  document.getElementById('cli-api-fields').hidden = login;
  document.getElementById('cli-login-fields').hidden = !login;
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
  document.getElementById('new-cli-profile').onclick = () => openCliEditor();
  document.getElementById('terminal-search').oninput = renderTerminalProfiles;
  document.getElementById('terminal-directory').oninput = () => { TERMINAL_DIRTY = true; };
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
        if (result.ok) { document.getElementById(target).value = result.path; if (target === 'terminal-directory') TERMINAL_DIRTY = true; }
        else if (!result.cancelled) throw new Error(result.error);
      } catch (error) { target === 'terminal-directory' ? terminalError(error.message) : cliFormError(error.message); }
    };
  }
  document.getElementById('terminal-folder').onclick = async () => {
    terminalError();
    try { const result = await api().open_project_folder(document.getElementById('terminal-directory').value); if (!result.ok) throw new Error(result.error); }
    catch (error) { terminalError(error.message || '无法打开项目文件夹。'); }
  };
  document.getElementById('cli-profile-form').onsubmit = submitCliProfile;
  for (const id of ['cli-dialog-close', 'cli-cancel']) document.getElementById(id).onclick = closeCliEditor;
  document.getElementById('cli-profile-dialog').addEventListener('cancel', event => { event.preventDefault(); closeCliEditor(); });
  document.getElementById('cli-mode').onchange = renderCliMode;
  document.getElementById('cli-type').onchange = () => { document.getElementById('cli-base-url').placeholder = CLI_BASE_URLS[document.getElementById('cli-type').value]; };
});
