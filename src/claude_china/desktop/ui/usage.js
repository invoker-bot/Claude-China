let USAGE = null;
let usagePoll, usageRequest = 0;
const usageNames = {claude: 'Claude Code', codex: 'Codex', grok: 'Grok CLI', 'grok-bot': 'Grok Bot'};
const usageNumber = value => value == null ? '—' : new Intl.NumberFormat(I18n.locale(), {notation: 'compact', maximumFractionDigits: 1}).format(value);
const usageExact = value => value == null ? '—' : new Intl.NumberFormat(I18n.locale()).format(value);
const usageMoney = value => value == null ? '—' : new Intl.NumberFormat(I18n.locale(), {style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 4}).format(value);
const usageCost = row => `${esc(usageMoney(row.cost_usd))}<small>${row.cost_status === 'partial' ? '部分估算' : row.cost_usd == null ? '无法计价' : '估算'}</small>`;

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
    const result = await api().get_usage_report(Number(document.getElementById('usage-days').value), document.getElementById('usage-tool').value, document.getElementById('usage-project').value, document.getElementById('usage-model').value);
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
  const models = document.getElementById('usage-model'), selectedModel = models.value;
  models.innerHTML = '<option value="all">全部模型</option>' + USAGE.model_options.map(model => `<option ${model ? 'data-i18n-skip' : ''} value="${esc(model)}">${esc(model || '模型未知')}</option>`).join('');
  if (selectedModel !== 'all' && !USAGE.model_options.includes(selectedModel)) models.add(new Option(selectedModel || I18n.text('模型未知'), selectedModel));
  models.value = selectedModel;
  const cards = [['Token 用量', total.tokens, '输入与输出合计'], ['等效 API 费用', total.cost_usd, total.cost_status === 'partial' ? '仅已知价格部分 · USD' : 'Standard · USD'], ['工具调用', total.tool_calls, '按调用 ID 去重'], ['活跃会话', total.sessions, '所选期间有记录的会话'], ['项目数', total.projects, '已识别的项目目录'], ['活跃天数', total.active_days, '有会话活动的天数']];
  document.getElementById('usage-metrics').innerHTML = cards.map(([label, value, hint], i) => `<div class="usage-kpi ${i === 1 ? 'usage-cost-kpi' : ''}"><p>${label}</p><strong title="${esc(i === 1 ? usageMoney(value) : usageExact(value))}">${esc(i === 1 ? usageMoney(value) : usageNumber(value))}</strong><small>${hint}</small></div>`).join('') +
    `<div class="usage-breakdown"><span>输入 <b>${esc(usageNumber(total.input_tokens))}</b></span><span>输出 <b>${esc(usageNumber(total.output_tokens))}</b></span><span>缓存读取 <b>${esc(usageNumber(total.cached_tokens))}</b></span><span>缓存写入 <b>${esc(usageNumber(total.cache_write_tokens))}</b></span></div>`;
  renderUsageChart();
  renderUsageDetails();
  renderUsageCalls();
  document.getElementById('usage-projects').innerHTML = USAGE.projects.length ? USAGE.projects.slice(0, 20).map(row => `<button class="usage-project-row" type="button" data-project="${esc(row.project)}"><span data-i18n-skip title="${esc(row.project)}">${esc(row.project)}</span><strong>${esc(usageNumber(row.tokens))} · ${esc(usageMoney(row.cost_usd))}</strong><small>${row.sessions} 个会话</small></button>`).join('') : '<p class="usage-empty">所选范围没有已识别的项目。</p>';
  document.getElementById('usage-sources').innerHTML = `<div class="usage-table-scroll"><table class="usage-table"><thead><tr><th>工具</th><th>已索引文件</th><th>活跃会话</th><th>Token 用量</th></tr></thead><tbody>${USAGE.tools.map(row => `<tr><td>${esc(usageNames[row.tool])}</td><td>${usageExact(row.files)}</td><td>${usageExact(row.sessions)}</td><td>${usageExact(row.tokens)}</td></tr>`).join('')}</tbody></table></div>`;
  document.getElementById('usage-warnings').innerHTML = USAGE.warnings.map(message => `<li>${esc(message)}</li>`).join('');
  I18n.apply();
}

function renderUsageDetails() {
  const rows = USAGE.models;
  document.getElementById('usage-models').innerHTML = rows.length ? `<table class="usage-table usage-detail-table"><thead><tr><th>工具 / 模型</th><th>输入</th><th>输出</th><th>缓存读取</th><th>缓存写入</th><th>工具调用</th><th>活跃会话</th><th>等效 API 费用</th></tr></thead><tbody>${rows.map(row => `<tr class="usage-model"><td><small>${esc(usageNames[row.tool])}</small><button class="usage-filter-link" data-model="${esc(row.model)}" data-tool="${esc(row.tool)}" ${row.model ? 'data-i18n-skip' : ''}>${esc(row.model || '模型未知')}</button></td>${['input_tokens', 'output_tokens', 'cached_tokens', 'cache_write_tokens', 'tool_calls', 'sessions'].map(key => `<td title="${esc(usageExact(row[key]))}">${esc(usageNumber(row[key]))}</td>`).join('')}<td>${usageCost(row)}</td></tr>`).join('')}</tbody></table>` : '<p class="usage-empty">所选范围没有可用的 token 记录。</p>';
  const tool = document.getElementById('usage-tool').value;
  document.getElementById('usage-tools').innerHTML = `<table class="usage-table"><thead><tr><th>工具</th><th>Token 用量</th><th>工具调用</th><th>活跃会话</th><th>项目数</th><th>等效 API 费用</th></tr></thead><tbody>${USAGE.tools.filter(row => tool === 'all' || row.tool === tool).map(row => `<tr><td><button class="usage-filter-link" data-tool="${esc(row.tool)}">${esc(usageNames[row.tool])}</button></td><td>${usageExact(row.tokens)}</td><td>${usageExact(row.tool_calls)}</td><td>${usageExact(row.sessions)}</td><td>${usageExact(row.projects)}</td><td>${usageCost(row)}</td></tr>`).join('')}</tbody></table>`;
  const isModels = document.getElementById('usage-detail-mode').value === 'models';
  document.getElementById('usage-models').hidden = !isModels;
  document.getElementById('usage-tools').hidden = isModels;
  const total = USAGE.totals;
  document.getElementById('usage-cost-coverage').textContent = !USAGE.pricing.ready ? '正在更新计价索引，请等待扫描完成。' : `价格核对：${USAGE.pricing.checked_on} · 已计价 token：${usageExact(total.priced_tokens)} / ${usageExact(total.tokens)} · 未计价 token：${usageExact(total.unpriced_tokens)} · 缺少用量的会话：${total.missing_usage_sessions} · 使用假设的记录：${total.assumed_records}`;
  document.getElementById('usage-rates').innerHTML = `<table class="usage-table"><thead><tr><th>模型</th><th>输入</th><th>输出</th><th>缓存读取</th><th>短时写入</th><th>长时写入</th><th>价格来源</th></tr></thead><tbody>${rows.map(row => `<tr><td ${row.model ? 'data-i18n-skip' : ''}>${esc(row.model || '模型未知')}</td>${['input', 'output', 'cached', 'write', 'long_write'].map(key => `<td>${esc(usageMoney(row.price?.[key]))}</td>`).join('')}<td>${row.price ? `<button class="usage-filter-link" data-price-model="${esc(row.model)}">官方定价</button>` : '价格未知'}</td></tr>`).join('')}</tbody></table><p class="usage-note">单价单位：USD / 一百万 token。表中为短上下文单价；长上下文按对应模型的门槛和倍率计算。</p>`;
  I18n.apply();
}

function renderUsageCalls() {
  if (!USAGE) return;
  const search = document.getElementById('usage-call-search').value.trim().toLowerCase();
  const mcp = document.getElementById('usage-mcp-only').checked;
  const rows = USAGE.tool_calls.filter(row => (!mcp || row.is_mcp) && row.name.toLowerCase().includes(search));
  document.getElementById('usage-calls').innerHTML = rows.length ? `<table class="usage-table"><thead><tr><th>调用名称</th><th>来源应用</th><th>调用次数</th><th>活跃会话</th></tr></thead><tbody>${rows.map(row => `<tr><td data-i18n-skip>${esc(row.name)}</td><td>${esc(usageNames[row.tool])}</td><td>${usageExact(row.calls)}</td><td>${usageExact(row.sessions)}</td></tr>`).join('')}</tbody></table>` : '<p class="usage-empty">没有匹配的工具调用记录。</p>';
  I18n.apply();
}

function renderUsageChart() {
  if (!USAGE) return;
  const metric = document.getElementById('usage-metric').value;
  const maximum = Math.max(0, ...USAGE.daily.map(row => row[metric] || 0)) || 1;
  const label = {tokens: 'Token 用量', sessions: '活跃会话', cost_usd: '等效 API 费用', tool_calls: '工具调用'}[metric];
  const format = metric === 'cost_usd' ? usageMoney : usageExact;
  document.getElementById('usage-chart').innerHTML = USAGE.daily.map(row => {
    const caption = `${row.date} · ${I18n.text(label)}: ${format(row[metric])}`;
    return `<div class="usage-day" tabindex="0" role="img" aria-label="${esc(caption)}" title="${esc(caption)}"><i style="height:${Math.max(1, 100 * (row[metric] || 0) / maximum)}%" class="${row[metric] ? '' : 'is-empty'}"></i></div>`;
  }).join('');
  const days = USAGE.daily;
  document.getElementById('usage-axis').innerHTML = `<span>${esc(days[0]?.date || '')}</span><span>${esc(metric === 'cost_usd' ? usageMoney(maximum) : usageNumber(maximum))}</span><span>${esc(days[days.length - 1]?.date || '')}</span>`;
  document.getElementById('usage-daily-table').innerHTML = `<table class="usage-table"><thead><tr><th>日期</th><th>Token 用量</th><th>工具调用</th><th>活跃会话</th><th>项目数</th><th>等效 API 费用</th></tr></thead><tbody>${days.slice().reverse().map(row => `<tr><td>${esc(row.date)}</td><td>${usageExact(row.tokens)}</td><td>${usageExact(row.tool_calls)}</td><td>${usageExact(row.sessions)}</td><td>${usageExact(row.projects)}</td><td>${usageCost(row)}</td></tr>`).join('')}</tbody></table>`;
  I18n.apply();
}

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('usage-button').onclick = () => setMainView('usage');
  document.getElementById('usage-refresh').onclick = () => refreshUsage(true);
  for (const id of ['usage-days', 'usage-tool', 'usage-project', 'usage-model']) document.getElementById(id).onchange = () => {
    if (id === 'usage-days' || id === 'usage-tool') document.getElementById('usage-project').value = '';
    if (id !== 'usage-model') document.getElementById('usage-model').value = 'all';
    refreshUsage();
  };
  document.getElementById('usage-metric').onchange = renderUsageChart;
  document.getElementById('usage-detail-mode').onchange = renderUsageDetails;
  document.getElementById('usage-call-search').oninput = renderUsageCalls;
  document.getElementById('usage-mcp-only').onchange = renderUsageCalls;
  for (const id of ['usage-models', 'usage-tools']) document.getElementById(id).onclick = event => {
    const button = event.target.closest('[data-tool]');
    if (!button) return;
    document.getElementById('usage-tool').value = button.dataset.tool;
    document.getElementById('usage-model').value = button.dataset.model ?? 'all';
    refreshUsage();
  };
  document.getElementById('usage-rates').onclick = async event => {
    const button = event.target.closest('[data-price-model]');
    if (!button) return;
    try { if (!(await api().open_usage_price_source(button.dataset.priceModel)).ok) toast('无法打开价格来源。'); }
    catch { toast('无法打开价格来源。'); }
  };
  document.getElementById('usage-projects').onclick = event => {
    const button = event.target.closest('[data-project]');
    if (button) { document.getElementById('usage-project').value = button.dataset.project; refreshUsage(); }
  };
});
window.addEventListener('languagechange', renderUsage);
