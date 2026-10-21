# Original-entry takeover on Windows

The Windows x64 installer provides independent registrations for Claude,
Codex and Grok Bot **when installed as a conventional EXE at a fixed path**.
Open Settings → the application → **接管原入口** after saving settings.
Windows requests administrator authorization to register that application's
launch filter; the launcher and vendor application still run as the normal user.
Adding support never enables any application automatically.

**The currently detected Claude and Codex installations are MSIX and remain
unsupported.** Their controls explain this limitation and cannot enable a
partial path-only guard. Selecting an EXE inside a package manually does not
bypass this restriction. Versioned Squirrel `app-<version>` paths are also
rejected. See [platform support and remaining work](launch-takeover-platforms.md).

Once enabled, opening the registered original EXE, Desktop/Start Menu shortcuts,
or an updater restart at the same installation path runs the saved system-proxy
checks, automatic proxy-variable handling and region policy before the app is
created. Unknown results block in strict mode. Every main-process launch reads
settings again; disabling a saved check has the same meaning here as in the
launcher. Existing running instances are not retroactively checked or stopped.

The toggle takes effect immediately, independently of the settings Save button.
Disable it in the same panel to restore ordinary launches. The uninstaller also
removes the owned registration before deleting the launcher; cancelled or failed
administrator cleanup cancels uninstallation. Do not manually delete the
launcher while takeover is enabled. If either installation directory changes,
disable takeover first and enable it again against the new path.

## Implementation and scope

- The 64-bit IFEO key for the selected executable contains an exact `FilterFullPath` and
  an ownership marker. Registration refuses existing foreign configuration.
  Removal preserves unrelated values and filters. Enabling/disabling one app
  never changes another app's registration. Vendor shortcuts are unchanged.
- The original executable and its signature remain intact on disk. A fresh
  broker checks the environment before creating a suspended main process. It
  injects the bundled compatibility DLL in memory and resumes only if that
  operation succeeds. There is no unchecked fallback.
- Chromium needs real child process IDs and handles for its sandbox. The DLL
  uses Microsoft Detours to handle only same-executable renderer, GPU, utility
  and crash-handler creation. Those children retain the vendor's handles,
  token and suspension behavior. Ordinary main/relauncher starts still pass
  through the Windows filter. No `--no-sandbox` switch is added.
- A restart restores prior values of variables overwritten by the last
  injection before applying current settings. That small record travels only
  in process memory, not in configuration or diagnostics. User/session-wide
  environment variables are never edited.
- `~/.claudec/takeover/<app-id>.json` stores paths and registration ownership.
  Existing schema-1 Grok manifests remain compatible. Uninstallation removes
  all owned app registrations, including those whose vendor EXE was removed.
  The adjacent `logs/` directory retains at most 50 launch decisions with
  app IDs, timestamps, PIDs and safe error text; it omits IP addresses and environment
  values. Configuration remains in the existing `~/.claudec/desktop.yaml`.

This is a launch guard for normal application entries, not an OS security
boundary against a user deliberately bypassing it. An administrator can remove
the filter, and a different executable path is outside its scope. It does not
prove provider eligibility or that every network request obeys the app's proxy
environment. MSIX applications and other operating systems do not have a native
global interceptor in this implementation. A moved/deleted target, invalid
registration or missing manifest is not reported as a protected current entry.

## Initial Grok-only verification on 2026-10-21

The installed frozen Windows launcher was tested against the real Grok Bot:

- Original EXE, original Desktop shortcut and original Start Menu shortcut all
  reached the guard, started the main process and Chromium children, and had
  `HTTP_PROXY` / `HTTPS_PROXY` present in the main process.
- A validly signed official 0.72.1 installer upgraded 0.72.0 using the vendor
  updater's `--updated /S --force-run` arguments. Its automatic restart ran a new
  guard check and started 0.72.1 with both proxy variables and the native hook.
  This exercised the real installer/restart path, not an in-app update click.
- An incoming `NO_PROXY=*` made the route ambiguous. Strict mode returned
  unknown and created no new Grok process; the already running instance remained
  untouched. Unit tests also cover denylisted and unknown decisions.
- The installed uninstaller cleanup command removed the registration, a second
  cleanup was a no-op, and re-enabling restored the exact-path filter. The final
  installed executable, native DLL and settings UI matched the rebuilt bundle.
- All 22 recorded Claude/Codex processes retained their PIDs and creation times.
  The four existing configuration files in `.claudec` and `.code-ai` retained
  their hashes. Grok's program version changed intentionally during the upgrade.

The entry-point tests used a separate Grok data directory. The vendor installer
restarted through the user's desktop session and did not retain that test-only
directory variable, so upgrade acceptance was observed on the normal profile.
No sign-in, account changes or provider requests were used as acceptance tests.

Automated tests cover repeated preflight, settings reload, removing obsolete
injection, fail-closed decisions, exact-path registration/replacement, foreign
key preservation, disable/uninstall behavior and native child PID/exit status.
Run `python tools/build_windows_hook.py` before `python -m pytest tests/ -q`
on Windows to include the native test. Local live reports are under the ignored
`build/desktop/takeover-grok-<run-id>/` directory.

Final Windows checks: 583 tests passed, 2 skipped, plus successful frozen and
installed GUI smoke runs. The preview's enable/disable control, unsaved-edit
guard and Grok-only visibility passed in headless Edge at 1000×780 and 760×650,
with no console errors. Preview interactions use mock state, not the registry.

The earlier unsuccessful Python-wrapper experiment is retained in
[the historical probe notes](windows-launch-takeover-probe.md).

## Per-app refactor verification on 2026-10-21

Only Grok Bot was used for live application execution. With the rebuilt installed
launcher, the original EXE and unchanged Desktop/Start Menu shortcuts each ran
the guard, received both proxy variables and loaded the native compatibility
hook. A separate data directory was verified for every entry. An incoming
ambiguous route (`NO_PROXY=*`) was rejected without creating a target process.
The vendor EXE hash stayed unchanged. The real 0.72.0→0.72.1 vendor update above
was not repeated during this refactor; same-path replacement is also covered by
unit tests. This does not constitute Claude/Codex or MSIX runtime acceptance.
All 23 baseline Claude/Codex processes retained their PIDs, executable paths
and creation times. All four saved configuration hashes and the three apps'
IFEO trees were unchanged; Claude/Codex takeover remained disabled. The final
installed launcher, native hook and settings UI matched the rebuilt bundle,
and the installed GUI smoke test passed.

Tests first failed for the missing per-app functionality, then passed after the
refactor: Windows **608 passed, 2 skipped**; the targeted suite on Linux in a
Python 3.11 container **44 passed, 1 skipped** (the Windows native hook test).
Linux results cover common preflight, per-app policy and mocked registration;
they do not demonstrate global Linux interception. macOS backend delegation is
unit-tested, but there is no Mac build or native execution evidence for this
change. The existing release workflow retains Windows/macOS/Linux build jobs.

The settings preview passed in headless Edge at 1000×780 and 760×650: three
independent controls, unsupported MSIX controls staying disabled after Save,
and unsaved-edit protection. These interactions used preview state only.
Local runtime evidence is under `build/desktop/takeover-cross-platform/`.

## References

- [Microsoft Detours](https://github.com/microsoft/Detours), v4.0.1, MIT license.
- [Windows process creation flags](https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags).
- [Official Grok Bot download](https://cursor.com/download/bot).
