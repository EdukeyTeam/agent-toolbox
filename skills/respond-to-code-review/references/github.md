# GitHub review feedback

Use the team's existing GitHub method if it can read reviews and post replies. The `gh` CLI is convenient but optional; if it is not ready, follow the [one-time setup guide](github-setup.md) only when needed. From a checkout, GitHub can infer the owner and repository; add `--repo owner/repo` to `gh pr` commands when working elsewhere.

## Collect

```bash
gh pr view <number-or-url> --json state,reviewDecision,reviewRequests,reviews
# In a repository checkout, replace NUMBER with the PR number:
gh api --paginate repos/{owner}/{repo}/pulls/NUMBER/comments
gh api --paginate repos/{owner}/{repo}/issues/NUMBER/comments
gh pr checks <number-or-url>
```

The first API call includes inline review comments and replies; the second includes top-level conversation comments. Review bodies are in `reviews`. Read all pages and identify which threads are unresolved before changing code.

## Fix and respond

Check out the PR's source branch before editing; fetching alone does not switch branches. Follow the repository's commit and test rules. For a consolidated reply, write the exact text to a file and use `gh pr comment <number> --body-file <file>`. For a reply attached to a specific inline comment, use GitHub's [review-comment reply endpoint](https://docs.github.com/en/rest/pulls/comments#create-a-reply-for-a-review-comment).

After pushing, recheck comments and checks. Request another review only when needed and supported by that repository. Merge only with the user's authorization and the repository's required checks and approvals.

Official references: [pull request reviews](https://docs.github.com/en/rest/pulls/reviews), [review comments](https://docs.github.com/en/rest/pulls/comments), [issue comments](https://docs.github.com/en/rest/issues/comments).
