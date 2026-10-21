// Capture the current English UI with in-memory preview data; no native apps or
// user configuration are accessed. Requires Playwright and an installed browser.
// Usage: node tools/capture_readme_screenshots.cjs [preview URL]
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

async function main() {
  const url = new URL(process.argv[2] || 'http://127.0.0.1:8769/?preview');
  assert.ok(['http:', 'https:'].includes(url.protocol), 'Use an HTTP preview server');
  assert.ok(['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname), 'Use a local preview server');
  assert.ok(url.searchParams.has('preview'), 'Screenshot capture requires demo mode');
  url.searchParams.set('lang', 'en');
  const output = path.resolve(__dirname, '../docs/screenshots');
  await fs.mkdir(output, { recursive: true });
  const options = { headless: true };
  if (process.env.PLAYWRIGHT_CHANNEL) options.channel = process.env.PLAYWRIGHT_CHANNEL;
  const browser = await chromium.launch(options);
  const page = await browser.newPage({ viewport: { width: 1120, height: 780 },
    deviceScaleFactor: 2, locale: 'en-US', timezoneId: 'UTC', reducedMotion: 'reduce' });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => {
    if (['error', 'warning'].includes(message.type())) errors.push(message.text());
  });
  const terminalReady = () => page.waitForFunction(() =>
    !TERMINAL_LOADING && !TERMINAL_HISTORY_LOADING && !TERMINAL_STARTING);
  const screenshot = async name => {
    await page.evaluate(() => document.fonts.ready);
    await page.waitForFunction(() => getComputedStyle(document.getElementById('toast')).opacity === '0');
    await page.locator('h1:visible').click();
    await page.mouse.move(5, 775);
    assert.equal(await page.locator('html').getAttribute('lang'), 'en');
    assert.equal(await page.locator('#home-button').textContent(), 'My apps');
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    assert.equal(await page.evaluate(() => [...document.images].every(image => image.complete && image.naturalWidth > 0)), true);
    await page.screenshot({ path: path.join(output, name + '.png'), animations: 'disabled' });
    console.log('Captured ' + name + '.png');
  };
  try {
    await page.goto(url.href);
    await page.waitForFunction(() => READY);
    assert.equal(await page.title(), 'Claude China');
    assert.equal(await page.locator('.bay').count(), 3);

    // Use English sample content for documentation only. The app correctly keeps
    // user-authored profile names and session titles unchanged when switching languages.
    await page.evaluate(async () => {
      const bridge = window.pywebview.api;
      for (const [original, name] of [
        ['日常开发', 'Daily development'],
        ['工作项目', 'Work projects'],
        ['个人账号', 'Personal account'],
      ]) {
        const result = await bridge.get_cli_profile(original);
        if (!result.ok) throw new Error('Missing demo profile: ' + original);
        const saved = await bridge.save_cli_profile({...result.data, name}, original, result.data.revision);
        if (!saved.ok) throw new Error('Could not rename demo profile: ' + original);
      }
      const titles = {
        '完善项目登录与权限流程': 'Improve sign-in and permissions',
        '整理文档站点与导航': 'Refresh docs navigation',
        '旧版页面探索': 'Explore legacy pages',
      };
      const listHistory = bridge.list_cli_history;
      bridge.list_cli_history = async name => {
        const result = await listHistory(name);
        if (result.ok) {
          result.data.sessions = result.data.sessions.map(session => {
            if (!titles[session.title]) throw new Error('Unknown demo session title: ' + session.title);
            return {...session, title: titles[session.title]};
          });
        }
        return result;
      };
    });

    // Configure the demo Codex installation through the same controls users see.
    await page.locator('#gear-codex').click();
    await page.locator('#pick-codex').click();
    await page.locator('#save-codex').click();
    await page.getByRole('button', { name: 'My apps', exact: true }).click();
    await page.locator('#btn-launch-codex').click();
    await page.waitForFunction(() => document.getElementById('status-codex').textContent === 'Running');
    await screenshot('desktop-apps');

    await page.getByRole('button', { name: 'My terminals', exact: true }).click();
    await terminalReady();
    assert.equal(await page.locator('.terminal-session').count(), 3);
    await page.locator('#terminal-search').fill('Projects');
    assert.equal(await page.locator('.terminal-session').count(), 2);
    await screenshot('terminal-history');

    await page.getByRole('button', { name: 'Favorite projects', exact: true }).click();
    const docsProject = page.locator('.terminal-project-card').filter({
      has: page.getByRole('heading', { name: 'docs-site', exact: true }),
    });
    await docsProject.getByRole('button', { name: 'Favorite docs-site', exact: true }).click();
    await terminalReady();
    assert.equal(await docsProject.getByRole('button', { name: 'Unfavorite docs-site', exact: true }).getAttribute('aria-pressed'), 'true');
    await page.locator('#terminal-launch-profile').selectOption('Work projects');
    await terminalReady();
    await page.locator('#terminal-search').fill('Projects');
    assert.equal(await page.locator('.terminal-project-card').count(), 2);
    await screenshot('favorite-projects');

    await page.getByRole('button', { name: 'Settings', exact: true }).click();
    await page.locator('[data-panel="common"]').click();
    assert.equal(await page.locator('#app-language').inputValue(), 'en');
    await screenshot('desktop-language-en');
    await page.locator('#auto-proxy-env').check();
    await page.locator('#save-settings').click();
    assert.equal(await page.locator('#auto-proxy-env').isChecked(), true);
    await screenshot('desktop-settings');

    await page.setViewportSize({ width: 1280, height: 1000 });
    await page.locator('#usage-button').click();
    await page.waitForFunction(() => USAGE && USAGE.totals.cost_usd > 0);
    assert.equal(await page.locator('.usage-kpi').count(), 6);
    assert.equal(await page.locator('#usage-title').textContent(), 'Usage & activity');
    assert.equal(await page.locator('#usage-models tbody tr').count(), 3);
    await screenshot('usage-statistics');
    assert.deepEqual(errors, []);
    console.log('All six English screenshots passed page, image, overflow and console checks.');
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
