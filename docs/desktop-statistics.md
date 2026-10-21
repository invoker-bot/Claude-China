# Desktop statistics

The **Statistics** tab shows recorded token usage, active sessions, identified
projects and active days. Choose today, 7, 30 or 90 days, then filter by tool and
project. The daily chart switches between tokens and sessions, with an accessible
daily table. Selecting a project in the ranking applies that project to the page.
All labels support English, Simplified Chinese and Traditional Chinese.

This feature is in the development checkout and will ship with the next desktop
release. It does not add a CLI dependency or require installing usage plugins.

## Sources and coverage

The scanner includes default homes, environment-selected homes, isolated login
homes in the CLI profiles, and archived Codex sessions. Duplicate roots and
copied request records are combined. Profiles sharing a home cannot reliably be
attributed to separate credentials, so the page groups by tool and project.

| Source | Read-only files | Available data |
| --- | --- | --- |
| Claude Code | `projects/**/*.jsonl` in Claude homes | Request usage, model, session, project, activity |
| Codex | `sessions/**/*.jsonl`, `archived_sessions/**/*.jsonl` | Response usage or advancing cumulative counters, model, session, project, activity |
| Grok CLI | `sessions/*/*/updates.jsonl`, adjacent `summary.json` | Completed-turn usage and per-model breakdown, session, project, activity |
| Grok Bot | Recognized transcript replicas in `sand-client-persistence/*.blob` | Cached local session activity; token and project details unavailable |

Grok Bot's default data directory is under `%APPDATA%/Grok Bot` on Windows,
`~/Library/Application Support/Grok Bot` on macOS, and
`${XDG_CONFIG_HOME:-~/.config}/Grok Bot` on Linux. These private formats can
change; unknown versions are reported instead of inferred. The current Bot
adapter has been checked against Windows data; native macOS/Linux Bot data
has not been verified.

The page reports retained local history, not an account-wide ledger. Deleted,
remote-only, unfinished or unsupported records can be absent. A dash means
token usage is unavailable; it is never converted to zero. Activity and project
counts can still be shown when token data is missing. Active sessions are
distinct tool/session IDs with records during the selected local-calendar days,
including independently identified background sessions. Project counts include
only identified absolute directories; a directory need not still exist.

Input includes cache reads and writes. Reasoning is a subset of output and is
not added a second time. Claude's uncached input/cache fields are normalized to
this convention. Streaming fragments of the same request retain their largest
recorded counters. Codex response IDs and advancing cumulative snapshots are
reconciled rather than added together. Inherited legacy child snapshots,
ambiguous resets and overlapping records are handled conservatively with a
coverage notice. In-progress Grok turns contribute activity, but their token
usage is unavailable until `turn_completed` arrives.
The UI deliberately does not infer subscription limits or monetary charges from
these token counts.

## Storage and refresh

Opening the tab or pressing **Refresh statistics** starts one background scan.
Other pages remain usable. During a scan, the page shows the previous completed
summary and progress; the initial scan can take minutes for large histories.
The scanner never launches, stops or restarts a provider application.

`~/.claudec/usage-v1.sqlite` contains the rebuildable local index: source file
positions/signatures, request IDs, session IDs, project paths, model names,
timestamps and numeric aggregates. It does not store prompts, responses, tool
arguments, authentication credentials or raw transcripts. SQLite's WAL mode
allows reads while a scan is running. No usage data is sent over the network.

Unchanged files are skipped. Appends resume after the last complete JSONL line;
an incomplete trailing line is retried after a later write. Changed/replaced
files are rescanned, removed files are removed from the index, and duplicate
copies remain represented until their final copy disappears. A compact daily
summary is rebuilt after changed files have been indexed, keeping UI filters
fast without rereading transcripts. Adapter version changes invalidate file
checkpoints. Malformed or oversized records have a coverage warning.

## Validation

`python -m pytest tests/test_desktop_usage.py -q` exercises native-format
fixtures, cache/input normalization, streaming and copy deduplication, both
Codex event orders, inherited child history, counter resets, date/tool/project
filters, append/rewrite/delete behavior, private-data exclusion, background
scan coordination and source locations. Fixtures never contact a provider.

Browser QA covers the English and Traditional Chinese interfaces, tool/date/
project selection, the activity chart, unknown-token/empty/error states and
desktop/narrow layouts. The committed screenshot uses preview data only.
Windows local-read validation covers real retained logs. An isolated Windows
WebView2 smoke checks the actual Python/JavaScript bridge and fixture statistics
without launching provider apps. Neither establishes native GUI acceptance on
macOS or Linux.

Related formats: [ccusage Claude source](https://ccusage.com/guide/claude/),
[Codex source](https://ccusage.com/guide/codex/),
[Grok CLI source](https://ccusage.com/guide/grok/).
