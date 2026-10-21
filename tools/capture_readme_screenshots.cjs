// Capture the shipped UI with its in-memory preview data; no native apps or
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
  url.searchParams.set('lang', 'zh-CN');
  const output = path.resolve(__dirname, '../docs/screenshots');
  await fs.mkdir(output, { recursive: true });
  const options = { headless: true };
  if (process.env.PLAYWRIGHT_CHANNEL) options.channel = process.env.PLAYWRIGHT_CHANNEL;
  const browser = await chromium.launch(options);
  const page = await browser.newPage({ viewport: { width: 1120, height: 780 },
    deviceScaleFactor: 2, locale: 'zh-CN', timezoneId: 'Asia/Shanghai', reducedMotion: 'reduce' });
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

    // Configure the demo Codex installation through the same controls users see.
    await page.locator('#gear-codex').click();
    await page.locator('#pick-codex').click();
    await page.locator('#save-codex').click();
    await page.getByRole('button', { name: '我的应用', exact: true }).click();
    await page.locator('#btn-launch-codex').click();
    await page.waitForFunction(() => document.getElementById('status-codex').textContent === '运行中');
    await screenshot('desktop-apps');

    await page.getByRole('button', { name: '我的终端', exact: true }).click();
    await terminalReady();
    assert.equal(await page.locator('.terminal-session').count(), 3);
    await page.locator('#terminal-search').fill('Projects');
    assert.equal(await page.locator('.terminal-session').count(), 2);
    await screenshot('terminal-history');

    await page.getByRole('button', { name: '常用项目', exact: true }).click();
    const docsProject = page.locator('.terminal-project-card').filter({
      has: page.getByRole('heading', { name: 'docs-site', exact: true }),
    });
    await docsProject.getByRole('button', { name: '收藏 docs-site', exact: true }).click();
    await terminalReady();
    assert.equal(await docsProject.getByRole('button', { name: '取消收藏 docs-site', exact: true }).getAttribute('aria-pressed'), 'true');
    await page.locator('#terminal-launch-profile').selectOption('工作项目');
    await terminalReady();
    await page.locator('#terminal-search').fill('Projects');
    assert.equal(await page.locator('.terminal-project-card').count(), 2);
    await screenshot('favorite-projects');

    await page.getByRole('button', { name: '设置', exact: true }).click();
    await page.locator('[data-panel="common"]').click();
    await page.locator('#auto-proxy-env').check();
    await page.locator('#save-settings').click();
    assert.equal(await page.locator('#auto-proxy-env').isChecked(), true);
    await screenshot('desktop-settings');
    assert.deepEqual(errors, []);
    console.log('All four screenshots passed page, image, overflow and console checks.');
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
