# Waiting without a native monitor

Read only when the current harness does not expose a suitable native monitor/wait tool. In a Claude Code environment with a built-in monitor, use that tool and await its output; do not implement a second scheduler. Do not assume the same tool exists in every version or surface.

## Keep this turn active

Run one bounded watcher as the foreground process of the tool-managed shell session. Do not use shell `&`, `nohup` or another detachment method: the parent shell can exit before the watcher returns, leaving no session output to collect. Let the harness itself yield/background the still-running command and retain its session or task ID. Its result, not a new scheduled conversation, returns control to the coordinator. A session ID or "running" status means the command is still executing: wait/poll that same session using the harness's output tool rather than restarting it. Codex commonly exposes this as `exec_command` followed by `write_stdin`; use the actual tool schema supplied by the current session. Do independent work where useful, then collect the result before the final response. Do not leave an indefinite tool call blocking user interaction.

A detached process or asynchronous hook is not automatically a new-turn trigger. Without a verified continuation mechanism, do not end the turn promising an automatic return. Do not install services, hooks, a message-queue bridge or permanent scheduler just for this short wait.

## Small provider-independent mechanism

This is pseudocode, not an executable shell script or a new dependency:

```text
pin the target PR/MR, current head and last handled feedback identifiers
set a deadline and maximum checks; record process/session and log path
repeat until either bound is reached:
    fetch complete review feedback/status using the platform's normal adapter
    if API/auth fails, head changes, PR closes or reviewer declines:
        return a diagnostic result and stop
    if unhandled feedback or explicit current-head review completion exists:
        return the evidence and stop (completion may contain no findings)
    wait no longer than the polling interval or remaining deadline
return timeout, never approval
```

Use the human's timing; otherwise allow roughly three checks 3-4 minutes apart. The watcher itself enforces the bounds and request timeouts so it stops if the coordinator is interrupted. Name the target head, deadline, check limit, process/session ID and output path before launch. Keep logs outside the target worktree or in a verified ignored durable directory.

Use the selected platform's existing collection procedure: [GitHub](github.md), [GitLab](gitlab.md) or [Bitbucket](bitbucket.md). For GitHub, an authenticated `gh` adapter can collect review summaries, inline comments/replies and conversation comments; do not replace all feedback with CI checks or require GitHub CLI for other platforms. Parse actual current-head completion/status and stable feedback identifiers, not generic words in arbitrary comment bodies. A new push invalidates a watcher pinned to the old head.

On result, the coordinator re-reads complete feedback, verifies findings and fixes/replies only within existing authorization. A successful process exit is not review approval or permission to merge. Check both approvals and required CI against the current head. Avoid duplicate responses. On timeout/error, report what is unresolved; silence is not success.

Preserve evidence and stop only a watcher you own. Before final handoff, collect its result and confirm it exited; if interruption leaves it running, record its ID, owner and self-enforced deadline rather than pretending it ended. Persistent Scheduled tasks are for a separately explicit persistent-scheduling request.
