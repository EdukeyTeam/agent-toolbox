# GitHub review feedback

Use the team's existing GitHub method if it can read reviews and post replies. The `gh` CLI is convenient but optional; if it is not ready, follow the [one-time setup guide](github-setup.md) only when needed. From a checkout, GitHub can infer the owner and repository. Outside a checkout, add `--repo OWNER/REPO` to `gh pr` commands and use the literal owner and repository in every `gh api` path; `gh api` has no `--repo` option.

## Collect

```bash
gh pr view <number-or-url> --json state,reviewDecision,reviewRequests
# Replace OWNER, REPO, and NUMBER with the PR's actual values, even outside a checkout:
gh api --paginate repos/OWNER/REPO/pulls/NUMBER/reviews
gh api --paginate repos/OWNER/REPO/pulls/NUMBER/comments
gh api --paginate repos/OWNER/REPO/issues/NUMBER/comments
gh pr checks <number-or-url>
```

The first REST API call returns every submitted review and its body across pages. The second includes inline review comments and replies; the third includes top-level conversation comments. REST comments do not report whether their review thread was resolved. To distinguish active threads from historical feedback, check the PR's **Files changed** conversations in GitHub, or query `reviewThreads.isResolved` with GraphQL:

```bash
# Replace OWNER, REPO, and NUMBER with the PR's actual values.
gh api graphql --paginate -f owner=OWNER -f repo=REPO -F number=NUMBER -f query='
query($owner: String!, $repo: String!, $number: Int!, $endCursor: String) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      reviewThreads(first: 100, after: $endCursor) {
        nodes { isResolved comments(first: 1) { nodes { url } } }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}'
```

Match each thread's first comment URL to the REST comments. Read all pages before changing code; an unresolved thread is active feedback, while a resolved one may still provide useful history.

## Fix and respond

Check out the PR's source branch before editing; fetching alone does not switch branches. Follow the repository's commit and test rules. For a consolidated reply, write the exact text to a file and use `gh pr comment <number> --body-file <file>`. For a reply attached to a specific inline comment, use GitHub's [review-comment reply endpoint](https://docs.github.com/en/rest/pulls/comments#create-a-reply-for-a-review-comment).

After pushing, recheck comments and checks. Request another review only when needed and supported by that repository. If the user wants to enable optional bot reviewers, follow the [one-time review bot setup guide](review-bots.md). Merge only with the user's authorization and the repository's required checks and approvals.

Official references: [pull request reviews](https://docs.github.com/en/rest/pulls/reviews), [review comments](https://docs.github.com/en/rest/pulls/comments), [review-thread fields](https://docs.github.com/en/graphql/reference/objects#pullrequestreviewthread), [issue comments](https://docs.github.com/en/rest/issues/comments), and [GitHub CLI API usage](https://cli.github.com/manual/gh_api).
