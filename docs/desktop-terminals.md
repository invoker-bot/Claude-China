# Desktop terminals

The **我的终端** workspace shares CLI profiles with `claudec`; it does not
install the underlying AI CLIs or change their global entry points. Grok CLI
profiles are separate from the Grok Bot desktop application.

## Configuration

- `~/.claudec/config.yaml`: shared profile records (name, tool, authentication,
  endpoint, proxy, default argument list). Save publishes a complete YAML file
  atomically. Unrelated profiles and extension fields are preserved.
- `~/.claudec/desktop.yaml`: last project directory/profile, up to 20 recent
  directories and 50 favorites under `terminals`. Existing common/app/safety
  settings and terminal extension fields are kept. Removing a favorite only
  removes the bookmark, including when its directory no longer exists.
- `~/.claudec/terminal-jobs/`: short-lived, single-use launch requests containing
  only profile name, directory, expiry and an optional session ID. No credentials
  or environment are serialized here. The worker consumes and deletes its
  request before launching.

Editing, copying and deleting use a record revision to reject stale forms after
an external CLI edit. This is optimistic conflict detection, not a cross-process
transaction lock. Delete removes only the profile entry. Blank API keys preserve
the current value on edits of the same tool/authentication mode; changing either
requires new credentials. The page receives only a `has_secret` flag.

## History and project shortcuts

The workspace has **历史会话**, **常用项目**, and **CLI 配置** views. Choose a
profile above the list to read that profile's CLI history. Search matches the
session title, project path, or session ID. **继续会话** resumes that exact
conversation in its saved project directory. **选用目录** selects the project
without starting anything; **新建会话** starts a fresh conversation using the
selected profile. Star a directory to keep it at the top of **常用项目**.

History includes sessions created outside Claude China. API profiles use the
CLI's default home (`~/.claude`, `~/.codex`, or `~/.grok`); login profiles use their
isolated `credentials_path`, matching the environment built for launch. Profiles
sharing the same home intentionally share history. Listing never starts a CLI,
queries a provider, creates a credentials directory, or imports transcripts into
`~/.claudec`. Only IDs, short titles, project directories and activity times are
returned to the UI. A first prompt/summary can supply a missing title.

Local format adapters read Claude's project JSONL/index files, Codex's session
metadata and name index, and Grok's session summaries and working-directory
mapping. Codex background/subagent records and Claude sidechain records are
excluded. Parsing is bounded, tolerates partially written records, and skips
broken files with a notice. The list shows up to 200 recent sessions from the
newest 5,000 candidate files; it indicates when this limit is reached. Removed
project directories remain visible with launch actions disabled. Native file
formats may change between CLI versions; unsupported records are not guessed.

Resume uses the provider's documented command:

- [Claude Code](https://code.claude.com/docs/en/cli-reference): `claude --resume ID`.
- [Codex CLI](https://developers.openai.com/codex/cli/reference/): `codex resume ID`.
- [Grok CLI](https://docs.x.ai/build/features/sessions): `grok --resume ID`.

The terminal worker reloads the profile and verifies that the selected ID still
exists in its history home and still belongs to the selected project. It then
repeats the normal proxy/safety/environment preparation. Default arguments that
would override the session or directory are rejected instead of silently
resuming elsewhere. Resume never requests source-code restoration or a fork.
New-session actions also reject resume defaults so their behavior stays clear.

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

When **CLI / Playwright 浏览器** network protection is enabled, Windows managed
terminals and `claudec` propagate a Playwright Node-driver preload via
`NODE_OPTIONS`, preserving unrelated Node options. Registered browser EXEs are
protected persistently by WFP; a new browser version/custom executable is
blocked before creation until registered. TUN mode requires the selected
tunnel, allows its WebRTC UDP, and rejects direct fallback when disconnected.
Browser children bypass ambient HTTP proxies in this mode while the CLI's API
proxy remains unchanged. Restore removes the owned filters and disables the
launch check; restart existing CLI/browser processes to refresh options, and
close managed terminals before uninstalling. See the
[network protection guide](desktop-safety.md) for scope and limitations.

## Verification

Unit coverage includes profile CRUD and stale revisions, credential redaction
and preservation, atomic write failure, argument handling, system proxy and
strict safety failures, launch-request replay/expiry, and platform dispatch.
History coverage includes all three native formats, login-home isolation,
partial records, missing directories, bounds/sorting, canonical directory
matching, favorites, and exact resume arguments. A real isolated fake CLI
process verifies the worker's resume ID, working directory, and environment.
Packaged GUI smoke exercises the native bridge and profile CRUD against
temporary CLI and desktop configurations without starting provider CLIs. It
also creates a fixture history record, saves a favorite, and verifies separate
resume/new-session requests through the native bridge using a fake terminal.
Smoke history homes and launch requests are isolated from real user data.
Windows native terminal verification uses an isolated home and a fake CLI to
check working directory, literal arguments and environment. Linux/macOS dispatch
tests do not establish native terminal integration on those operating systems;
release acceptance still requires testing their actual desktop terminals.
