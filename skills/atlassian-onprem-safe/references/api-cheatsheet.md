# Server/DC API cheatsheet

Use the installed server version's reference. Paths below are relative to the
stored base URL, whose context path is preserved automatically. Commands are the
arguments after `atlassian.sh` / `atlassian.ps1` / `atlassian.py`. All are GET unless
listed under approved writes. Quote JQL/CQL and query arguments in the shell.

## Bitbucket

| Command | Path |
| --- | --- |
| `bitbucket projects` | `/rest/api/1.0/projects` |
| `bitbucket repos PROJECT` | `/rest/api/1.0/projects/PROJECT/repos` |
| `bitbucket prs PROJECT REPO` | `/rest/api/1.0/projects/PROJECT/repos/REPO/pull-requests` |
| `bitbucket pr PROJECT REPO ID` | same + `/ID` |
| `bitbucket diff PROJECT REPO ID` | same + `/ID.diff` (text wrapped as JSON) |
| `bitbucket activities PROJECT REPO ID` | same + `/ID/activities` |
| `bitbucket comments PROJECT REPO ID --query path=src/main.ts` | same + `/ID/comments` |

The PR list defaults to the server's default state (usually OPEN). Add
`--query state=ALL` when you need every state. Lists use `limit` and `start`;
`--all` follows `isLastPage` and the server's `nextPageStart`, never a guessed offset.
The comments endpoint requires a file `path`; use activities for general PR discussion.
Diff output can itself be truncated by the server; activities can contain threaded
comments not represented by a flat comment list. Keep server truncation metadata.

[Bitbucket REST reference](https://developer.atlassian.com/server/bitbucket/rest/v1002/api-group-pull-requests/)
and [API introduction/pagination](https://developer.atlassian.com/server/bitbucket/rest/v1002/intro/).

## Jira

| Command | Path |
| --- | --- |
| `jira search 'project = DEMO'` | `/rest/api/2/search?jql=...` |
| `jira issue DEMO-1` | `/rest/api/2/issue/DEMO-1` |
| `jira comments DEMO-1` | `/rest/api/2/issue/DEMO-1/comment` |
| `jira transitions DEMO-1` | `/rest/api/2/issue/DEMO-1/transitions` |

Use `--query fields=summary,status` to limit returned issue fields. Lists with
`startAt`, `maxResults` and `total` are followed by `--all`. Query caps and permissions
still affect search results. For transitions requiring additional fields, use the
human UI; this wrapper supports only an ID-only transition body.

[Jira search](https://developer.atlassian.com/server/jira/platform/rest/v11003/api-group-search/)
and [issues, comments, transitions](https://developer.atlassian.com/server/jira/platform/rest/v11003/api-group-issue/).

## Confluence

| Command | Path |
| --- | --- |
| `confluence search 'type = page AND space = DEMO'` | `/rest/api/content/search?cql=...` |
| `confluence page 123` | `/rest/api/content/123?expand=body.storage,version` |
| `confluence page 123 --query expand=body.view,version` | same page with rendered view |
| `confluence GET /rest/api/space --query limit=10` | list visible spaces |

`--all` follows `_links.next`, preserving the configured origin/context and refusing
links outside the product REST root. Query-only next links are supported. Older
responses without `_links` can use `start/limit/size`; a full last page may cause one
extra empty GET. With `_links` present and no `next`, pagination ends. Nested expanded
collections have their own pagination and are not recursively fetched.

[Content resource](https://developer.atlassian.com/server/confluence/rest/v10215/api-group-content-resource/)
and [examples/pagination](https://developer.atlassian.com/server/confluence/confluence-rest-api-examples/).

## Approved writes

Write one UTF-8 JSON body file, review it with the human, then pass its path via
`--body-file`. All writes require BOTH `--write --confirmed`; leaving either out
prints the request summary and refuses the request. There is no env-only approval
or generic write endpoint. Commands accept exactly the fields shown below.

| Command | Method/path | Body example |
| --- | --- | --- |
| `bitbucket pr-comment PROJECT REPO ID` | POST PR `/ID/comments` | `{"text":"Reviewed the error handling."}` |
| `jira comment DEMO-1` | POST issue `/DEMO-1/comment` | `{"body":"Verified on the staging environment."}` |
| `jira transition DEMO-1` | POST issue `/DEMO-1/transitions` | `{"transition":{"id":"31"}}` |
| `confluence update-page 123` | PUT `/rest/api/content/123` | see below |

For a page currently at version 4, after reading its full storage body:

```json
{
  "type": "page",
  "title": "Release notes",
  "version": {"number": 5},
  "body": {
    "storage": {"value": "<p>Full replacement page body.</p>", "representation": "storage"}
  }
}
```

Do not reuse stale versions or write a rendered `view` as `storage`. Updates replace
the full title/body. Restore prior content only as a separately approved new version.
Comments and transitions can notify users or invoke automation. Each write prints
its redacted method, URL and full body before sending; stdout holds only the API
JSON result (`null` for an empty successful response). A nonzero exit does not prove
the write was rolled back. Inspect state before any retry.

## Version and authentication sources

- [Bitbucket HTTP access tokens](https://confluence.atlassian.com/bitbucketserver/personal-access-tokens-939515499.html): PATs introduced in 5.5; use Bearer by default. A username explicitly selects Basic for installations requiring it.
- [Bitbucket 7.2 archived documentation](https://confluence.atlassian.com/alldoc/files/278071997/1014269810/1/1592961931913/BitbucketServer072Docs.pdf) records the 5.5 introduction. Older deployments may need Basic username/password; administrator policy decides availability.
- [Jira/Confluence PAT documentation](https://confluence.atlassian.com/enterprise/using-personal-access-tokens-1026032365.html): Jira Core/Software 8.14+, JSM 4.15+, Confluence 7.9+, with Bearer authorization. PAT availability is not a guarantee every endpoint above exists on the oldest versions.
- [Atlassian Rovo MCP](https://developer.atlassian.com/cloud/rovo-mcp/) serves Cloud. Cloud REST auth/endpoints differ, including email/API-token Basic for Jira/Confluence. This skill is scoped to Server/DC.

These are compatibility notes, not certification against every product version.
An administrator may disable Basic/PAT auth, restrict token lifetime or require VPN.
No real-server validation is bundled; run setup and a scoped read on your own server.
