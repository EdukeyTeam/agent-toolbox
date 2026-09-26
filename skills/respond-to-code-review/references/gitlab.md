# GitLab merge request feedback

GitLab calls review threads **discussions** and uses a project-local merge request **IID**. Use an authenticated `glab` CLI if available, or the GitLab API. Check the instance's own documentation when it is self-managed and may run an older version. Keep access tokens out of command arguments, logs, and skill files.

- Read all pages of `GET /projects/:id/merge_requests/:merge_request_iid/discussions`; inspect replies and resolution state.
- General MR comments are notes: `GET /projects/:id/merge_requests/:merge_request_iid/notes`.
- A consolidated response is a new MR note. When the team expects a reply in a thread, add a note to that discussion instead.
- Resolve a discussion only after its finding is addressed and the team's workflow permits it.

Official references: [Discussions API](https://docs.gitlab.com/api/discussions/) and [Notes API](https://docs.gitlab.com/api/notes/).
