# Desktop environment checks

Settings → **安全检查** displays the system timezone/UTC offset, language and
region. These values are read locally and are not sent to the IP service.
Windows reads the user's UI language and geographic region; macOS/Linux report
locale region settings. A locale region is not evidence of physical location.

Both **启动前检查环境** and **无法确认时也阻止启动** default to enabled,
including when loading an older desktop configuration. The switches are saved
in `~/.claudec/desktop.yaml` as `safety_check` and `safety_block_unknown`.
Existing environment variables and application paths are preserved. Manual
**检查环境** uses saved settings; unsaved edits do not change launch behavior.

## Router preflight mode

Choose **路由器模式** and save, or run
`claudec network-mode router`. To return to the prior proxy/TUN behavior, turn
the switch off or run `claudec network-mode default`. Reapply any restored
network guard when returning to a protected TUN setup. The mode does not require
a local proxy. Disable the system proxy and
restore any existing system network protection for the selected desktop app or
the **CLI / Playwright 浏览器** target before using it. Proxy variables are
removed from managed child environments, but existing saved values are retained.
For step-by-step setup, testing and recovery, see the
[路由器模式配置与测试教程](router-mode.md).

Each managed desktop, terminal-profile and `claudec` launch makes one HTTPS
request to Cloudflare and compares its observed country with the configured
region denylist. A blocked region cancels launch; a failed or invalid lookup
blocks in strict mode. Router checks still run when the ordinary region-check
switch is off. Existing desktop-app takeovers also use this launch path.

The check does not request Claude or Anthropic endpoints, send chat messages,
or perform STUN, UDP or separate DNS leak probes. Ordinary DNS resolution is
still required to connect to Cloudflare. Cloudflare sees the connecting IP;
reports stay in memory and do not include profile credentials. The lookup
does not validate Claude-specific routes, browser WebRTC or IP reputation.

On Windows, a managed Claude desktop or Claude CLI launch additionally requests
administrator authorization and installs user-scoped WFP rules for the registered
Claude installation or managed CLI and discovered local Playwright browser EXEs.
The elevation must use the same Windows account as the requesting session;
cross-account administrator credentials are rejected for runtime monitoring.
The guard waits about 10 seconds after each completed check before starting the
next; a probe may take up to 12 seconds before it is treated as unknown. A blocked
region or an unknown country result in strict mode removes the temporary
network permits. An IP change within an allowed region does not trigger it. A crash of the
monitor also removes those permits. The persistent deny remains in place for
registered programs, including already-established connections, and a warning
is displayed; the program and its session are not terminated. Normal session
exit removes the guard, and **安全检查 → 还原网络防护** removes it after a
failure. Administrator authorization is needed again when restoring a failed
guard. The uninstaller restores both router targets before it removes the app.

Checks are periodic, not an instantaneous router kill switch: traffic can leave
before a failure is detected, and actual timing can vary with system load. If
unknown results are allowed, an unobservable failure alone does not trigger a
block. The check uses launcher-side probes, not traffic inspection inside Claude
or the browser; it cannot guarantee provider availability or detect every split
route. The guard is tied to registered executable paths and the Windows user,
not a full process tree: other invocations of a registered browser EXE are also
affected, while new versions, arbitrary shell tools, external launchers, remote
or container browsers, and system DNS are not covered. TCP loopback remains
available for local control; a separate local relay could therefore carry
traffic onward. Restart a managed session after updating its browser or CLI so
its paths are registered again. Codex and Grok retain startup checks only.
Claude runtime protection is currently Windows-only; its managed router-mode
launches on other platforms are rejected instead of claiming this protection.

Manual **检查环境** queries the country service and reports local proxy mode,
Chrome/Edge policy state and IPv6 default route. It does not probe UDP, STUN or
DNS leaks and does not run WebRTC inside the target app. On Windows, **启用网络防护** keeps WebRTC enabled
and installs a per-user WFP allowlist for the selected installation's EXEs:
only TCP to the pinned HTTP proxy IP/port is permitted; direct TCP, UDP and
IPv6 bypasses are blocked. A disconnected proxy never permits direct fallback.
The guarded launch path verifies the actual filters and endpoint independently
of the regional-check switches. Both activation and **还原网络防护** use Windows
administrator authorization, with read-only verification remaining unelevated.

Select **指定 TUN 隧道（支持 WebRTC UDP）** for TCP/UDP through a chosen
connected adapter instead of an HTTP proxy. The proxy client manages its TUN
routes and DNS. WFP pins the interface identity and source addresses for IPv4
and IPv6, and packet-layer source guards block fallback through another NIC,
including established UDP flows. The source guards also affect other processes
sending from the same tunnel addresses. Adapter changes require reapplying
protection; another tunnel is never selected automatically.

**CLI / Playwright 浏览器** protects discovered cache EXEs and explicitly listed
browser/helper paths. `claudec` and managed desktop terminals additionally load
a pre-spawn check into Playwright's Node driver: unregistered versions are
rejected before browser creation, and real rules/tunnel state are verified
without elevation. Standard local Node/Python bindings are covered. External
launchers require the same environment integration; remote and WSL/container
browsers are outside these Windows rules. Restart existing CLI/browser
processes after switching/restoring modes to refresh their launch options.

In TUN mode, **同时保护 CLI 自身网络** also registers installed CLI binaries
and uses a private copy of Node for managed CLI wrappers, so unrelated Node
programs are not restricted. Managed launches reject unregistered CLI binaries
before execution and bypass HTTP proxy environment variables; local proxy or
localhost API endpoints may therefore stop working in this mode. Reapply after
installing or changing a CLI, its Node runtime or Grok profile home. The WFP
rule also affects other invocations of the same registered native CLI EXE for
this user. Shell tools, system DNS services, external launchers and remote,
WSL or container processes are not protected as a process tree. Restoring the
CLI / Playwright target removes both browser and CLI rules.

Rules and restore metadata are committed atomically in WFP and persist after
the launcher exits. Restore works with the proxy off or the app removed, and
does not touch another app's rules. Windows uninstallation restores owned
network protection before deleting the launcher. Existing browser-policy repair
records remain available for restoration; no new browser restriction is written.
See the [README section](../README.md#environment-check-and-webrtc-repair) for
proxy formats, executable-path update boundaries and shared-runtime/DNS limits.

Every launch/restart runs a fresh check before stopping the existing app.
Regions in the shared denylist block launching. Unknown results also block in
strict mode: network failure, invalid geolocation, and ambiguous proxy routing
cannot authorize a launch. Disabling strict mode permits unknown results but
continues blocking regions in the denylist.
Turning off the master switch disables automatic region queries and region blocking.
It does not disable an installed system network guard; use its restore button.
The earlier system-proxy and automatic-proxy-variable checks still apply.

## What is checked

The check makes a TLS-verified HTTPS request to
[Cloudflare trace](https://www.cloudflare.com/cdn-cgi/trace) for the connection's public IP and country code. It does not send
credentials, local environment details or the entire launch environment.
Proxy authentication is used only for the HTTP CONNECT hop. Results are kept
in the current UI session and are not written to config or logs. No request
is sent merely by opening the settings panel.

The checker compares effective launch proxy variables with the OS's static
HTTPS proxy settings. It refuses unsupported proxy formats, PAC/automatic
proxy configuration, conflicting endpoints, and exclusions that could route
known service domains differently. Local/private network exclusions and
unrelated domain exclusions are allowed. Equivalent local host spellings such
as `localhost` and `127.0.0.1` are each probed and must report the same IP/region.
Windows/macOS brokered launches cannot rely on custom environment variables
without a corresponding system proxy. Failed proxy requests never fall back
to a direct connection. In TUN mode, managed CLI and protected desktop checks bind the query to the
selected tunnel address and check the adapter before and after the request.
TUN firewall rules continue independently of the country check; unlike Claude
router mode, TUN mode does not continuously monitor the country. Each network
operation has an 8-second socket timeout;
responses are capped at 16 KiB and redirects are refused.

This checks the configured region policy, **not official provider eligibility or account safety**. A
proxy exit does not prove the user's physical location, residency or eligibility.
It does not evaluate account history, IP reputation, legal/organization
eligibility, DNS-based application split routing, or the app's own network
configuration. By default it guards starts requested through this launcher.
On Windows, enabling [original-entry takeover](windows-launch-takeover.md)
for a supported fixed-path EXE also checks that application's original EXE,
shortcuts and same-path update restarts. Each app has a separate opt-in control;
MSIX and versioned installation paths are currently unsupported.
That opt-in feature registers a Windows launch filter; it does not change the
system proxy or the user's global environment variables. Other applications'
external entries are unaffected.

## Shared region policy

On 2026-10-21 the user requested one common rule for Claude, Codex and Grok Bot:

| Code | Region blocked |
| --- | --- |
| CN | Mainland China |
| HK | Hong Kong |
| MO | Macao |
| RU | Russia |
| IR | Iran |
| KP | North Korea |

All other recognized ISO country/territory codes pass this configured rule.
Missing/invalid codes and failed network queries remain unknown and fail closed
in strict mode. No additional countries were inferred from the user's “etc.”.
The shared list lives in `src/claude_china/desktop/regions.py` and is also returned
to the settings UI; displayed policy and enforcement use the same source.

This replaces the former provider-specific allowlists and their 90-day expiry.
A user-configured denylist is not an official support snapshot, so it does not
expire as if it were one. Grok Bot no longer fails solely because an official
country list is unavailable. The UI describes a successful result as passing
the region rule. Its optional official-service links are informational, not
the source or an endorsement of this user-requested rule.

## Verification

- `python -m pytest tests/test_desktop_safety.py tests/test_desktop_safety_platforms.py -q`
  covers the shared rules, strict/disabled modes, transport failures, credentials,
  proxy routing and preserving a running app when preflight fails.
- `python -m pytest tests/ -q` covers existing launcher/configuration behavior.
- The packaged GUI smoke checks the category, saved/default switches, draft
  preservation/cancellation, persistence and a deterministic blocked-result
  display. It makes no IP request and does not start/stop user applications.
- Browser preview data is synthetic and labeled as a preview; it is not live
  evidence of the user's current IP or eligibility.
