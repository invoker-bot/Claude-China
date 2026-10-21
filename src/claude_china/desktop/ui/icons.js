// One outline family shared by the launcher and settings.
const ICON_PATHS = {
  terminal: '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="m7 9 3 3-3 3m6 0h4"/>',
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
  edit: '<path d="m15 4 5 5M4 20l5-1L21 7a2 2 0 0 0-5-5L4 14Z"/>',
  copy: '<rect x="8" y="8" width="12" height="13" rx="2"/><path d="M16 8V3H3v13h5"/>',
  trash: '<path d="M3 6h18M9 6V3h6v3m-10 0 1 15h12l1-15M10 10v7m4-7v7"/>',
  shield: '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6Z"/><path d="m8 12 3 3 5-6"/>',
  refresh: '<path d="M20 7v5h-5M4 17v-5h5"/><path d="M5.5 7a7.5 7.5 0 0 1 12.4-2L20 8M4 16l2.1 3A7.5 7.5 0 0 0 18.5 17"/>',
  settings: '<path d="m9 3-.6 2.3-2 .9-2.2-.6L2.7 8.2l1.7 1.7v2.2l-1.7 1.7 1.5 2.6 2.2-.6 2 .9L9 19h3l.6-2.3 2-.9 2.2.6 1.5-2.6-1.7-1.7V9.9l1.7-1.7-1.5-2.6-2.2.6-2-.9L12 3Z" transform="translate(1.5 1)"/><circle cx="12" cy="12" r="3"/>',
  network: '<circle cx="12" cy="5" r="3"/><circle cx="5" cy="18" r="3"/><circle cx="19" cy="18" r="3"/><path d="m10.5 7.7-4 7.6m7-7.6 4 7.6M8 18h8"/>',
  arrow: '<path d="m9 5 7 7-7 7"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v.1"/>',
  folder: '<path d="M3 7V5h6l2 2h10v13H3Z"/>',
  plus: '<circle cx="12" cy="12" r="9"/><path d="M12 8v8m-4-4h8"/>',
  close: '<path d="m6 6 12 12M6 18 18 6"/>',
  minimize: '<path d="M5 12h14"/>',
  maximize: '<rect x="5" y="5" width="14" height="14" rx=".5"/>',
  restore: '<path d="M9 5h10v10M9 5v4m10 6h-4"/><rect x="5" y="9" width="10" height="10" rx=".5"/>',
  external: '<path d="M14 3h7v7m0-7L10 14M10 4H4v16h16v-6"/>',
  document: '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6m-6 4h6m-6 4h4"/>',
  sliders: '<path d="M3 5h4m4 0h10M3 12h10m4 0h4M3 19h4m4 0h10"/><circle cx="9" cy="5" r="2"/><circle cx="15" cy="12" r="2"/><circle cx="9" cy="19" r="2"/>',
  play: '<path d="m8 4 12 8-12 8Z" fill="currentColor" stroke="none"/>',
  stop: '<rect x="5" y="5" width="14" height="14" rx="1.5" fill="currentColor" stroke="none"/>',
};

function icon(name) {
  return `<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${ICON_PATHS[name] || ""}</svg>`;
}

function appSymbol(id) {
  if (id === "claude") return '<img src="claude.png" alt="" draggable="false">';
  if (id === "codex") return '<img src="codex.png" alt="" draggable="false">';
  if (id === "grok-bot") return '<img src="grok-bot.png" alt="" draggable="false">';
  return icon("document");
}

document.querySelectorAll("[data-icon]").forEach(el => { el.innerHTML = icon(el.dataset.icon); });
