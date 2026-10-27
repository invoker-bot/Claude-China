// Loaded before the Playwright Node driver by inherited NODE_OPTIONS.
// Browser authorization completes synchronously BEFORE process creation.
'use strict';
const cp = require('node:child_process');
const path = require('node:path');
const sync = cp.spawnSync;
const marker = Symbol.for('claudec.playwright.guard');
if (!cp[marker] && process.env.CLAUDEC_BROWSER_GUARD_HELPER) {
  cp[marker] = true;
  const names = new Set(['chrome.exe', 'msedge.exe', 'chromium.exe', 'firefox.exe',
    'headless_shell.exe', 'chrome-headless-shell.exe', 'playwright.exe', 'minibrowser.exe']);
  const cliNames = new Set(['claude.exe', 'codex.exe', 'grok.exe']);
  function cli(file) {
    return process.env.CLAUDEC_CLI_GUARD === '1' &&
      cliNames.has(path.win32.basename(file).toLowerCase());
  }
  function authorize(file, args) {
    if (typeof file !== 'string') return;
    const browser = cli(file) || names.has(path.win32.basename(file).toLowerCase()) ||
      (Array.isArray(args) && args.some(value => /^-{1,2}(remote-debugging-(pipe|port)|juggler-pipe|inspector-pipe)(=|$)/.test(value)));
    if (!browser) return;
    let command;
    try { command = JSON.parse(process.env.CLAUDEC_BROWSER_GUARD_HELPER); }
    catch (_) { throw new Error('Invalid Playwright network guard helper. Browser launch blocked.'); }
    if (!Array.isArray(command) || !command.length || command.some(value => typeof value !== 'string'))
      throw new Error('Invalid Playwright network guard helper. Browser launch blocked.');
    const result = sync(command[0], [...command.slice(1), file],
      {encoding: 'utf8', env: {...process.env, PYTHONIOENCODING: 'utf-8'},
        windowsHide: true, timeout: 30000, maxBuffer: 16384, shell: false});
    if (result.error || result.status !== 0)
      throw new Error((result.stderr || '').trim() || 'Playwright network protection could not be verified. Browser launch blocked.');
    try { return JSON.parse(result.stdout || '{}'); } catch (_) { return {}; }
  }
  for (const method of ['spawn', 'spawnSync', 'execFile', 'execFileSync']) {
    const original = cp[method];
    cp[method] = function(file, args, ...rest) {
      const guard = authorize(file, args);
      if ((guard?.mode === 'tun' || guard?.mode === 'router') && Array.isArray(args)) {
        args = [...args];
        if (/chrome|chromium|msedge/i.test(path.win32.basename(file)) || args.some(value => /^--remote-debugging-/.test(value))) {
          // Headless shell can still use the Windows system proxy with only
          // --no-proxy-server. Force direct routing through the protected path.
          const switches = ['--no-proxy-server', '--proxy-server=direct://'];
          const separator = args.indexOf('--');
          if (separator < 0) args.push(...switches);
          else args.splice(separator, 0, ...switches);
        }
        const supplied = rest[0] && typeof rest[0] === 'object' ? rest.shift() : {};
        const env = {...(supplied.env || process.env)};
        for (const key of Object.keys(env))
          if (['http_proxy','https_proxy','all_proxy','no_proxy'].includes(key.toLowerCase())) delete env[key];
        if (cli(file)) { env.NO_PROXY = '*'; env.no_proxy = '*'; }
        rest.unshift({...supplied, env});
      }
      return original.call(this, file, args, ...rest);
    };
  }
  require('node:module').syncBuiltinESMExports();
}
