# Third-party references: Claude account-safety projects

These repositories are **read-only reference material**, tracked as git submodules
so their upstream history can be updated deliberately. They are not part of this
project's build, packaging or runtime, and nothing here is imported by
`claude_china`.

> Scope and limits: they are third-party projects with their own licenses and
> quality; listing them is not an endorsement. Avoiding geographic restrictions
> can conflict with the provider's terms of service, and **no tool can guarantee
> that an account will not be suspended**. Do not hand account credentials,
> session cookies, API keys or full proxy subscriptions to any of these tools.
> Evaluate them yourself before running scripts on your machine.

## Included

| Directory | Upstream | License | Stars* | Pinned |
| --- | --- | --- | ---: | --- |
| [check-cc](check-cc) | [yacuo/check-cc](https://github.com/yacuo/check-cc) | MIT | 2.2k | `078e7ba` (v1.1.1-4) |
| [claude-guardian](claude-guardian) | [DUNHKpcc/Claude-Guardian](https://github.com/DUNHKpcc/Claude-Guardian) | GPL-3.0-only | 1.0k | `efa8c6d` (main) |
| [claude-ip-guard](claude-ip-guard) | [cso1z/claude-ip-guard](https://github.com/cso1z/claude-ip-guard) | MIT | 220 | `295c9c4` (v1.2.0-1) |

\* Stars on 2026-10-27; they change. Pins are the commits recorded by
`git submodule status` when this index was written.

### check-cc — browser-side environment fingerprinting

Next.js/TypeScript app (deployable, also hosted at checkcc.org) that samples the
browser **before** signing in and scores how self-consistent the environment is:

- timezone, UTC offset and DST behaviour, `Intl` locale, `navigator.languages`,
  Simplified/Traditional Chinese variant, User-Agent / UA client hints, device
  and OS hints, WebView/automation traces, and OS-specific emoji rendering;
- plugin per signal (`src/detection/plugins/`), weighted against region profiles
  (`src/regions/`), producing a 0–100 score where ≥70 is treated as
  `restricted`;
- everything runs locally by default; no Claude login, cookies or chat data are
  read.

Useful as a catalogue of "what a browser leaks about where it thinks it is",
and as a contrast to this project's machine-level network check.

### claude-guardian — environment hardening playbook + measurement scripts

A Codex/agent "skill" with Python 3.10+ scripts and a large reference library:

- `network_check.py` measures route/TUN, IPv4 exit, IPv6, DNS leakage and UDP
  (STUN) without ever contacting Claude/Anthropic; exit IPs stay in memory and
  reports show country/ASN/mismatch instead;
- `stun_probe.py` is a strict RFC 8489 STUN parser; `egress_verifier.py` judges
  eight required layers (`tun`, core IPv6, DNS, rules, IPv4 exit, IPv6 probe,
  WebRTC, failure drill) as `established` / `violated` / `incomplete`;
- `traffic_policy.py` states a fixed `IPv4_ONLY`, fail-closed, no-direct-fallback
  policy for the whole machine;
- repair/recovery tooling records original values and rolls back; changes are
  authorised in tiers (read-only, plan-approved, on-the-spot confirmation);
- guidance for VM/VPS isolation, fail-closed firewalls, account warm-up rhythm,
  ban appeals and cleaning old environment traces.

This is the closest match to the "diagnose, then reversibly repair" model used
here — including a WebRTC test page served on loopback.

### claude-ip-guard — runtime guard for Claude Code

A shell + Python Claude Code hook plugin:

- installs `SessionStart` and `UserPromptSubmit` hooks; before a prompt it checks
  direct reachability of `api.anthropic.com` (a 403 means the IP is refused) and
  looks up the current exit country;
- blocks on a configured denylist (CN, RU, KP, IR, SY, CU, BY, …);
- keeps a 30-day history of distinct IPs and **soft-blocks new IPs** with a
  graded warning (2–3 = notice, 4–6 = warning, ≥7 = severe); resending the same
  prompt continues;
- skips itself when `ANTHROPIC_BASE_URL` points at a third-party relay, and
  fails open when the network check itself fails;
- caches by IP for 10 minutes to avoid a request per prompt.

It is the runtime counterpart to a pre-flight check: cheap, fail-open, and
explicit about "frequent IP changes are themselves a risk signal".

## Common patterns

1. **Consistency beats individual signals.** Country, timezone, locale, language
   and device fingerprint must agree; a mismatch is the risk, not any one value.
2. **One stable egress.** Prefer a single long-lived exit (residential/native IP,
   or a full-tunnel TUN) over switching nodes, and avoid "browser proxied, CLI
   direct" splits.
3. **Close the bypasses.** IPv6, DNS, UDP/STUN/WebRTC and proxy-failure fallback
   are the usual holes; the better projects make failure **fail-closed**.
4. **Measure, then change.** Record evidence first, keep IPs out of shared
   reports, and make every change reversible with an explicit rollback.
5. **Guard at runtime where possible.** A hook or launcher check can stop a
   request before it leaves; post-hoc account recovery is much harder.
6. **Isolate and stay boring.** Separate VM/VPS or device, stable fingerprint,
   gradual plan upgrades, consistent payment/email story, and cleanup of old
   environment traces after a suspension.
7. **State the boundary.** No project can guarantee immunity; several explicitly
   refuse purchased accounts, KYC bypass, top-ups or credential handling.

## Working with the submodules

```bash
# after cloning this repository
git submodule update --init --recursive

# inspect the pinned commits
git submodule status

# update one reference on purpose
git submodule update --remote --merge docs/refs/check-cc

# or update all and review the diff before committing
git submodule update --remote --merge
git diff --submodule=log
```

A submodule pin is part of this repository's history: update it in its own
commit so the reviewed upstream state stays reproducible. `check-cc` and
`claude-ip-guard` are MIT; `claude-guardian` is GPL-3.0-only. Do not copy code
from these trees into this MIT project without checking the license first.
