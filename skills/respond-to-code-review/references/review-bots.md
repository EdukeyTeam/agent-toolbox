# Optional review bots

This is one-time repository setup, not a prerequisite for responding to review comments. Ask whether the user wants a bot reviewer before changing repository or organization settings. Check current vendor documentation, plan eligibility, permissions, and possible usage costs. A bot's absence on a pull request does not mean it approved the change.

## GitHub Copilot

If Copilot code review is available to the repository, request it from the pull request's **Reviewers** menu, like a human reviewer. For automatic reviews, a repository administrator can configure a branch ruleset with **Automatically request Copilot code review** and optionally **Review new pushes**. Availability depends on the user's or organization's Copilot access; it is not guaranteed for every repository. See [GitHub's setup guide](https://docs.github.com/en/copilot/how-tos/copilot-on-github/set-up-copilot/configure-code-review) and [request guide](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/request-a-code-review/use-code-review).

## Codex

Connect the GitHub repository to Codex cloud, then enable Code review for it in Codex settings. Users with the needed access can request a review on a pull request with `@codex review`; automatic reviews can be enabled separately in settings. If no review arrives, check the repository connection, code review setting, and trigger configuration. See [OpenAI's GitHub code review guide](https://learn.chatgpt.com/docs/third-party/github).

## Claude

Claude Code Review is a managed GitHub review service available to eligible Claude Team and Enterprise organizations. An organization owner enables it, installs the Claude GitHub App, selects repositories, and chooses automatic or manual review triggers. A configured repository can request a manual review with `@claude review`. See [Anthropic's Code Review guide](https://code.claude.com/docs/en/code-review). As a separate option, teams can run a [Claude Code GitHub Action](https://code.claude.com/docs/en/github-actions) to review pull requests; that requires a workflow and authentication setup.

## Requesting a review with a comment command

When the user asks for a review that a comment command starts, such as `@codex review`, `@claude review` or PR-Agent's `/review`:

- Post each command as its own comment, with nothing else in it. Self-hosted workflows often accept only the exact command text (for example `^@claude review$`) or check only the start of the comment, so a combined comment can silently start neither.
- For a workflow in the repository, read its trigger condition first; it states the exact text and who may use it.
- Confirm that the review actually started: the workflow run's review job must run, not finish as skipped, and the bot's reply must appear on the current head. A run that ends with a turn or time limit may post partial findings or none, so report that instead of treating silence as approval.
- A review costs money or subscription usage. Request one only when the user asked for it.

## Other hosts

GitLab and Bitbucket review bots depend on the user's own integrations and CI configuration. Inspect the repository's reviewers and pipelines rather than assuming a GitHub bot is available. Anthropic documents a [Claude Code GitLab CI/CD integration](https://code.claude.com/docs/en/gitlab-ci-cd); check its current instructions before offering setup. Continue the response workflow with the reviews that actually exist.
