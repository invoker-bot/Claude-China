// Source-language catalogs also cover messages returned by the Python bridge.
// Translate text in place so switching language never reconstructs a form draft.
const I18n = (() => {
  let language = 'system', resolved = 'zh-CN', messages = {}, patterns = [];
  const originals = new WeakMap();
  const attributes = ['title', 'aria-label', 'placeholder'];
  const skip = 'script, style, textarea, [data-i18n-skip]';
  const options = {subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: attributes};
  const escapeRegex = value => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  // These arguments are application-owned diagnostic messages, not user data.
  const nested = new Set(['安全检查未通过：{0} 已取消启动。', '安全检查未通过：{0}',
    '{0} 已取消启动。', '{0}已取消启动。', '出口位于统一禁止地区：{0}，禁止启动。',
    '更新未完成：{0} 原有设置已保留。', '{0}格式无效。', '请填写{0}。']);

  function text(source, depth = 0) {
    if (!source || resolved === 'zh-CN' || depth > 4) return source;
    const leading = source.match(/^\s*/)[0], trailing = source.match(/\s*$/)[0];
    const key = source.trim();
    if (!key) return source;
    let result = Object.prototype.hasOwnProperty.call(messages, key) ? messages[key] : undefined;
    if (result === undefined && /（预览(?:示例)?）[。]?$/.test(key)) {
      result = key.replace(/^(.*)（(预览(?:示例)?)）([。]?)$/, (_, message, label, punctuation) =>
        text(message, depth + 1) + ' (' + text(label, depth + 1) + ')' + (resolved === 'en' && punctuation ? '.' : punctuation));
    }
    if (result === undefined) {
      for (const entry of patterns) {
        const match = entry.regex.exec(key);
        if (!match) continue;
        result = entry.target.replace(/\{(\d+)\}/g, (_, index) => {
          const value = match[entry.indices.indexOf(index) + 1];
          return nested.has(entry.source) ? text(value, depth + 1) : value;
        });
        break;
      }
    }
    // Composed status summaries are messages separated by a visible delimiter.
    if (result === undefined && key.includes(' · ')) result = key.split(' · ').map(part => text(part, depth + 1)).join(' · ');
    if (result === undefined && key.startsWith('· ')) result = '· ' + text(key.slice(2), depth + 1);
    if (result === undefined && / \d+%$/.test(key)) result = key.replace(/^(.*)( \d+%)$/, (_, message, percent) => text(message, depth + 1) + percent);
    return leading + (result === undefined ? key : result) + trailing;
  }

  function update(node, name, value, write) {
    const saved = originals.get(node) || {};
    const previous = saved[name];
    const source = previous && value === previous.output ? previous.source : value;
    const output = text(source);
    saved[name] = {source, output};
    originals.set(node, saved);
    if (value !== output) write(output);
  }

  function apply() {
    observer.disconnect();
    try {
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) {
        const node = walker.currentNode;
        const element = node.nodeType === Node.TEXT_NODE ? node.parentElement : node;
        if (!element || element.closest(skip)) continue;
        if (node.nodeType === Node.TEXT_NODE) update(node, 'text', node.nodeValue, value => { node.nodeValue = value; });
        else for (const name of attributes) {
          if (node.hasAttribute(name)) update(node, name, node.getAttribute(name), value => node.setAttribute(name, value));
        }
      }
    } finally { observer.observe(document.body, options); }
  }
  const observer = new MutationObserver(apply);

  function setLocale(data) {
    language = data.language; resolved = data.resolved; messages = data.messages || {};
    patterns = Object.entries(messages).filter(([source]) => /\{\d+\}/.test(source)).map(([source, target]) => {
      const indices = [];
      const regex = new RegExp('^' + source.split(/(\{\d+\})/).map(part => {
        const placeholder = /^\{(\d+)\}$/.exec(part);
        if (!placeholder) return escapeRegex(part);
        indices.push(placeholder[1]); return '([\\s\\S]*?)';
      }).join('') + '$');
      return {source, target, regex, indices};
    }).sort((a, b) => b.source.length - a.source.length);
    document.documentElement.lang = resolved;
    document.getElementById('app-language').value = language;
    window.dispatchEvent(new Event('languagechange'));
    apply();
  }

  async function change() {
    const select = document.getElementById('app-language');
    if (select.disabled) return;
    select.disabled = true;
    const error = document.getElementById('language-error');
    error.hidden = true;
    try {
      const result = await api().set_language(select.value);
      if (!result.ok) throw new Error(result.error || '语言设置保存失败，请重试。');
      setLocale(result.data);
      toast('语言设置已保存');
    } catch (reason) {
      select.value = language;
      error.textContent = reason.message || '语言设置保存失败，请重试。';
      error.hidden = false;
    } finally { select.disabled = false; }
  }

  async function init() {
    document.getElementById('app-language').onchange = change;
    setLocale(await api().get_locale());
  }
  return {init, apply, text, locale: () => resolved};
})();
