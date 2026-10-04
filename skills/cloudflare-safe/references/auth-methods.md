# Cloudflare authentication methods

Cloudflare has several credentials that look alike and are not interchangeable. This skill uses API tokens.

| Method | Signs in as | What it reaches | Role here |
|---|---|---|---|
| **API token**, account-owned or user-owned | The token | Exactly the permissions chosen when it was created, across the whole API | What `cf-read.mjs` and `cf-apply.mjs` use. |
| **OAuth sign-in**, used by Cloudflare's hosted MCP servers and other connected applications | The user | A fixed set of scopes chosen by the application, mostly developer-platform products | Optional helper for finding endpoints or combining calls. |
| **Global API key** | The user, with every permission they hold | Everything, including billing and members | Never use it with an agent. |
| **Access service token** | A service, to applications behind Cloudflare Access | Your own protected applications, not the Cloudflare API | Unrelated to this skill. |

## Account-owned or user-owned token

Both kinds offer the same permissions. An account-owned token belongs to the account, survives the departure of the person who created it, and appears in the audit log under its own name, which suits shared and long-lived automation. A user-owned token belongs to one person and can span every account that person can access. `cf-read.mjs verify` tries the account endpoint first and then the user endpoint, so either kind verifies.

## When an MCP server is also connected

An OAuth connection is limited to the scopes its application requests. Security configuration, such as zone settings, WAF rules and bot settings, is often outside those scopes even when listing a zone works. If the MCP server returns a permission error for something the read token can reach, use `cf-read.mjs` rather than concluding the data is unavailable.

An MCP connection may also carry write scopes. The skill's rules for changes apply regardless of the tool: propose, hand over or get explicit approval, then check.
