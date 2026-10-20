# Grok Bot original-entry takeover on Windows

The Windows x64 installer supports opt-in takeover of **Grok Bot only**. Open
Settings → Grok Bot → **接管原入口** and enable it after saving any setting
changes. Windows requests administrator authorization to register the launch
filter. The launcher and Grok still run as the normal user afterwards.

Once enabled, opening the original `Grok Bot.exe`, Desktop/Start Menu shortcuts,
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

- The 64-bit IFEO key for `Grok Bot.exe` contains an exact `FilterFullPath` and
  an ownership marker. Registration refuses existing foreign configuration.
  Removal preserves unrelated values and filters. No Claude or Codex registry
  keys or shortcuts are touched.
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
- `~/.claudec/takeover/grok-bot.json` stores paths and registration ownership.
  The adjacent `logs/` directory retains at most 50 launch decisions with
  timestamps, PIDs and safe error text; it omits IP addresses and environment
  values. Configuration remains in the existing `~/.claudec/desktop.yaml`.

This is a launch guard for normal application entries, not an OS security
boundary against a user deliberately bypassing it. An administrator can remove
the filter, and a different executable path is outside its scope. It does not
prove provider eligibility or that every network request obeys the app's proxy
environment. MSIX applications, other apps and other operating systems have not
been enabled by this implementation.

## Verification on 2026-10-21

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

## References

- [Microsoft Detours](https://github.com/microsoft/Detours), v4.0.1, MIT license.
- [Windows process creation flags](https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags).
- [Official Grok Bot download](https://cursor.com/download/bot).
