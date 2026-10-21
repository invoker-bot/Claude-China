# Launch takeover: supported paths and remaining work

The requirement is to run a fresh environment check and rebuild process-local
variables before a vendor application starts, including its original entry
and updater restart. A shortcut wrapper alone does not meet that requirement.
The launcher must not report an installation as protected when a native entry
or a new version can bypass the guard.

| Installation | Original entry and restart coverage | Current status |
| --- | --- | --- |
| Windows x64, fixed-path EXE | Exact registered image path, including replacement at the same path | Independent Claude/Codex/Grok registrations implemented; only real Grok tested |
| Windows MSIX | Package activation and changing package version paths | Not implemented; UI refuses enabling |
| Windows versioned `app-<version>` directory | New version uses a different image path | Not implemented; UI refuses enabling |
| macOS signed `.app` | Finder/LaunchServices, direct execution and updater relaunch | No native interceptor; control disabled |
| Linux | Desktop entry, direct executable and package/updater relaunch | No native interceptor; control disabled |

All three platform backends can supply proxy information to the common
preflight, which applies only the selected app's settings. It reloads saved
configuration for each main-process start and restores old overwritten values
before applying new ones. It never stops or launches a process while evaluating
policy. Normal launches from the desktop launcher retain their existing
platform behavior; this common code is not itself a global hook.

## Windows package activation

The local Claude and Codex apps use MSIX. A fixed absolute IFEO filter cannot
be assumed to cover a new package directory. The OS activation context also
matters for their child processes. A background watcher that repairs a filter
after an update has a gap before repair; it is not strict restart protection.

Microsoft's
[IPackageDebugSettings::EnableDebugging](https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nf-shobjidl_core-ipackagedebugsettings-enabledebugging)
accepts a package full name, debugger command and environment. It also changes
package lifecycle behavior. It is an investigation path, not an implemented
solution here. A complete backend still needs package-identity-preserving
preflight/injection, a guarantee across version replacement, reversible
registration and isolated packaged-app validation before opt-in use.

No debug mode, IFEO filter, shortcut rewrite or relaunch has been applied to
the real local Claude/Codex applications. Registry ownership tests use an
in-memory fake; those tests cannot establish MSIX activation correctness.

## macOS

[Endpoint Security](https://developer.apple.com/documentation/endpointsecurity)
provides authorization of pending process events. A native client requires the
restricted
[Endpoint Security entitlement](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.developer.endpoint-security.client).
This is separate from ordinary Developer ID signing/notarization.

Authorization alone is not an implementation of environment replacement. The
design still needs to preserve LaunchServices behavior, signed application
integrity, argv, updater relaunch semantics and failure reporting. This change
does not rewrite vendor bundles or weaken signing settings. There is currently
no available Mac for compilation/native verification, and no confirmed Endpoint
Security entitlement. Both native implementation and acceptance remain open.

## Linux

Changing `.desktop` files does not cover direct binary execution or every
updater. A future privileged native guard needs to account for executable
replacement, session/user boundaries, argv/environment propagation and helper
processes. Distribution packages, AppImages, Flatpak and Snap must be assessed
separately instead of claiming that a generic wrapper covers all formats.

Linux [fanotify](https://man7.org/linux/man-pages/man7/fanotify.7.html) permission
events can mediate access, but notifications alone are not interception, and an
access decision is not environment injection. No privileged fanotify service
has been shipped or installed here. Container unit tests verify Python logic
only; desktop and updater acceptance remains open.

## Acceptance before enabling any new native backend

Use isolated fixtures first, then the explicitly permitted vendor app. Verify
that rejected/unknown checks run before vendor code, that a fresh main restart
reloads settings, and that helper processes preserve handles/PIDs and sandbox
behavior. Exercise a real version replacement and its immediate automatic
restart, restoration/uninstall and missing-guard failures. Verify other apps'
registrations, running processes and saved configuration are unchanged.
