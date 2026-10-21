# Desktop localization

Settings → General → Display language offers `system`, `zh-CN`, `zh-TW` and `en`.
It saves immediately to the desktop configuration, independently of form drafts.
The default is `system`; unsupported OS languages fall back to English. Windows
uses the user's display language, macOS uses the first preferred Apple language,
and Linux uses the locale environment. The preference changes presentation only.

## Message catalogs

`src/claude_china/desktop/ui/locales.json` is the shared, offline catalog for the
webview, tray, native menus and desktop launch diagnostics. Simplified Chinese is
the source language; each source message has English and Traditional Chinese
translations. It is bundled with both wheels and desktop installers. No translation
service or additional runtime dependency is used.

Add a matching entry to both catalogs for each new label or diagnostic. Use
`{0}`, `{1}`, etc. for variable parts, keeping the same placeholders in each
translation. Do not translate values such as profile names, session titles,
paths or credentials. Generated profile-copy suffixes are translated separately.

`i18n.js` translates text nodes and accessible labels in place, remembers their
source strings, and observes late status updates. It never rewrites input values
or regenerates forms when the language changes. Mark user-owned text elements
with `data-i18n-skip`, including their titles. Keep timestamps and other opaque
data separate from translated status text. Use `I18n.locale()` for date formatting.
Only explicitly listed diagnostic templates recursively translate their message
arguments; ordinary placeholders are always copied literally. Keep that small
list aligned with `localization.translate_message` if adding nested diagnostics.

Native menus retain their commands and keyboard shortcuts when relabeled. Cocoa
updates run on its main thread. OS-owned dialogs or Services entries follow the
OS's own localization. The CLI command interface and launched providers keep
their own language settings.

## Verification

- `python -m pytest tests/ -q`: catalogs, placeholders, static labels, system
  language resolution, persistence, failed saves, concurrent writes, native menu
  dispatch and launch invariants.
- Serve `src/claude_china/desktop/ui` locally, then run
  `node tools/test_desktop_localization.cjs "http://127.0.0.1:8769/?preview"`.
  It checks immediate switching, reload persistence, system fallback, drafts,
  secrets, user data, dynamic diagnostics and 600–1000 px layouts using Playwright.
  `PLAYWRIGHT_MODULE` and `PLAYWRIGHT_CHANNEL` can use an existing installation.
- `python -m claude_china.desktop.entry --smoke-test <report.json>` tests the
  actual webview and tray with temporary desktop/CLI configuration. It switches
  all three languages, verifies persisted selections and preserves a form draft.
  It never launches or stops the user's provider apps.

This change was verified in Edge/Windows WebView2. macOS and Linux have mocked
platform tests and the same packaged smoke assertions, but were not run locally.
