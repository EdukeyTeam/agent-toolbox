# Bitbucket pull request feedback

Identify **Bitbucket Cloud** or **Bitbucket Data Center** first; their APIs differ. Use an authenticated client or the web interface, follow pagination, and keep tokens out of command arguments, logs, and skill files.

## Cloud

- Read all pages of `GET /2.0/repositories/{workspace}/{repo_slug}/pullrequests/{pull_request_id}/comments`. The result includes general comments, inline comments, and replies.
- A new PR comment can carry a consolidated response. Reply in a thread when the team expects it; resolve a thread only after its finding is addressed.
- Review any outstanding PR tasks as well as comments.

See the official [Bitbucket Cloud pull request API](https://developer.atlassian.com/cloud/bitbucket/rest/api-group-pullrequests/).

## Data Center

- Read the PR and its comments using the instance's `/rest/api/latest/projects/{projectKey}/repos/{repositorySlug}/pull-requests/{pullRequestId}` endpoints.
- Check comment threads and blocker comments or tasks supported by that instance's version. Follow that team's reply and resolution rules.

See the official [Bitbucket Data Center pull request API](https://developer.atlassian.com/server/bitbucket/rest/v811/api-group-pull-requests/). Verify paths against the installed server version.
