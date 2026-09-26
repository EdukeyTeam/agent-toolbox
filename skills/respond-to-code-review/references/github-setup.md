# Optional one-time GitHub CLI setup

Read this only when GitHub CLI is missing or not authenticated and the existing GitHub workflow cannot complete the task.

1. Check whether `gh` is already installed and usable. If it is missing, tell the user that GitHub CLI can read PR feedback and post comments, and ask whether they want it installed. If they agree, install it using the [official instructions for their operating system](https://github.com/cli/cli#installation). If they decline, use their existing browser or approved integration.
2. Let the user choose and complete authentication. Browser sign-in is the CLI default and requests broad OAuth scopes. A fine-grained personal access token can instead be limited to selected repositories and the permissions needed for this task: read access for inspection, write access only for replies or code changes. GitHub recommends `GH_TOKEN` for fine-grained tokens rather than `gh auth login --with-token`. Explain the choice briefly; do not choose broader access on the user's behalf.
3. Never ask for a token in chat, print it, put it in command arguments, or save it in the repository. The user should set up the credential through their own secure local method. Check the resulting account with `gh auth status`, without `--show-token`.

GitHub's browser login uses the system credential store when available and may fall back to a plain-text file when it is not. Tell the user if that fallback applies. See [GitHub CLI authentication](https://cli.github.com/manual/gh_auth_login) and [fine-grained token permissions](https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens).
