# Numeric interchange and rate cards

`import --input FILE --store LEDGER --out REPORT_DIR` accepts an object with `schema_version: 1` and lists named `usage`, `contexts`, `tools`, `quotas`, `sessions`, `sources`, `warnings`. Omitted lists are empty. Unknown fields, including raw content fields, are discarded. Invalid counts, percentages and naive timestamps are rejected. Preserve stable identities across repeated exports.

Usage fields: `id`, `agent`, `session_id`, optional `parent_session_id`, `model`, aware UTC `timestamp`, `source_id`, `origin`, `device`, `account`, `request_count`, `unit`, `quality`, `input_tokens`, `cache_read_tokens`, `cache_write_tokens`, `cache_write_5m_tokens`, `cache_write_1h_tokens`, `output_tokens`, `reasoning_tokens`, `speed`, `service_tier`, `inference_geo`. Input is the total prompt including both cache components; reasoning is an output subset. Missing counts are null. A session/turn aggregate uses its actual `unit` and cannot masquerade as a request when prompt tiers are unknown.

Example synthetic usage record:

```json
{"id":"sample-request","agent":"claude","session_id":"sample-session","model":"claude-sonnet-5-5","timestamp":"2026-10-01T12:00:00Z","input_tokens":25000,"cache_read_tokens":20000,"cache_write_tokens":4000,"cache_write_5m_tokens":4000,"cache_write_1h_tokens":0,"output_tokens":500,"reasoning_tokens":null,"request_count":1,"unit":"request","quality":"reported","origin":"imported"}
```

Context observations use `session_id`, `agent`, `observed_at`, `used_tokens`, `window_tokens`, `basis`, `provider_percent`, `compactions`, `retention_status`, and `categories` containing `name`, `characters`, `estimated_tokens`, `lower_tokens`, `upper_tokens`, `quality`. Do not include content. A measured native category may be supplied as reported; locally reconstructed categories remain estimates. Unknown used/capacity is null, never zero. A negative `unattributed_tokens` residual signals estimator overrun.

Quota observations use `id`, `agent`, `account`, `bucket`, `window_minutes`, `resets_at`, `used_percent`, `observed_at`, `origin` and `source_id`. All timestamps are aware ISO-8601 values; aliases identify accounts without exposing real account IDs.

Tool/skill observations contain stable invocation identity, session/time/source, safe `name`, `kind` (`tool` or `skill`), `argument_chars` and `result_chars`. These are visible-content proxies. They are not request charges, and no logged command is executed.

## Price updates

The independent `assets/pricing.json` card has a version, verification date, currency USD, official source links, exact model entries and explicit aliases. Supply another card using `--rates`. Report JSON embeds the model entries and aliases actually used, alongside their provenance, so subsequent card updates do not erase the calculation inputs. Preserve previous complete cards separately when needed. Current reference rates do not prove what a historical request would actually have been billed.

Each model entry contains prices per million tokens: `input`, `output`, `cache_read`, `cache_write_5m`, `cache_write_1h`. An absent independent cache-write charge is represented by zero, meaning ordinary input treatment. `tiers` select request-specific rates above an inclusive-input threshold. `effective_from`/`effective_until` can select verified historical versions; an entry can be a list of effective variants. Optional `alternate_rates` yields a range when a known prompt tier cannot be established. Speed multipliers and geography are applied per observation before grouping.

Refresh official [OpenAI pricing](https://developers.openai.com/api/docs/pricing) and [Claude pricing](https://platform.claude.com/docs/en/about-claude/pricing), preserving exact model and cache semantics. Never alias a newer model to an older one because the names look similar. Unknown models are unpriced. The bundled OpenAI short/long rates currently produce a range because the verification did not establish their threshold; supply a verified tier rule to narrow it. Claude cache TTL uncertainty also produces a range.

Pricing coverage counts requests with usable counters/rates and those left unpriced. Reported subscription credits, nano-AIU and provider costs are different units. Tool/service fees absent from the counters are outside the token-cost comparison. Reasoning is not billed twice.

## Reconciliation metadata

Native collectors preserve numeric cumulative endpoints for Codex transitions and AGY snapshots. Keep those fields when round-tripping normalized exports: `native_total_input_tokens`, `native_total_output_tokens`, `legacy_total_input_tokens`, `legacy_total_output_tokens`, `cumulative_observed_at`, and the `cumulative_` token counters. They establish overlap across separate collection runs. An initial AGY cumulative baseline has unknown activity time and is excluded from dated reports; later observed deltas can be dated. Alternative Copilot SQL/event rows are reconciled per session globally, preferring usable event counters; mismatches and unsupported schemas remain visible.
