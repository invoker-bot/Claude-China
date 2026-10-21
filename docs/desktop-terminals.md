# Desktop terminals

The **我的终端** workspace shares CLI profiles with `claudec`; it does not
install the underlying AI CLIs or change their global entry points. Grok CLI
profiles are separate from the Grok Bot desktop application.

## Configuration

- `~/.claudec/config.yaml`: shared profile records (name, tool, authentication,
  endpoint, proxy, default argument list). Save publishes a complete YAML file
  atomically. Unrelated profiles and extension fields are preserved.
- `~/.claudec/desktop.yaml`: last project directory and up to eight recent
  directories under `terminals`. Existing common/app/safety settings are kept.
- `~/.claudec/terminal-jobs/`: short-lived, single-use launch requests containing
  only profile name, directory and expiry. No credentials or environment are
  serialized here. The worker consumes and deletes its request before launching.

Editing, copying and deleting use a record revision to reject stale forms after
an external CLI edit. This is optimistic conflict detection, not a cross-process
transaction lock. Delete removes only the profile entry. Blank API keys preserve
the current value on edits of the same tool/authentication mode; changing either
requires new credentials. The page receives only a `has_secret` flag.

## Launch behavior

The launcher validates the project directory and prepares the selected profile
using the core CLI environment builder. It clears managed provider/proxy/home
variables inherited from other profiles, applies the selected profile, and uses
the common desktop environment for unrelated variables. Per-desktop-app
overrides do not apply to CLI profiles. A profile proxy overrides the automatic
proxy, but enabling automatic proxy still requires a valid system HTTP endpoint.

Proxy and safety checks happen before opening a profile terminal, and again in
the terminal worker using freshly read settings. Unknown regions fail under
strict mode. A settings change during a check cancels that attempt. The worker
runs the CLI with an argument list and an explicit environment; it never
evaluates profile arguments as shell source. An ordinary terminal skips profile
preparation and provider checks.

Windows launches PowerShell with a credential-free encoded bootstrap and a
console-attached packaged worker. Known npm shims resolve to their package's
Node or native entry point, avoiding `cmd.exe` expansion of `%` and `&` in user
arguments. Unrecognized shims fail with an installation error. macOS sends a
quoted bootstrap to Terminal using a fixed AppleScript and argument data.
Linux passes the directory and helper as separate terminal arguments. The
interactive shell remains after the CLI returns; its later commands do not
inherit the profile environment of the worker's child.

## Verification

Unit coverage includes profile CRUD and stale revisions, credential redaction
and preservation, atomic write failure, argument handling, system proxy and
strict safety failures, launch-request replay/expiry, and platform dispatch.
Packaged GUI smoke exercises the native bridge and profile CRUD against
temporary CLI and desktop configurations without starting provider CLIs.
Windows native terminal verification uses an isolated home and a fake CLI to
check working directory, literal arguments and environment. Linux/macOS dispatch
tests do not establish native terminal integration on those operating systems;
release acceptance still requires testing their actual desktop terminals.
