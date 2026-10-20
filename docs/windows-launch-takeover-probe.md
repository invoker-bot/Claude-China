# Windows launch takeover experiment

Status: experimental; the IFEO candidate failed the real-app compatibility gate.
It is not included in the installer or enabled by the desktop UI.
Validation date: 2026-10-21. Target: installed Grok Bot 0.72.0, conventional EXE.
Claude and Codex were excluded from execution and registration changes.

## Purpose and boundaries

Validate whether opening the original executable can enter the launcher's existing
proxy and regional checks before any target process starts. This is separate from
replacing shortcuts. Use a temporary Windows Image File Execution Options (IFEO)
Debugger registration filtered to the exact Grok Bot executable path.

The production launch mechanism is unchanged. The shared region policy was
updated separately at the user's request. This experiment does not establish
MSIX compatibility, Electron renderer/sandbox compatibility, or survival of a
real vendor upgrade. An external restart simulation is not an actual upgrade
test. A successful guarded direct launch is not a successful IFEO launch.

## Implementation

- `tools/windows_takeover_probe.py` reuses `LauncherBridge` with only Grok Bot in
  its registry. It preserves launch arguments/current directory and avoids the
  launcher's normal stop-before-restart operation. It never stops existing apps.
- Failed/unknown regional checks, invalid automatic proxy settings, changed
  settings, expired experiments, and native creation failures fail closed.
- An allowed launch uses `DEBUG_ONLY_THIS_PROCESS | CREATE_SUSPENDED`, detaches
  the debugger, and resumes the initial thread. It does not temporarily remove
  IFEO registration. It forwards inheritable IPC handles and keeps the broker
  alive until the target exits, returning the target's exit code. Both were
  locked down with failing native fixture tests before being fixed. The caller
  still sees the broker PID; the observed sandbox failure is consistent with
  this remaining process-identity mismatch.
- `tools/windows_takeover_probe_registry.ps1` needs elevation for the temporary
  HKLM registration. The broker refuses elevated target launches. The helper
  refuses an existing Grok Bot IFEO key, uses `FilterFullPath`, and rolls back
  its own registration on a stop file or timeout (maximum 15 minutes).
- Rollback checks its ownership identifier and debugger/path values; it does
  not overwrite or delete unrelated registrations. An abruptly killed helper
  requires the explicit `-RestoreOnly` recovery command below.
- Audit files contain decisions and process IDs, not environment values or
  original command-line arguments. They stay in the ignored build directory.
- A temporary, explicitly authorized `test_allow` override is supported only
  with an isolated Grok Bot profile (`SAND_USER_DATA_DIR`). It never changes
  `desktop.yaml`, and its results are marked `test_override`, not `supported`.

## Observed results

| Check | Result |
| --- | --- |
| Original installed EXE started normally | Intercepted; unknown region prevented creation of Grok Bot |
| Existing desktop shortcut | Intercepted and blocked before target execution |
| Existing Start Menu shortcut | Intercepted and blocked before target execution |
| Two external native restart attempts | Both invoked fresh checks and were blocked |
| Another executable named `Grok Bot.exe` in a different directory | Ran normally; exact-path filter did not intercept it |
| Expired broker manifest | Original application remained blocked |
| Native Windows process fixture | Reached entry point with injected marker, original working directory, spaces, embedded quote, and Unicode arguments intact |
| Guarded direct launch of real Grok Bot under the shared region policy | Passed without a test override; current exit country was JP; isolated onboarding window rendered |
| Real main process and network/GPU utility environments | Marker and HTTP_PROXY/HTTPS_PROXY matched the configured environment |
| Sandboxed renderer environment | Chromium sanitized it; does not contain the injected variables |
| IFEO launch of real Grok Bot | Failed: GPU subprocess launch error 57, followed by fatal shutdown, exit code 0x80000003 |
| Real Grok Bot self-relaunch and vendor update | Not tested |

The first blocked-entry tests used the former provider policy, which classified
Grok Bot as unknown. The user then specified a common denylist for all three
apps (CN/HK/MO/RU/IR/KP; unknown IP/location still blocks). The real launch tests
used that updated policy with strict mode enabled, not the `test_allow` override.
Both Grok Bot's user-data and data-root directories were isolated.

Logs reported `GPU process launch failed: error_code=57` and
`GPU process isn't usable. Goodbye.` Chromium defines result 57 as
`SBOX_ERROR_CANNOT_WRITE_VARIABLE_VALUE`. Together with IFEO returning the
debugger process handle instead of the requested child's handle, this is
consistent with sandbox setup targeting the wrong executable/process. Forwarding
inherited handles and waiting for the real exit code did not resolve it. No
sandbox-disabling flags were used. This candidate must not be presented as an
available global takeover mode.

After both runs, temporary IFEO registration was removed and verified absent.
The Grok executable and all existing YAML configurations retained their hashes.
All 22 baseline Claude/Codex processes were still alive with matching creation
times. Only the isolated Grok test tree was stopped.

Automated validation: `python -m pytest tests/ -q` — 563 passed, 2 skipped,
including 15 focused gate/native tests. Live reports are saved under
`build/desktop/takeover-grok-<run-id>/`; `takeover-current.txt` identifies this run.
Environment presence is distinct from proof that every Grok network request
honors proxy variables; the latter was not claimed or tested through an account.

## Reproducing and recovering the temporary registration

Create a fresh ignored build directory and `manifest.json` with:

- `run_id`: a fresh UUID without hyphens;
- `target`: absolute path to the installed `Grok Bot.exe`;
- `expires_at`: a short future Unix timestamp;
- `debugger`: Windows-quoted absolute command for `pythonw.exe`, this repository's
  `tools/windows_takeover_probe.py`, `--manifest`, the manifest path, and `--`;
- `isolated_profile`: a fresh directory in this experiment's build directory;
- `marker`: a harmless unique environment marker;
- `test_allow`: `false` unless an isolated allow test has been explicitly approved.

The Python interpreter needs the project's desktop dependencies. Inspect the
manifest and record the target hash, settings hashes, and running applications
before registration. Start the helper elevated; launch the original application
from the ordinary, non-elevated user session:

```powershell
pwsh -NoProfile -File tools/windows_takeover_probe_registry.ps1 -Manifest <absolute-manifest-path>
```

Create an empty `stop` file beside the manifest to end the experiment and restore
the original registration state. Confirm `restored.json` and that the exact IFEO
registration is absent. If the helper was interrupted, recover with:

```powershell
pwsh -NoProfile -File tools/windows_takeover_probe_registry.ps1 -Manifest <absolute-manifest-path> -RestoreOnly
```

Do not remove the experiment directory until rollback is confirmed. Do not
leave this source-based debugger registration installed as a product feature.

## References

- [Microsoft: IFEO debugger command-line and process identity semantics](https://devblogs.microsoft.com/oldnewthing/20070702-00/?p=26193/)
- [Windows process creation flags](https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags)
- [DebugActiveProcessStop](https://learn.microsoft.com/en-us/windows/win32/api/debugapi/nf-debugapi-debugactiveprocessstop)
- [Chromium Windows sandbox result codes](https://github.com/chromium/chromium/blob/main/sandbox/win/src/sandbox_types.h)
