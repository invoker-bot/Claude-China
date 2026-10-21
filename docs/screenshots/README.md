# README screenshots

All five PNGs show the v0.4.2 desktop UI in English at a 1120 × 780 logical viewport
with a 2× pixel scale.
They use the browser preview's in-memory example data with English profile names
and session titles; no real profiles, credentials, project history or native app
status are captured.

- `desktop-apps.png`: app launch controls and shared launch settings.
- `terminal-history.png`: project search and exact-session resume.
- `favorite-projects.png`: saved project folders and new sessions.
- `desktop-settings.png`: system proxy checks and environment variables.
- `desktop-language-en.png`: display language selection in general settings.

The root README uses absolute raw GitHub image URLs so the same images can
load when the package description is rendered on PyPI.

## Refresh the screenshots

From the repository root, serve the static UI:

```sh
python -m http.server 8769 --bind 127.0.0.1 --directory src/claude_china/desktop/ui
```

In an environment with Node.js, Playwright and a supported browser installed:

```sh
node tools/capture_readme_screenshots.cjs "http://127.0.0.1:8769/?preview"
```

`PLAYWRIGHT_MODULE` can point to an existing Playwright package if it is not on
Node's module search path. `PLAYWRIGHT_CHANNEL` can select an installed browser,
such as `msedge` or `chrome`; otherwise Playwright uses its bundled Chromium.

The script only accepts a local preview URL and forces English regardless of the
system language. It seeds English sample content in the isolated preview bridge;
real profile names and session titles are never translated. It configures a demo
app, searches history, favorites a demo project and saves demo settings through
the UI, then waits for notifications to disappear before capturing. It checks the
page title, English locale, loaded images, horizontal overflow, expected UI state
and browser console.
Review all five images for clipping and legibility before committing them.

Capture verification used headless Edge with Playwright; the Browser plugin was
not available in the authoring environment. Screenshots demonstrate the UI, not
native launch or update execution.
