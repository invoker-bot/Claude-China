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

Every launch/restart runs a fresh check before stopping the existing app.
Unsupported regions block launching. Unknown results also block in strict mode:
network failure, invalid geolocation, ambiguous proxy routing, expired rules,
and missing provider rules cannot authorize a launch. Disabling strict mode
permits unknown results but continues blocking known unsupported regions.
Turning off the master switch disables automatic queries and this guard.
The earlier system-proxy and automatic-proxy-variable checks still apply.

## What is checked

The check makes a TLS-verified HTTPS request to [ipwho.is](https://ipwhois.io/documentation)
for the connection's public IP and coarse geographic region. It does not send
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
to a direct connection. Each network operation has an 8-second socket timeout;
responses are capped at 16 KiB and redirects are refused.

This is a regional support check, **not a guarantee of account safety**. A
proxy exit does not prove the user's physical location, residency or eligibility.
It does not evaluate account history, IP reputation, legal/organization
eligibility, DNS-based application split routing, or the app's own network
configuration. It only guards starts requested through this launcher; it does
not change system settings or block opening an app elsewhere.

## Rule provenance and maintenance

Country snapshots in `src/claude_china/desktop/regions.py` were reviewed on
2026-10-21:

| App | Official reference | Check behavior |
| --- | --- | --- |
| Claude | [Where can I access Claude?](https://support.claude.com/en/articles/8461763-where-can-i-access-claude) | Current consumer service country list |
| Codex | [ChatGPT Supported Countries](https://help.openai.com/en/articles/7947663-chatgpt-supported-countries) | Reference for Codex with a ChatGPT account; not a verification of API-account eligibility |
| Grok Bot | [Grok Bot overview](https://docs.x.ai/grok-bot/overview) | No verifiable complete product-specific geographic list was found; report unknown |

The Claude list's duplicate Bosnia/Herzegovina entries are deduplicated and
“Mariana Islands” is mapped to MP. The newer Anthropic legal page with an
effective date of 2026-11-12 was not applied ahead of its effective date.
Ukraine is conservatively unknown because country-level geolocation cannot
resolve subregional restrictions. Grok-on-X availability is not used as a
substitute for a Grok Bot policy.

Snapshots expire after 90 days; a system date before their review date also
produces unknown. Maintainers must recheck official sources, update the ISO
code sets and `REVIEWED_ON`, and run the regional tests when shipping new rules.
The UI links to the official source and shows the rule review date. The source
is evidence for the regional list, not a claim that timezone/language determine
whether a provider will suspend an account.

## Verification

- `python -m pytest tests/test_desktop_safety.py tests/test_desktop_safety_platforms.py -q`
  covers provider rules, strict/disabled modes, transport failures, credentials,
  proxy routing and preserving a running app when preflight fails.
- `python -m pytest tests/ -q` covers existing launcher/configuration behavior.
- The packaged GUI smoke checks the category, saved/default switches, draft
  preservation/cancellation, persistence and a deterministic blocked-result
  display. It makes no IP request and does not start/stop user applications.
- Browser preview data is synthetic and labeled as a preview; it is not live
  evidence of the user's current IP or eligibility.
