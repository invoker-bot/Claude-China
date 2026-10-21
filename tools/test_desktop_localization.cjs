// Real-browser regression checks against the isolated preview bridge.
// Usage: node tools/test_desktop_localization.cjs [http://127.0.0.1:8769/?preview]
const assert = require('node:assert/strict');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

async function main() {
  const url = new URL(process.argv[2] || 'http://127.0.0.1:8769/?preview');
  assert.ok(['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname));
  assert.ok(url.searchParams.has('preview'), 'Only use the isolated preview bridge');
  url.searchParams.delete('lang');
  const browser = await chromium.launch({headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? {channel: process.env.PLAYWRIGHT_CHANNEL} : {})});
  const errors = [];
  const context = await browser.newContext({locale: 'en-US', viewport: {width: 1000, height: 720}, reducedMotion: 'reduce'});
  const page = await context.newPage();
  page.on('pageerror', error => errors.push(error.message));
  const language = async (selected, resolved = selected) => {
    await page.locator('#app-language').selectOption(selected);
    await page.waitForFunction(expected => document.documentElement.lang === expected && !document.getElementById('app-language').disabled, resolved);
  };
  const text = async (selector, expected) => assert.equal(await page.locator(selector).textContent(), expected);
  const terminalReady = () => page.waitForFunction(() => !TERMINAL_LOADING && !TERMINAL_HISTORY_LOADING);
  const fits = () => page.evaluate(() => {
    const elements = ['#app-header', '#home-button', '#terminals-button', '#open-settings', '#window-close'];
    return elements.every(selector => {
      const rect = document.querySelector(selector).getBoundingClientRect();
      return rect.x >= 0 && rect.right <= innerWidth + 1;
    }) && document.documentElement.scrollWidth <= innerWidth;
  });
  try {
    await page.goto(url.href);
    await page.waitForFunction(() => READY);
    assert.equal(await page.locator('html').getAttribute('lang'), 'en');
    await text('#home-button', 'My apps');
    await page.locator('#open-settings').click();
    assert.equal(await page.locator('#app-language').inputValue(), 'system');

    // Language saves independently without saving or reconstructing form drafts.
    await page.locator('#auto-proxy-env').check();
    await page.locator('#common-env .v').fill('http://proxy.example.test:7890/设置/{token}');
    await page.locator('#add-common').click();
    await page.locator('#common-env .k').last().fill('USER_NOTE');
    await page.locator('#common-env .v').last().fill('设置 {0} <img src=x>');
    const draft = await page.evaluate(() => draftSnapshot('common'));
    for (const [selected, label] of [['zh-TW', '我的應用'], ['zh-CN', '我的应用'], ['en', 'My apps']]) {
      await language(selected);
      await text('#home-button', label);
      assert.equal(await page.evaluate(() => draftSnapshot('common')), draft);
      assert.equal(await page.evaluate(() => isDirty('common')), true);
      assert.equal(await page.evaluate(async () => (await api().get_settings()).auto_proxy_env), false);
      assert.equal(await page.locator('#common-env img').count(), 0);
    }
    await language('zh-TW');
    await page.reload(); await page.waitForFunction(() => READY);
    await text('#home-button', '我的應用');
    await page.locator('#open-settings').click();
    assert.equal(await page.locator('#app-language').inputValue(), 'zh-TW');
    await language('system', 'en');
    await text('#home-button', 'My apps');
    if (process.env.LOCALIZATION_SCREENSHOT) {
      await language('en');
      await page.setViewportSize({width: 1120, height: 780});
      await page.evaluate(() => document.fonts.ready);
      await page.waitForFunction(() => getComputedStyle(document.getElementById('toast')).opacity === '0');
      await page.locator('h1:visible').click();
      await page.mouse.move(5, 775);
      await page.screenshot({path: process.env.LOCALIZATION_SCREENSHOT, animations: 'disabled'});
      await page.setViewportSize({width: 1000, height: 720});
    }

    // User data equal to catalog keys must survive translations unchanged.
    await page.locator('#terminals-button').click(); await terminalReady();
    await page.locator('#new-cli-profile').click();
    await page.locator('#cli-name').fill('设置');
    await page.locator('#cli-secret').fill('test-only-{0}-启动');
    await page.locator('#cli-default-args').fill('["--model", "settings"]');
    // Exercise a language change during an open dialog through the same handler.
    await page.evaluate(() => { const select = document.getElementById('app-language'); select.value = 'zh-TW'; select.dispatchEvent(new Event('change')); });
    await page.waitForFunction(() => document.documentElement.lang === 'zh-TW');
    assert.equal(await page.locator('#cli-name').inputValue(), '设置');
    assert.equal(await page.locator('#cli-secret').inputValue(), 'test-only-{0}-启动');
    assert.equal(await page.locator('#cli-default-args').inputValue(), '["--model", "settings"]');
    await page.locator('#cli-submit').click(); await terminalReady();
    await page.waitForFunction(() => !CLI_SAVING);
    await page.locator('#open-settings').click(); await language('en');
    await page.locator('#terminals-button').click(); await terminalReady();
    await page.locator('[data-terminal-view="profiles"]').click();
    assert.equal(await page.locator('.terminal-card h2').last().textContent(), '设置');
    assert.equal(await page.locator('[data-cli-action="edit"]').last().getAttribute('aria-label'), 'Edit 设置');
    await page.locator('[data-terminal-view="history"]').click();
    assert.equal(await page.locator('.terminal-session-info h2').first().textContent(), '完善项目登录与权限流程');
    assert.ok((await page.locator('.terminal-session-meta').last().textContent()).includes('Project folder no longer exists'));
    assert.ok((await page.locator('.terminal-session-meta').first().textContent()).includes('Oct'));

    // Late asynchronous updates and nested diagnostics use the current language.
    await page.locator('#open-settings').click();
    await page.locator('[data-panel="updates"]').click();
    await page.locator('#update-action').click();
    await page.waitForFunction(() => UPDATE.phase === 'available');
    assert.match(await page.locator('#update-status').textContent(), /^New version available:/);
    await page.locator('#update-action').click();
    await page.waitForFunction(() => UPDATE.phase === 'ready');
    await text('#update-action', 'Install and restart');
    const translations = await page.evaluate(() => [
      I18n.text('安全检查未通过：出口位于统一禁止地区：中国大陆，禁止启动。 已取消启动。'),
      I18n.text('已发送 设置 {0} <script> 启动请求'),
      I18n.text('系统代理格式无效，请检查主机地址和端口（1–65535）。已取消启动。'),
    ]);
    assert.equal(translations[0], 'Safety check failed: The exit region is blocked by the shared policy: Mainland China. Launch is blocked. Launch cancelled.');
    assert.equal(translations[1], 'Launch requested for 设置 {0} <script>');
    assert.equal(translations[2], 'Invalid system proxy format. Check the host and port (1–65535). Launch cancelled.');
    assert.equal(await page.evaluate(() => I18n.text('toString')), 'toString');
    assert.equal(await page.evaluate(() => I18n.text('__proto__')), '__proto__');

    // All supported languages fit the native minimum window size.
    for (const width of [1000, 760, 600]) {
      await page.setViewportSize({width, height: 720});
      await page.locator('#nav-common').click();
      for (const selected of ['en', 'zh-TW', 'zh-CN']) {
        await language(selected);
        assert.equal(await fits(), true, `Header overflows at ${width}px in ${selected}`);
        for (const id of ['#app-language', '#save-settings', '#cancel-common']) {
          assert.equal(await page.locator(id).evaluate(el => {
            const box = el.getBoundingClientRect();
            return box.x >= 0 && box.right <= innerWidth && box.y >= 0 && box.bottom <= innerHeight;
          }), true, `${id} is clipped at ${width}px in ${selected}`);
        }
      }
    }

    // A failed save reverts the selector and keeps the language and dirty form.
    const failure = new URL(url); failure.searchParams.set('save', 'error');
    await page.goto(failure.href); await page.waitForFunction(() => READY);
    await page.locator('#open-settings').click();
    await page.locator('#auto-proxy-env').check();
    await page.locator('#app-language').selectOption('en');
    await page.waitForFunction(() => !document.getElementById('language-error').hidden);
    assert.equal(await page.locator('html').getAttribute('lang'), 'zh-CN');
    assert.equal(await page.locator('#app-language').inputValue(), 'zh-CN');
    assert.equal(await page.locator('#auto-proxy-env').isChecked(), true);
    assert.equal(await page.evaluate(() => isDirty('common')), true);

    for (const [system, resolved] of [['zh-HK', 'zh-TW'], ['zh-SG', 'zh-CN'], ['fr-FR', 'en']]) {
      const local = await browser.newContext({locale: system});
      const tab = await local.newPage();
      await tab.goto(url.href); await tab.waitForFunction(() => READY);
      assert.equal(await tab.locator('html').getAttribute('lang'), resolved);
      await local.close();
    }
    assert.deepEqual(errors, []);
    console.log('PASS: language selection, system fallback, persistence, drafts, private values, async messages, errors and 600–1000px layouts');
  } finally { await browser.close(); }
}
main().catch(error => {console.error(error); process.exitCode = 1;});
