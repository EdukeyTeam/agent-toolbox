# Owning-agent collection and monitoring

Normal analysis is offline. An owning agent can export numeric data that another host cannot access, but authentication and protected content remain in that host. Do not invent an endpoint or scrape cookies.

## Claude and AGY snapshots

Capture a native statusline JSON observation using the owning agent's existing supported integration. Import it with the snapshot command:

```bash
python3 scripts/agent_usage.py snapshot --agent claude --input /path/to/statusline.json --store /path/to/analytics.sqlite --out /path/to/reports/latest
```

The numeric projection reads `rate_limits.five_hour`/`seven_day`, their utilization/reset fields, and `context_window.current_usage`/capacity when present. It excludes all other raw fields. Immediately after compaction the current usage may be null. See [Claude statusline](https://code.claude.com/docs/en/statusline). An existing user's statusline should be extended rather than replaced; hook installation is a separate user-authorized action.

For a detailed native breakdown, use `/context` or `/context all` inside the owning interactive Claude session. Ask that agent to export only the observed totals and category/skill sizes using the normalized context contract. Slash commands are not shell executables. Keep `~300` and `<20` entries as estimates/bounds rather than exact counts; catalog descriptions, deferred schemas and loaded skill bodies are different categories. Screenshots alone cannot supply exact machine-readable counters.

For AGY, pass an explicit documented JSON/stream export as `--source agy=FILE`. Native quota/context snapshots can be imported through `snapshot --agent agy` when they expose compatible fields. See [AGY headless](https://antigravity.google/docs/cli/headless/). Repeated cumulative result objects are not independent requests. Cache semantics vary by source/model; ambiguous input accounting remains unavailable for exact pricing.

## Codex account quotas

```bash
python3 scripts/agent_usage.py capture-codex --store /path/to/analytics.sqlite --out /path/to/reports/quota
```

This starts the already authenticated Codex app-server and issues initialization plus `account/rateLimits/read`, then closes the child process. It requests no model turn, reads no credentials itself and prints no provider raw errors. Availability depends on CLI version and authentication. [App-server documentation](https://learn.chatgpt.com/docs/app-server) describes the supported interface. Historical quota samples can also occur inside local rollout `rate_limits` events.

The documented account `account/usage/read` capability can supply separate account summaries/daily activity when available in the owning host. Keep those summaries as account-scope reconciliation evidence, not additional local request rows. API-organization usage is different from consumer subscription activity.

## Copilot-hosted tools

If the owning Copilot session has a session-store SQL tool, inspect that tool's actual schema and dialect. The supplied example uses DuckDB with `created_at` partition pruning on absolute UTC literals. Bound event scans by a known session set. Export request IDs, timestamps, model/counter fields and source metadata only; omit user messages, assistant content and tool arguments/results. Import them through the normalized contract. If the hosted tool is absent, use local files/SQL and state that cloud coverage is missing. Do not promise a generic hosted SQL endpoint.

## Automation and interpretation

Run `collect` repeatedly with explicit source paths and the same analytics ledger. It upserts stable numeric identities, retaining already collected observations if sources rotate or disappear. Repeated imports do not increase counts. The analytics ledger is user-owned local state and is never the provider database.

An existing scheduler can run that same short command at a user-selected cadence. Collection frequency controls observation resolution; it does not recover snapshots from before monitoring began. Do not create a scheduler or background service implicitly. Prevent overlapping heavy scans when scheduling a large history; the ledger supports transactional concurrent writes, but source parsing still costs time.

Reports expose local five-hour/seven-day processed usage and the provider's actual quota buckets separately. Not every plan has a five-hour limit. Cloud work and other devices may consume the same allowance. Reset times can change and provider accounting may arrive late.

Experimental calibration requires `--complete-coverage`, five compatible samples spanning at least five percentage points in one account/bucket/reset, monotone utilization and a stable model/speed mix. Aging activity invalidates a rolling-window interval. An eligible ratio describes only that observed interval; it does not recover the provider's undisclosed weighting or a universal token allowance. Keep API-equivalent dollars and tokens per point labeled empirical, and use the recorded observations when the conditions fail.
