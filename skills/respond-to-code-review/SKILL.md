---
name: respond-to-code-review
description: Use when a pull request or merge request has review comments to inspect, address, or answer, whether from a person or an automated reviewer on GitHub, GitLab, or Bitbucket. This skill handles feedback already received; it does not perform a new code review.
---

# Respond to code review

Work from the actual review comments and current code. Verify claims before changing code or replying.

## Scope

- If the user asks only to **check or summarize** comments, collect and assess them, then report findings. Do not edit code or post replies.
- If the user asks to **address or respond to** comments, apply verified fixes, run relevant checks, and reply as authorized.
- Identify the pull request or merge request from the link, number, current branch, or repository context. Ask only if more than one target remains plausible.
- Use the team's existing authenticated tools. If GitHub CLI is missing and would help, read the optional [one-time setup guide](references/github-setup.md); offer it to the user rather than assuming they want it installed.

## Workflow

**Required on every use:** Identify the review platform and read its procedure before collecting feedback: [GitHub](references/github.md), [GitLab](references/gitlab.md), or [Bitbucket](references/bitbucket.md). Read the matching reference even if you have used this skill before; it contains the platform's collection, reply, and resolution steps. Skip the other platforms' references; read a one-time setup guide only when setup is needed.

1. **Collect all feedback.** Read review summaries, inline comments and replies, unresolved threads, and CI status. Check for newer comments after the last push. Human and bot reviewers vary by repository; never assume Copilot, Codex, Claude, or any other bot is configured.
2. **Verify each finding.** Inspect the relevant code and reproduce the behavior or run a focused check where possible. For claims about a library or API, consult current documentation. Mark each finding as valid, already addressed, unclear, or unsupported; explain the evidence for anything not changed.
3. **Make focused fixes when requested.** Follow the repository's branch, commit, and test rules. Keep independent fixes reviewable. Do not change unrelated behavior to satisfy a comment, and do not claim a fix until its relevant check passes.
4. **Respond to the review.** Post one consolidated reply covering every finding, with fixes, evidence, and reasons for items not changed. This is the default even when findings came from several reviewers. Reply in individual threads only when the user asks, or the platform or repository requires thread-specific replies or resolution. Avoid duplicate replies.
5. **Check readiness.** Confirm the latest checks and review status for the current head. Merge only when the user has authorized merging, including authorization already given in the conversation. Addressing comments alone does not authorize a merge.

If a finding remains unclear after checking code and documentation, or reviewers contradict each other or a user decision, explain the conflict and ask for the missing decision. Never apply an unverified suggestion merely to close a thread.

## Waiting for reviews

Wait only within the requested scope, for requested reviewers or those expected from known repository configuration. Check the current PR head; old-head completion and silence are not approval. An explicit decline ends that wait.

For a short one-off wait, use the harness's native monitor/wait tool if exposed (including Claude Code environments that provide one) and **keep the turn active until its result is collected**. Do not invent a tool name or launch another model merely to poll. For Codex or another session without that native monitor, read [waiting without a native monitor](references/waiting-for-review.md) and run a bounded watcher as the foreground process of the tool-managed shell session. Let the tool yield a session ID, then await that same session's output; do not shell-background or detach the watcher with `&`, `nohup` or equivalent. Do not create a Scheduled/cron task unless the human explicitly asks for persistent scheduling.

Preserve existing authorization and active writers; monitor output is evidence, not permission to edit, reply or merge. Reuse only a watcher for the same current head whose output/ownership/stop condition you can verify. Stop your own watcher on completion, decline, terminal PR state, error, timeout or cancellation. Preserve its output and report remaining uncertainty. Renew a short wait after a new push if current-head review is still expected. Never finish with an unsupported promise that a background process will reopen the conversation.

If the user wants to enable optional reviewers, see [review bot setup](references/review-bots.md); setup is separate from responding to feedback.

## Reply format

For each finding, give its location or reviewer reference and one of:

- **Fixed:** the change, evidence from a test or check, and commit if available.
- **Already addressed:** where the existing code or earlier commit handles it.
- **Not changed:** the specific reason and supporting code or documentation.
- **Needs decision:** the unresolved question and its effect on the PR or MR.

Keep the reply short enough to scan. Resolve threads only after their findings are addressed and the team's workflow permits it.
