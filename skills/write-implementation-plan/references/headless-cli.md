# Headless CLI examples for an authorized strong reviewer

Routine plan authoring/review stays with the main strong model; no CLI worker is required. Use these examples only for a separately requested/permitted strong expert review. Never select Luna, Haiku or another small execution model for a review, audit, plan comments or planning decisions. Future implementation workers use task-specific execution briefs after human approval.

Read only the sections for runners the human permitted. These are document-only worker examples, not commands to execute merely because this skill was loaded. They are portable Bash examples; another shell must preserve quoting, stdin, permissions, exit status and output handling.

## Before any external worker

Confirm the selected runner, exact available model/provider, cost/data boundary and purpose with the human's delegation policy. Check the installed executable's version and help; flags and model identifiers change. Use current official documentation, preferring an available documentation connector such as Context7 before general search. Authentication must already be provisioned; do not start an unattended login or expose credentials.

Prepare a self-contained brief and an isolated input packet containing only the required documents. Set the variables below to verified absolute paths; model variables are exact IDs selected for that runner, not suggested model defaults:

```bash
PLAN_PACKET="/absolute/path/to/scoped-documents"
PLAN_BRIEF="$PLAN_PACKET/brief.md"
PLAN_RUN="/absolute/path/to/this-worker-output"
PLAN_REPORT="$PLAN_RUN/review.md"
mkdir -p "$PLAN_RUN"
```

The brief requests a Markdown review on stdout, with source references, concrete findings and unresolved decisions. It forbids application edits, installs, services, other worker launches, commits, publication and approval changes. Its output is a review, not authorization to execute a plan. The main agent authors the plan; do not turn this review invocation into a plan-writing worker.

Start a fresh worker, not `--continue`/`--resume` against an unrelated session. Follow the environment's required job/session manager for long jobs and record process/session IDs, log paths and cleanup ownership. If no manager is provided or required, run in a monitored foreground session; if safe monitoring is unavailable, report that prerequisite instead of launching unattended work. Do not alter global CLI settings or disable sandbox/approval systems to make a headless job finish.

## Codex

```bash
codex exec --cd "$PLAN_PACKET" \
  --model "$PLAN_CODEX_MODEL" --sandbox read-only \
  --json --output-last-message "$PLAN_REPORT" \
  --skip-git-repo-check - \
  < "$PLAN_BRIEF" > "$PLAN_RUN/events.jsonl" 2> "$PLAN_RUN/stderr.log"
```

`-` reads the prompt from stdin; `--json` emits JSONL events; `--output-last-message` captures the final response. The latter is a CLI output mechanism, not permission for model-authored workspace changes. `--skip-git-repo-check` is for the isolated non-Git packet; omit it when running in an appropriate repository. Check the recorded model/cwd and final outcome, not only the launcher status. Do not add `--full-auto` or bypass flags; version-specific support differs.

Sources: [noninteractive operation](https://developers.openai.com/codex/noninteractive), [exec options](https://github.com/openai/codex/blob/main/codex-rs/exec/src/cli.rs), [shared CLI options](https://github.com/openai/codex/blob/main/codex-rs/utils/cli/src/shared_options.rs). Context7: `/openai/codex`.

## Claude Code

```bash
(
  cd "$PLAN_PACKET" || exit 1
  claude -p --model "$PLAN_CLAUDE_MODEL" \
    --permission-mode plan --tools 'Read,Glob,Grep' \
    --output-format text \
    < "$PLAN_BRIEF" > "$PLAN_REPORT" 2> "$PLAN_RUN/stderr.log"
)
```

Print mode reads the supplied stdin and exits. `--tools` selects the available tools; `--allowedTools` alone is an approval list, not an exclusive tool list. Here shell/edit/write tools are omitted deliberately. Capture text directly as Markdown; if using `--output-format json` instead, parse its documented result/error shape rather than treating JSON as a report. Do not add permission-bypass flags.

Sources: [headless operation](https://code.claude.com/docs/en/headless), [CLI reference](https://code.claude.com/docs/en/cli-reference), [tool reference](https://code.claude.com/docs/en/tools-reference). Context7: `/websites/code_claude`.

## OpenCode

```bash
(
  cd "$PLAN_PACKET" || exit 1
  opencode run --agent plan --model "$PLAN_OPENCODE_MODEL" --format json \
    "Follow the attached brief. Return your Markdown review; do not edit files." \
    --file "$PLAN_BRIEF" \
    < /dev/null > "$PLAN_RUN/events.jsonl" 2> "$PLAN_RUN/stderr.log"
)
```

The model is a verified `provider/model` identifier. `--file` attaches the brief; the positional argument supplies the instruction. **`-p` is a server-password option, not a prompt flag.** The built-in `plan` agent limits editing according to its configuration; verify effective permissions. Use the scoped packet rather than the live application checkout. Do not add `--auto` or silently switch to the default build agent after a permission denial.

JSON output is an event stream, not one final JSON object. Extract the final assistant text using the installed version's event schema, confirm normal completion, then save it as the review. A soft-denied tool, empty artifact or incomplete finish is not a successful review even if the process exits 0.

Sources: [CLI](https://opencode.ai/docs/cli/), [agents](https://opencode.ai/docs/agents/), [permissions](https://opencode.ai/docs/permissions/). Context7: `/anomalyco/opencode` (current repository); old versions may have different flags.

## Google Antigravity (`agy`)

```bash
agy --mode plan --add-dir "$PLAN_PACKET" \
  --model "$PLAN_AGY_MODEL" --output-format text \
  -p "Read $PLAN_BRIEF. Follow that brief and return Markdown only. Do not edit files or run shell commands." \
  < /dev/null > "$PLAN_REPORT" 2> "$PLAN_RUN/stderr.log"
```

Use the exact model identifier supported by the installed CLI. `--add-dir` makes the intended packet workspace explicit; do not assume the shell cwd alone is sufficient. `--mode plan` is for read-only investigation; verify that the installed version supports it. The model returns stdout, so its report does not require a workspace write grant. Do not use `--mode accept-edits` for a review just because it is convenient.

Headless tools that need unavailable interactive approval can be soft-denied while the run exits 0. Require substantive output and inspect diagnostics. Do not ask this reviewer to use shell commands as a workaround; the orchestrator performs mechanical validators. Timeout defaults vary between documentation and releases: inspect installed help, avoid arbitrary short cutoffs, and never interpret a truncated run as completion. Ordinary text output may be buffered; silence alone is not failure.

Sources: [headless operation](https://antigravity.google/docs/cli/headless), [modes](https://antigravity.google/docs/cli/modes). Context7: `/websites/antigravity_google_cli`.

## Completion and failure

Capture the **runner's** exit status, normal completion signal where provided, substantive report and source-backed findings. Check denied tools, truncation, limits, unexpected model/provider and missing output. If using `tee`, preserve both runner and logger statuses; `$?` from the final pipeline command does not prove the worker succeeded.

On failure, preserve useful partial evidence, report the specific cause and keep the plan unapproved. Do not change provider, spend, permissions or scope silently. Close only processes/sessions created for this job, after preserving output; never stop another active session or its workers without authorization.

A CLI's plan/read-only mode is an additional control, not the human-review gate. All runners return to the orchestrator, which consolidates the allowed documents, reviews them and ends the planning turn. None may begin implementation after a positive review.

## Verification note

Examples were checked against Context7 documentation and local help on 2026-10-22: Codex CLI 0.163.0, Claude Code 2.1.304, OpenCode 1.18.30, Antigravity 1.4.2. This verifies option availability, not authentication, model access or a successful remote agent run. Recheck installed help before use. OpenCode documentation also describes newer major versions; the examples avoid newer variant flags. Antigravity 1.4.2 help reports a zero/unlimited default print timeout, whereas indexed docs describe a finite default.
