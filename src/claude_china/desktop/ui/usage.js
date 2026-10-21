let USAGE = null;
let usagePoll, usageRequest = 0;
const usageNames = {claude: 'Claude Code', codex: 'Codex', grok: 'Grok CLI', 'grok-bot': 'Grok Bot'};
const usageNumber = value => value == null ? '—' : new Intl.NumberFormat(I18n.locale(), {notation: 'compact', maximumFractionDigits: 1}).format(value);
const usageExact = value => value == null ? '—' : new Intl.NumberFormat(I18n.locale()).format(value);

async function refreshUsage(scan = false) {
  clearTimeout(usagePoll);
  const request = ++usageRequest;
  const error = document.getElementById('usage-error');
  error.hidden = true;
  try {
    if (scan) {
      const started = await api().start_usage_scan();
      if (!started.ok) throw new Error(started.error);
    }
    const result = await api().get_usage_report(Number(document.getElementById('usage-days').value), document.getElementById('usage-tool').value, document.getElementById('usage-project').value);
    if (request !== usageRequest) return;
    if (!result.ok) throw new Error(result.error);
    USAGE = result.data;
    renderUsage();
    if (USAGE.scan.phase === 'scanning' && MAIN_VIEW === 'usage') usagePoll = setTimeout(() => refreshUsage(), 1200);
  } catch (reason) {
    if (request !== usageRequest) return;
    error.textContent = reason.message || '无法读取统计，请重试。';
    error.hidden = false;
    document.getElementById('usage-refresh').disabled = false;
  }
}

function renderUsage() {
  if (!USAGE) return;
  const total = USAGE.totals, scan = USAGE.scan;
  const busy = scan.phase === 'scanning';
  document.getElementById('usage-partial').hidden = !USAGE.warnings.length;
  document.getElementById('usage-refresh').disabled = busy;
  const status = document.getElementById('usage-status');
  status.textContent = busy ? `正在扫描 · ${scan.scanned_files || 0} / ${scan.files || 0}` : scan.phase === 'error' ? scan.error : USAGE.updated_at ? `更新于 ${new Date(USAGE.updated_at * 1000).toLocaleString(I18n.locale())}` : '暂无统计，请刷新扫描本机日志。';
  const progress = document.getElementById('usage-progress');
  progress.hidden = !busy; progress.max = scan.files || 1; progress.value = scan.scanned_files || 0;
  const selector = document.getElementById('usage-project'), selected = selector.value;
  // User-owned paths bypass translation and are always escaped.
  selector.innerHTML = '<option value="">全部项目</option>' + USAGE.project_options.map(path => `<option data-i18n-skip value="${esc(path)}">${esc(path)}</option>`).join('');
  if (selected && !USAGE.project_options.includes(selected)) selector.add(new Option(selected, selected));
  selector.value = selected;
  const cards = [['Token 用量', total.tokens, '输入与输出合计'], ['活跃会话', total.sessions, '所选期间有记录的会话'], ['项目数', total.projects, '已识别的项目目录'], ['活跃天数', total.active_days, '有会话活动的天数']];
  document.getElementById('usage-metrics').innerHTML = cards.map(([label, value, hint]) => `<div class="usage-kpi"><p>${label}</p><strong title="${esc(usageExact(value))}">${esc(usageNumber(value))}</strong><small>${hint}</small></div>`).join('') +
    `<div class="usage-breakdown"><span>输入 <b>${esc(usageNumber(total.input_tokens))}</b></span><span>输出 <b>${esc(usageNumber(total.output_tokens))}</b></span><span>缓存读取 <b>${esc(usageNumber(total.cached_tokens))}</b></span><span>缓存写入 <b>${esc(usageNumber(total.cache_write_tokens))}</b></span></div>`;
  renderUsageChart();
  const max = Math.max(1, ...USAGE.models.map(row => row.tokens || 0));
  document.getElementById('usage-models').innerHTML = USAGE.models.length ? USAGE.models.map(row => `<div class="usage-model"><div><span ${row.model ? 'data-i18n-skip' : ''}>${esc(row.model || '模型未知')}</span><b title="${esc(usageExact(row.tokens))}">${esc(usageNumber(row.tokens))}</b></div><div class="usage-meter"><i style="width:${100 * row.tokens / max}%"></i></div></div>`).join('') : '<p class="usage-empty">所选范围没有可用的 token 记录。</p>';
  document.getElementById('usage-projects').innerHTML = USAGE.projects.length ? USAGE.projects.slice(0, 20).map(row => `<button class="usage-project-row" type="button" data-project="${esc(row.project)}"><span data-i18n-skip title="${esc(row.project)}">${esc(row.project)}</span><strong>${esc(usageNumber(row.tokens))}</strong><small>${row.sessions} 个会话</small></button>`).join('') : '<p class="usage-empty">所选范围没有已识别的项目。</p>';
  document.getElementById('usage-sources').innerHTML = `<div class="usage-table-scroll"><table class="usage-table"><thead><tr><th>工具</th><th>已索引文件</th><th>活跃会话</th><th>Token 用量</th></tr></thead><tbody>${USAGE.tools.map(row => `<tr><td>${esc(usageNames[row.tool])}</td><td>${usageExact(row.files)}</td><td>${usageExact(row.sessions)}</td><td>${usageExact(row.tokens)}</td></tr>`).join('')}</tbody></table></div>`;
  document.getElementById('usage-warnings').innerHTML = USAGE.warnings.map(message => `<li>${esc(message)}</li>`).join('');
  I18n.apply();
}

function renderUsageChart() {
  if (!USAGE) return;
  const metric = document.getElementById('usage-metric').value;
  const maximum = Math.max(1, ...USAGE.daily.map(row => row[metric] || 0));
  const label = metric === 'tokens' ? 'Token 用量' : '活跃会话';
  document.getElementById('usage-chart').innerHTML = USAGE.daily.map(row => {
    const caption = `${row.date} · ${I18n.text(label)}: ${usageExact(row[metric])}`;
    return `<div class="usage-day" tabindex="0" role="img" aria-label="${esc(caption)}" title="${esc(caption)}"><i style="height:${Math.max(1, 100 * (row[metric] || 0) / maximum)}%" class="${row[metric] ? '' : 'is-empty'}"></i></div>`;
  }).join('');
  const days = USAGE.daily;
  document.getElementById('usage-axis').innerHTML = `<span>${esc(days[0]?.date || '')}</span><span>${esc(usageNumber(maximum))}</span><span>${esc(days[days.length - 1]?.date || '')}</span>`;
  document.getElementById('usage-daily-table').innerHTML = `<table class="usage-table"><thead><tr><th>日期</th><th>Token 用量</th><th>活跃会话</th><th>项目数</th></tr></thead><tbody>${days.slice().reverse().map(row => `<tr><td>${esc(row.date)}</td><td>${usageExact(row.tokens)}</td><td>${usageExact(row.sessions)}</td><td>${usageExact(row.projects)}</td></tr>`).join('')}</tbody></table>`;
  I18n.apply();
}

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('usage-button').onclick = () => setMainView('usage');
  document.getElementById('usage-refresh').onclick = () => refreshUsage(true);
  for (const id of ['usage-days', 'usage-tool', 'usage-project']) document.getElementById(id).onchange = () => {
    if (id !== 'usage-project') document.getElementById('usage-project').value = '';
    refreshUsage();
  };
  document.getElementById('usage-metric').onchange = renderUsageChart;
  document.getElementById('usage-projects').onclick = event => {
    const button = event.target.closest('[data-project]');
    if (button) { document.getElementById('usage-project').value = button.dataset.project; refreshUsage(); }
  };
});
window.addEventListener('languagechange', renderUsage);
