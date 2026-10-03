# Change file format

One file describes one API request. The agent writes it, the human reviews it and replies `approved`, and `cf-apply.mjs` sends it.

## Location and name

```text
cf-changes/cf-change-YYYYMMDD-HHmm-<slug>.json
```

Put the folder in the current workspace. Use the UTC time of staging and a short kebab-case slug such as `allow-verified-bots`. The applied files form the audit trail of what the agent changed, so keep them. They contain the configuration that was read, so check them for sensitive values before committing them to a shared repository.

## Fields

```json
{
  "summary": "Challenge requests to /admin that do not come from the office network",
  "zone": "example.com",
  "zone_id": "0123456789abcdef0123456789abcdef",
  "created_at": "2026-01-15T10:42:00Z",
  "agent": "claude-code",
  "category": "waf",
  "blast_radius": "Requests to example.com/admin only; public pages are unaffected",
  "current_state": { "rules": [] },
  "proposed_state": { "rules": [{ "description": "Challenge /admin", "action": "managed_challenge" }] },
  "diff": "Adds one rule at the end of the custom ruleset; no existing rule changes.",
  "apply_command": {
    "method": "POST",
    "url": "https://api.cloudflare.com/client/v4/zones/0123456789abcdef0123456789abcdef/rulesets/<ruleset-id>/rules",
    "body": {
      "description": "Challenge /admin",
      "expression": "starts_with(http.request.uri.path, \"/admin\") and not ip.src in {203.0.113.0/24}",
      "action": "managed_challenge"
    }
  },
  "verification": "GET the ruleset and confirm the new rule is present and enabled; request /admin from outside the office network and expect a challenge.",
  "rollback": "DELETE zones/<zone-id>/rulesets/<ruleset-id>/rules/<new-rule-id>"
}
```

| Field | Required | Content |
|---|---|---|
| `summary` | yes | One line a human can approve or reject. |
| `category` | yes | The area, such as `dns`, `waf`, `bots`, `redirect-rules`, `transform-rules`, `cache`, `zone-settings`, `workers`, `r2` or `tunnel`. |
| `blast_radius` | yes | Which traffic or users are affected if this goes wrong. |
| `current_state` | yes | What the API returned for the affected object before the change; `null` when creating something new. |
| `proposed_state` | yes | What will exist afterwards; `null` when deleting. |
| `diff` | yes | The exact difference, in words a reviewer can check against the two states. |
| `apply_command` | yes | `method` (`POST`, `PUT`, `PATCH` or `DELETE`), `url` (must start with `https://api.cloudflare.com/client/v4/`) and `body` (the full request body, or `null`). |
| `verification` | yes | How to confirm the change worked: the read to repeat and the behaviour to test. |
| `rollback` | yes | The exact request or dashboard step that undoes it. |
| `zone`, `zone_id`, `created_at`, `agent` | no | Context for the reviewer and the audit trail. |

After sending the request the script adds `applied_at`, `http_status`, `api_success` and `result` (the API response). If the connection fails before a response arrives, it records the attempt with `http_status` and `api_success` set to `null`, because the change may have been applied anyway. A file that already has `applied_at` is refused: read the current state, then stage a new file to retry or to roll back.

## Before staging

- Read the current state in this session. Do not reuse a state from memory or an earlier conversation.
- Keep to one request per file. A change that needs several requests becomes several files, approved one by one in an order that is safe to stop halfway.
- For `PUT` requests that replace a whole object, such as a ruleset, build the body from the state you just read so nothing existing is dropped.
- Check the change against the "Never, even with approval" list in the skill.
