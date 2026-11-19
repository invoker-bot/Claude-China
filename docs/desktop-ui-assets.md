# Desktop UI assets

Application logos come from installed applications or official web assets,
are bundled locally for offline use, and are shared by the launcher cards and settings
navigation. The launcher's own `icon.png` is separate from the Claude application logo.

## Claude

`src/claude_china/desktop/ui/claude.png` comes from Anthropic's installed package
`Claude_3.1623.0.0_x64__pzs8sxrjxfjjc`:

- Original resource: `assets/Square44x44Logo.targetsize-256_altform-unplated.png`.
- SHA-256: `28f6dfd7bc66bffe9ac40dac94dc90b7bae9b4a60b123f687c90ab2b86a63eb0`.

## Codex

`src/claude_china/desktop/ui/codex.png` is the unmodified Codex app logo
from OpenAI's installed desktop package `OpenAI.Codex_26.1013.4894.0_x64__2p2nqsd0c76g0`:

- Original resource: `app/resources/app.asar` → `webview/assets/codex-app-ga-logo-3e5209898ca3.png`.
- SHA-256: `8e82b26c98a10e45798ce48124515720657f7735fb8d0853b3f087eaa8a6b74e`.
- Used to identify Codex in the launcher card and settings navigation. It is bundled locally for offline use.

## Grok Bot

`src/claude_china/desktop/ui/grok-bot.png` comes from the installed Grok Bot 0.72.0 application:

- Original resource: `resources/app.asar` → `dist/renderer/assets/app-icon-C7NKj2u7.png`.
- SHA-256: `79e6a73e634ce7ad8d1982739e9064bcc9c9ec5106bdd7281d7514ee68169ad2`.
- This is Grok Bot's robot icon, not the separate Grok chatbot's logo.

## Antigravity

`src/claude_china/desktop/ui/antigravity.png` is the 48 × 48 official favicon
from `https://antigravity.google/favicon.ico`, converted to RGBA and resized to
256 × 256 with Lanczos resampling.

- Source SHA-256: `d81604f50d96d4d7c3212bde47f598876985951eb7fdc4bebb30ab2691b7f531`.
- Packaged PNG SHA-256: `b3b2f1bedbe85003da4a1827fd46b8a85d252c11c92a130ed7eae60c22f4c1c3`.

The application names and logos belong to their respective owners; the project's
MIT license does not grant rights to third-party trademarks.
