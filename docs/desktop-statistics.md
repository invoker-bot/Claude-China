# Desktop statistics

The **Statistics** tab shows recorded token usage, active sessions, identified
projects, active days, tool calls and estimated API-equivalent token costs.
Choose today, 7, 30 or 90 days, then filter by application, exact model and
project. The daily chart switches between tokens, sessions, calls and costs, with an accessible
daily table. Selecting a project in the ranking applies that project to the page.
All labels support English, Simplified Chinese and Traditional Chinese.

Available since v0.4.3. It does not add a CLI dependency or require installing
usage plugins.

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

## Tool calls

The model/application breakdown and the **Tool call breakdown** show calls by
original name, including Bash, Read, Write, custom tools and MCP namespaces.
Search a name or select **MCP only**; these controls narrow the call ranking,
while date/application/model/project filters apply to the whole page.

Claude `tool_use` / `server_tool_use` blocks, Codex function/custom/built-in call
items, and Grok's structured `x.ai/tool` metadata are indexed by call ID.
Streaming fragments, copies and Grok status updates count once; outputs do not
add calls. Replayed Codex child calls before the child's creation are excluded;
child calls with no trustworthy creation time are excluded with a coverage notice.
Script-internal calls are not inferred from code or command arguments. A call
count means a recorded invocation, not necessarily successful completion.

Claude message models and Codex turn models identify the model making a call.
Grok's mutable session summary cannot establish historical call ownership, so
those calls appear under **Unknown model**. Grok Bot transcript caches do not
currently provide tool-call details; their call count is unavailable, not zero.

## API-equivalent costs

The offline price snapshot was checked on **2026-10-22**, using official
[OpenAI pricing](https://developers.openai.com/api/docs/pricing),
[Claude pricing](https://platform.claude.com/docs/en/about-claude/pricing) and
[Grok pricing](https://docs.x.ai/developers/pricing).
The model rate table exposes prices and links to each source. Prices are USD per
million tokens at current **Standard/global** rates, applied to all retained
history; this is not historical invoice reconstruction or a subscription bill.
Updating the app's price catalog recalculates cached aggregates without rereading
transcripts. A running app never fetches prices or uploads usage automatically.

Ordinary input = total input minus cached reads and writes. Each category is
priced separately, then output cost is added. Reasoning is already part of
output. Claude's recorded 5-minute and 1-hour cache writes use their respective
rates; missing durations assume 5 minutes for Claude and 30 minutes for OpenAI.
Per-request context thresholds apply to the whole request. GPT-5.5 uses the
largest retained request in the session to select its documented session tier.
Legacy cumulative deltas and Grok turn aggregates do not establish individual
prompt lengths; these use the short-context rate and are marked as assumptions.
Fast/priority modes, batch discounts, regional premiums, search/hosted-tool fees,
taxes and subscription charges are excluded.

Only explicitly listed model IDs and their dated snapshots match prices. Private
models, `<synthetic>`, `codex-auto-review` and unverified `grok-4.7-build` /
`grok-4.6-build` aliases remain unpriced instead of inheriting a similar name's
rate. Unknown usage/prices display a dash, while a recorded zero remains zero.
Totals are marked **Partial estimate** when some recorded usage is unpriced or
some sessions have no usage. Coverage shows priced/unpriced tokens, sessions
without usage and records using assumptions. These estimates cannot establish
account balances, quota remaining or amounts actually paid.

## Storage and refresh

Opening the tab or pressing **Refresh statistics** starts one background scan.
Other pages remain usable. During a scan, the page shows the previous completed
summary and progress; the initial scan can take minutes for large histories.
The scanner never launches, stops or restarts a provider application.

`~/.claudec/usage-v1.sqlite` contains the rebuildable local index: source file
positions/signatures, request/call IDs, session IDs, tool names, project paths, model names,
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

`python -m pytest tests/test_desktop_usage*.py -q` exercises native-format
fixtures, cache/input normalization, streaming and copy deduplication, both
Codex event orders, inherited child history, counter resets, date/tool/project
filters, append/rewrite/delete behavior, private-data exclusion, background
scan coordination and source locations, tool-call deduplication and namespaces,
price normalization, context tiers, unavailable prices, model filtering and
price-cache refresh. Fixtures never contact a provider.

Browser QA covers all three languages, application/model/date/project selection,
call search/MCP filtering, cost/call charts, unknown-price/empty/error states and
desktop/narrow layouts. The committed screenshot uses preview data only.
Windows local-read validation covers real retained logs. An isolated Windows
WebView2 smoke checks the actual Python/JavaScript bridge and fixture statistics
without launching provider apps. Neither establishes native GUI acceptance on
macOS or Linux.

Related formats: [ccusage Claude source](https://ccusage.com/guide/claude/),
[Codex source](https://ccusage.com/guide/codex/),
[Grok CLI source](https://ccusage.com/guide/grok/).
