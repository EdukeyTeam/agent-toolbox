# Letting search and AI crawlers through

Read this before proposing a rule that exempts crawlers from challenges, or a policy for AI crawlers. Crawler names and Cloudflare's bot features change often: confirm each name against its operator's documentation and each feature against the Cloudflare documentation before proposing a change.

## What to check first

1. **Is anything blocking them?** Read the zone's custom rules, its bot settings and recent security events for the crawler's user agent before changing anything. Often nothing needs to change.
2. **Which bot product is on?** On the Free plan, Bot Fight Mode runs outside the rules engine and a custom rule cannot skip it; the only choices are to turn it off or to upgrade. Super Bot Fight Mode (paid plans) and managed rules can be skipped with a custom rule using the Skip action.
3. **Does the zone manage AI crawlers in the dashboard?** Cloudflare's AI crawler controls may already allow or block specific crawlers. Those settings may not be available through the API; ask the user for a screenshot if you cannot read them.

## Never match on the user agent alone

A user agent is a header anyone can send. A rule that skips security for `user agent contains "Googlebot"` gives every attacker a way past the WAF. Require Cloudflare's own verification as well: `cf.client.bot` is true only for bots Cloudflare has verified by their network origin.

```text
cf.client.bot and (
  lower(http.user_agent) contains "googlebot"
  or lower(http.user_agent) contains "bingbot"
  or lower(http.user_agent) contains "duckduckbot"
  or lower(http.user_agent) contains "applebot"
  or lower(http.user_agent) contains "oai-searchbot"
  or lower(http.user_agent) contains "chatgpt-user"
  or lower(http.user_agent) contains "perplexitybot"
  or lower(http.user_agent) contains "claude-searchbot"
)
```

Action: Skip, limited to the security features that were actually blocking the crawler. Place it above the rule that challenges or blocks. `lower()` is needed because comparisons are case-sensitive and operators do not capitalise consistently (`bingbot`, `Googlebot`). If a crawler the user wants is not on Cloudflare's verified list, say so and let them decide; do not drop `cf.client.bot` to make the rule match.

## Crawler names, by purpose

Treat this as a starting point to verify, not a complete or current list.

| Purpose | Examples | Usual choice |
|---|---|---|
| Search indexing | `Googlebot`, `bingbot`, `DuckDuckBot`, `Applebot` | Allow. Blocking removes the site from search results. |
| AI search and answers with citations | `OAI-SearchBot`, `PerplexityBot`, `Claude-SearchBot` | Allow if the site should appear in AI answers. |
| Fetches made for a user's request | `ChatGPT-User`, `Perplexity-User`, `Claude-User` | Allow if users should be able to open the site from an assistant. |
| Training data collection | `GPTBot`, `ClaudeBot`, `CCBot`, `Google-Extended`, `Applebot-Extended`, `Bytespider`, `Meta-ExternalAgent` | The site owner's business decision. Ask; do not assume. |

`Google-Extended` and `Applebot-Extended` are robots.txt controls rather than separate crawlers, so they are set in robots.txt and not matched in a rule.

## Keep robots.txt consistent

robots.txt states the policy for well-behaved crawlers; Cloudflare rules enforce it. When proposing a Cloudflare change for crawlers, read the site's live `/robots.txt` and point out any contradiction, such as a crawler allowed in robots.txt but challenged by a rule.
