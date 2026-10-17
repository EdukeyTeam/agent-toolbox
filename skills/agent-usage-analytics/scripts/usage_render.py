"""Render one report object as JSON, Markdown and an offline HTML dashboard.

Rendering consumes only the report object. It never reads source files, runs
logged commands or fetches network resources.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re
from typing import Any

PLACEHOLDER = "__REPORT_JSON__"
TEMPLATE = Path(__file__).resolve().parent.parent / "assets" / "dashboard.html"
UNKNOWN = "Unknown"
NOT_SET = "Not set"
COST_NOTE = ("Costs are API-equivalent estimates from a versioned public rate card. "
             "They are not an invoice and not subscription payments.")

# Script-breaking characters inside the embedded JSON. All occur only inside
# JSON strings, where a \u escape is equivalent.
_EMBED_ESCAPES = {ord("<"): "\\u003c", ord(">"): "\\u003e", ord("&"): "\\u0026",
                  0x2028: "\\u2028", 0x2029: "\\u2029"}
_MD_SPECIAL = re.compile(r"([\\`*_\[\]<>|~&#!$])")
_CONTROL = re.compile(r"[\x00-\x1f\x7f\u0085\u2028\u2029]+")
_ISO = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})(?::\d{2}(?:\.\d+)?)?(Z|[+-]\d{2}:\d{2})$")
_PREFIX = re.compile(r"[A-Za-z0-9][\w.-]{0,80}")

BASIS_LABELS = {"input_plus_output": "input + output of the latest measured request",
                "input_only": "input of the latest measured request"}
GROUPS = (("daily", "Daily usage", "Date"), ("monthly", "Monthly usage", "Month"),
          ("models", "Models", "Model"), ("sessions", "Sessions", "Session"),
          ("tasks", "Task categories", "Task"))
METRIC_HEADERS = ["Requests", "Input", "Cache read", "Cache write", "Output",
                  "Reasoning (in output)", "Total", "API-equivalent cost"]
GROUP_LIMIT = 50
CONTRIBUTOR_LIMIT = 25
WARNING_DETAIL_LIMIT = 50


def write_reports(report: dict, outdir: Path, prefix: str = "report") -> dict[str, str]:
    """Write <prefix>.json/.md/.html into outdir and return their paths."""
    if not isinstance(report, dict):
        raise TypeError("report must be a dict")
    if not isinstance(prefix, str) or not _PREFIX.fullmatch(prefix):
        raise ValueError("prefix must be a plain file name stem")
    outdir = Path(outdir)
    # Render everything before writing so a failure never leaves mixed artifacts.
    texts = {"json": render_json(report), "markdown": render_markdown(report),
             "html": render_html(report)}
    outdir.mkdir(parents=True, exist_ok=True)
    paths = {"json": outdir / f"{prefix}.json", "markdown": outdir / f"{prefix}.md",
             "html": outdir / f"{prefix}.html"}
    for key, path in paths.items():
        with path.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(texts[key])
    return {key: str(path) for key, path in paths.items()}


def render_json(report: dict) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def embed_json(report: dict) -> str:
    """Compact JSON that cannot close or confuse its <script> element."""
    text = json.dumps(report, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return text.translate(_EMBED_ESCAPES)


def render_html(report: dict) -> str:
    template = TEMPLATE.read_text(encoding="utf-8")
    if template.count(PLACEHOLDER) != 1:
        raise RuntimeError("dashboard template must contain exactly one data placeholder")
    return template.replace(PLACEHOLDER, embed_json(report))


# ---------------------------------------------------------------- formatting

def _num(value: object) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) else None


def _obj(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _rows(value: object) -> list[dict[str, Any]]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def md(value: object, limit: int = 160) -> str:
    """Escape one untrusted label for a Markdown paragraph or table cell."""
    if value is None:
        return UNKNOWN
    text = _CONTROL.sub(" ", str(value)).strip()
    if not text:
        return UNKNOWN
    if len(text) > limit:
        text = text[:limit - 3] + "..."
    return _MD_SPECIAL.sub(r"\\\1", text)


def fmt_int(value: object) -> str:
    number = _num(value)
    return UNKNOWN if number is None else f"{round(number):,}"


def fmt_signed_int(value: object) -> str:
    number = _num(value)
    return UNKNOWN if number is None else f"{round(number):+,}"


def fmt_usd(value: float) -> str:
    if value != 0 and abs(value) < 0.01:
        return f"${value:.4f}"
    return f"${value:,.2f}"


def fmt_cost(lower: object, upper: object = None) -> str:
    lo, hi = _num(lower), _num(upper)
    if lo is None and hi is None:
        return UNKNOWN
    if lo is None:
        return f"up to {fmt_usd(hi)}"
    if hi is None:
        return f"at least {fmt_usd(lo)}"
    if abs(hi - lo) < 0.00005:
        return fmt_usd(lo)
    return f"{fmt_usd(lo)} to {fmt_usd(hi)}"


def fmt_pct(value: object) -> str:
    number = _num(value)
    return UNKNOWN if number is None else f"{number:.1f}%"


def fmt_delta(value: object) -> str:
    number = _num(value)
    return UNKNOWN if number is None else f"{number:+.1f}%"


def fmt_time(value: object) -> str:
    if not isinstance(value, str) or not value:
        return UNKNOWN
    match = _ISO.match(value)
    if not match:
        return md(value)
    zone = "UTC" if match.group(3) == "Z" else match.group(3)
    return f"{match.group(1)} {match.group(2)} {zone}"


def fmt_duration(minutes: object) -> str:
    number = _num(minutes)
    if number is None or number <= 0:
        return UNKNOWN
    number = round(number)
    if number % 1440 == 0:
        return f"{number // 1440} d"
    if number % 60 == 0:
        return f"{number // 60} h"
    return f"{number} min"


def table(headers: list[str], rows: list[list[str]], numeric: set[int] | None = None) -> list[str]:
    numeric = numeric or set()
    lines = ["| " + " | ".join(headers) + " |",
             "| " + " | ".join("---:" if i in numeric else "---" for i in range(len(headers))) + " |"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines + [""]


def row_total(row: dict[str, Any]) -> int | float | None:
    total = _num(row.get("total_tokens"))
    if total is not None:
        return total
    parts = [_num(row.get("input_tokens")), _num(row.get("output_tokens"))]
    if all(part is None for part in parts):
        return None
    return sum(part for part in parts if part is not None)


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _by_total(rows: list[dict[str, Any]], field: str = "total_tokens") -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: (_num(row.get(field)) is None, -(_num(row.get(field)) or 0)))


def _metric_cells(row: dict[str, Any]) -> list[str]:
    return [fmt_int(row.get("requests")), fmt_int(row.get("input_tokens")),
            fmt_int(row.get("cache_read_tokens")), fmt_int(row.get("cache_write_tokens")),
            fmt_int(row.get("output_tokens")), fmt_int(row.get("reasoning_tokens")),
            fmt_int(row_total(row)), fmt_cost(row.get("cost_lower_usd"), row.get("cost_upper_usd"))]


# ------------------------------------------------------------------ sections

def _scope_md(report: dict) -> list[str]:
    scope = _obj(report.get("scope"))
    session = report.get("mode") == "session"
    lines = ["# " + ("Session usage report" if session else "Agent usage report"), "",
             f"- Generated: {fmt_time(report.get('generated_at'))}",
             f"- Mode: {'single session' if session else 'historical usage'}",
             f"- Period: {md(scope.get('since')) if scope.get('since') else NOT_SET}"
             f" to {md(scope.get('until')) if scope.get('until') else NOT_SET} (half-open)",
             f"- Calendar timezone: {md(scope.get('timezone')) if scope.get('timezone') else 'UTC'}"]
    if scope.get("session_id"):
        lines.append(f"- Session: {md(scope.get('session_id'))}")
    lines.append("- Share mode: " + ("on, identifying labels are pseudonymized" if scope.get("share") else "off"))
    return lines + ["", f"> {COST_NOTE}", ""]


def _summary_md(report: dict) -> list[str]:
    session = report.get("mode") == "session"
    lines = ["## " + ("Lifetime usage of this session" if session else "Summary"), ""]
    summary = _obj(report.get("summary"))
    if not summary:
        return lines + ["No summary is available in this report.", ""]
    rows = [
        ["Requests", fmt_int(summary.get("requests"))],
        ["Sessions", fmt_int(summary.get("sessions"))],
        ["Input tokens (includes cache reads and writes)", fmt_int(summary.get("input_tokens"))],
        ["Cache read tokens", fmt_int(summary.get("cache_read_tokens"))],
        ["Cache write tokens", fmt_int(summary.get("cache_write_tokens"))],
        ["Output tokens (includes reasoning)", fmt_int(summary.get("output_tokens"))],
        ["Reasoning tokens (subset of output, not added again)", fmt_int(summary.get("reasoning_tokens"))],
        ["Total processed tokens (input + output)", fmt_int(summary.get("total_tokens"))],
        ["API-equivalent cost estimate (USD)",
         fmt_cost(summary.get("cost_lower_usd"), summary.get("cost_upper_usd"))],
        ["Priced requests", fmt_int(summary.get("priced_requests"))],
        ["Unpriced requests", fmt_int(summary.get("unpriced_requests"))],
        ["Requests missing usage counts", fmt_int(summary.get("missing_usage_requests"))],
    ]
    lines += table(["Metric", "Value"], rows, {1})
    if (_num(summary.get("requests")) or 0) == 0:
        lines += ["No measurable usage was found for this scope. Check the coverage and warnings "
                  "sections for unreadable or unsupported sources, widen the period, or select "
                  "another data root.", ""]
    missing = _num(summary.get("missing_usage_requests")) or 0
    unpriced = _num(summary.get("unpriced_requests")) or 0
    if missing:
        lines += [f"Token totals are known lower bounds: {fmt_int(missing)} requests had no usage counts.", ""]
    if summary.get("accounting_gap_observations"):
        lines += [f"Selected source history has {fmt_int(summary['accounting_gap_observations'])} accounting-gap observations. "
                  "Excluded or unattributable activity is not zero usage; gaps may extend outside the selected period.", ""]
    if unpriced:
        lines += [f"The cost covers priced requests only: {fmt_int(unpriced)} requests are unpriced.", ""]
    return lines


def _comparison_md(report: dict) -> list[str]:
    comparison = report.get("comparison")
    if not isinstance(comparison, dict):
        return []
    previous, current = _obj(comparison.get("previous")), _obj(report.get("summary"))
    rows = [["Requests", fmt_int(previous.get("requests")), fmt_int(current.get("requests"))],
            ["Total tokens", fmt_int(previous.get("total_tokens")), fmt_int(current.get("total_tokens"))],
            ["API-equivalent cost", fmt_cost(previous.get("cost_lower_usd"), previous.get("cost_upper_usd")),
             fmt_cost(current.get("cost_lower_usd"), current.get("cost_upper_usd"))]]
    return (["## Comparison with the previous period", ""]
            + table(["Metric", "Previous", "Current"], rows, {1, 2})
            + [f"Token change: {fmt_delta(comparison.get('token_delta_percent'))}. "
               f"Cost change: {fmt_delta(comparison.get('cost_delta_percent'))}.", ""])


def _insights_md(report: dict) -> list[str]:
    insights = _rows(report.get("insights"))
    lines = ["## Insights", ""]
    if not insights:
        return lines + ["No evidence-based recommendation applies to this scope.", ""]
    for index, item in enumerate(insights, 1):
        lines.append(f"{index}. **{md(item.get('title'))}**")
        lines.append(f"   - Evidence: {md(item.get('evidence'), 400)}")
        lines.append(f"   - Suggested action: {md(item.get('action'), 400)}")
    return lines + ["", "Recommendations are suggestions only; nothing in your configuration was changed.", ""]


def _groups_md(report: dict) -> list[str]:
    lines: list[str] = []
    for key, title, label in GROUPS:
        rows = _rows(report.get(key))
        lines += [f"## {title}", ""]
        if not rows:
            lines += ["No data for this grouping.", ""]
            continue
        rows = sorted(rows, key=lambda row: str(row.get("label"))) if key in ("daily", "monthly") else _by_total(rows)
        shown = rows[:GROUP_LIMIT]
        if key == "sessions":
            headers = [label, "Agent", "Model"] + METRIC_HEADERS
            body = [[md(row.get("label")), md(row.get("agent")), md(row.get("model"))] + _metric_cells(row)
                    for row in shown]
            numeric = set(range(3, len(headers)))
        else:
            headers = [label] + METRIC_HEADERS
            body = [[md(row.get("label"))] + _metric_cells(row) for row in shown]
            numeric = set(range(1, len(headers)))
        lines += table(headers, body, numeric)
        if len(rows) > len(shown):
            lines += [f"Showing the top {len(shown)} of {len(rows)} rows by total tokens; the JSON report has all rows.", ""]
    return lines


def _context_md(report: dict) -> list[str]:
    contexts = _rows(report.get("contexts"))
    lines = ["## Current context", ""]
    if not contexts:
        return lines + ["No context observation is available in this report. Context is reported per "
                        "session from its latest measured request.", ""]
    contexts.sort(key=lambda row: str(row.get("observed_at") or ""), reverse=True)
    lines += ["Context describes one session at its latest measured request. It is separate from "
              "the processed historical totals above, which count every request.", ""]
    for context in contexts[:10]:
        lines += _one_context_md(context)
    if len(contexts) > 10:
        lines += [f"Showing the 10 most recent of {len(contexts)} context observations; the JSON report has all.", ""]
    return lines


def _one_context_md(context: dict[str, Any]) -> list[str]:
    used, window = _num(context.get("used_tokens")), _num(context.get("window_tokens"))
    categories = _rows(context.get("categories"))
    visible = _num(context.get("visible_estimated_tokens"))
    if visible is None and categories:
        visible = sum(_num(row.get("estimated_tokens")) or 0 for row in categories)
    residual = _num(context.get("unattributed_tokens"))
    if residual is None and used is not None and visible is not None:
        residual = used - visible
    compactions = _num(context.get("compactions")) or 0
    basis = context.get("basis")
    lines = [f"### Session {md(context.get('session_id'))}", "",
             f"- Agent and model: {md(context.get('agent'))}, {md(context.get('model'))}",
             f"- Observed at: {fmt_time(context.get('observed_at'))}",
             f"- Basis: {BASIS_LABELS.get(basis, md(basis)) if basis else UNKNOWN}",
             f"- Measured context: {fmt_int(used)} of {fmt_int(window)} tokens "
             f"({fmt_pct(context.get('computed_percent'))} computed occupancy"
             f"{', provider reports ' + fmt_pct(context.get('provider_percent')) if _num(context.get('provider_percent')) is not None else ''})"]
    if used is not None and window is not None:
        lines.append(f"- Free (window minus measured): {fmt_int(window - used)} tokens")
    else:
        lines.append("- Free space: Unknown")
    lines.append(f"- Compactions: {fmt_int(compactions)}; retention: {md(context.get('retention_status'))}; "
                 f"quality: {md(context.get('quality'))}")
    if used is None:
        reason = ("the session compacted after its latest measured request, so retained context is unknown"
                  if compactions else "no measured request was recorded for this context")
        lines.append(f"- Current context: Unknown, because {reason}.")
    if categories:
        lower = sum(_num(row.get("lower_tokens")) or 0 for row in categories)
        upper = sum(_num(row.get("upper_tokens")) or 0 for row in categories)
        lines.append(f"- Visible content estimate: {fmt_int(visible)} tokens (range {fmt_int(lower)} to "
                     f"{fmt_int(upper)}); method: {md(context.get('estimation_method'))}")
    if residual is not None and residual >= 0:
        lines.append(f"- Unattributed residual (measured minus visible estimate): {fmt_int(residual)} tokens. "
                     "It covers hidden system prompts, tool schemas, non-text payloads and estimation error.")
    elif residual is not None:
        lines.append(f"- Warning: the visible estimate exceeds the measured total by {fmt_int(-residual)} tokens "
                     "(estimate overrun). Categories are not rescaled to match the measurement.")
    lines.append("")
    if categories:
        body = [[md(row.get("name")), fmt_int(row.get("characters")), fmt_int(row.get("estimated_tokens")),
                 f"{fmt_int(row.get('lower_tokens'))} to {fmt_int(row.get('upper_tokens'))}"]
                for row in _by_total(categories, "estimated_tokens")]
        lines += table(["Category (estimated)", "Characters", "Estimated tokens", "Range"], body, {1, 2, 3})
    else:
        lines += ["No visible category estimate is available for the retained context.", ""]
    return lines


def _contributors_md(report: dict) -> list[str]:
    lines = ["## Tools and skills", "",
             "Ranked by visible content size and invocation counts. These are content proxies, not exact "
             "causal charges: a model request is billed for its whole prompt, not per tool.", ""]
    for key, title in (("tools", "Tools"), ("skills", "Skills")):
        rows = _rows(report.get(key))
        lines += [f"### {title}", ""]
        if not rows:
            lines += [f"No {key} were observed in this scope.", ""]
            continue
        rows = _by_total(rows, "estimated_tokens")
        body = [[md(row.get("name")), md(row.get("agent")), fmt_int(row.get("calls")),
                 fmt_int(row.get("argument_chars")), fmt_int(row.get("result_chars")),
                 fmt_int(row.get("estimated_tokens"))] for row in rows[:CONTRIBUTOR_LIMIT]]
        lines += table(["Name", "Agent", "Calls", "Argument characters", "Result characters",
                        "Estimated visible tokens"], body, {2, 3, 4, 5})
        if len(rows) > CONTRIBUTOR_LIMIT:
            lines += [f"Showing the top {CONTRIBUTOR_LIMIT} of {len(rows)}; the JSON report has all.", ""]
    return lines


def local_windows(report: dict) -> tuple[datetime, list[tuple[str, int | float, int | float | None, int | float]]] | None:
    """Local token activity in the 5 h and 7 d up to the latest recorded request."""
    supplied = report.get("local_rolling_usage")
    generated = _parse_time(report.get("generated_at"))
    if isinstance(supplied, dict) and generated:
        return generated, [(label, row.get("requests"), row.get("total_tokens"), row.get("missing_usage_requests"))
                           for key, label in (("five_hour", "5 hours"), ("seven_day", "7 days"))
                           if isinstance((row := supplied.get(key)), dict)]
    stamped = [(ts, row) for row in _rows(report.get("requests"))
               if (ts := _parse_time(row.get("timestamp"))) is not None]
    if not stamped:
        return None
    anchor = max(ts for ts, _ in stamped)
    result = []
    for label, span in (("5 hours", timedelta(hours=5)), ("7 days", timedelta(days=7))):
        requests: int | float = 0
        total: int | float | None = None
        missing: int | float = 0
        for ts, row in stamped:
            if anchor - span < ts <= anchor:
                count = _num(row.get("request_count", row.get("requests")))
                count = 1 if count is None else count
                requests += count
                value = row_total(row)
                if value is None:
                    missing += count
                else:
                    total = (total or 0) + value
        result.append((label, requests, total, missing))
    return anchor, result


def _quotas_md(report: dict) -> list[str]:
    lines = ["## Quotas", "",
             "Provider quota windows, percentages and resets are shown as observed. They are separate "
             "from local token totals and are not converted into tokens.", ""]
    quotas = _rows(report.get("quotas"))
    if quotas:
        body = [[md(row.get("agent")), md(row.get("account")), md(row.get("bucket")),
                 fmt_duration(row.get("window_minutes")), fmt_time(row.get("resets_at")),
                 fmt_pct(row.get("used_percent")), fmt_time(row.get("observed_at"))]
                for row in sorted(quotas, key=lambda row: (str(row.get("agent")), str(row.get("bucket")),
                                                           str(row.get("observed_at") or "")))]
        lines += table(["Agent", "Account", "Bucket", "Window", "Resets at", "Used", "Observed at"], body, {5})
    else:
        lines += ["No quota observations are available. Record them from the owning agent's status "
                  "interface or a numeric import.", ""]
    estimates = _rows(report.get("quota_estimates"))
    if estimates:
        body = [[md(row.get("agent")), md(row.get("bucket")), md(row.get("status")), md(row.get("reason"), 300),
                 fmt_int(row.get("samples")), fmt_int(row.get("tokens_per_point")),
                 fmt_cost(row.get("cost_per_point"), row.get("cost_per_point"))] for row in estimates]
        lines += ["### Descriptive quota estimates", ""]
        lines += table(["Agent", "Bucket", "Status", "Reason", "Samples", "Tokens per point",
                        "API-equivalent cost per point"], body, {4, 5, 6})
        lines += ["Estimates describe compatible observations only. The provider's quota formula is unknown; "
                  "they are not an allowance or a forecast.", ""]
    windows = local_windows(report)
    if windows:
        anchor, rows = windows
        lines += ["### Local activity windows", "",
                  f"Local activity measured as of "
                  f"({anchor.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}). "
                  "These rolling windows are not provider quota periods, and the 7-day window can start "
                  "before the report period.", ""]
        lines += table(["Window", "Requests", "Total tokens", "Requests missing usage"],
                       [[label, fmt_int(requests), fmt_int(total), fmt_int(missing)]
                        for label, requests, total, missing in rows], {1, 2, 3})
    return lines


def _coverage_md(report: dict) -> list[str]:
    lines = ["## Coverage", ""]
    sources = _rows(report.get("coverage"))
    if sources:
        body = [[md(str(row.get("id") or "")[:12]), md(row.get("agent")), md(row.get("device")),
                 md(row.get("origin")), md(row.get("contract")), fmt_int(row.get("files_seen")),
                 fmt_int(row.get("files_parsed")), fmt_int(row.get("rows_seen")),
                 fmt_int(row.get("malformed_rows"))] for row in sources]
        lines += table(["Source", "Agent", "Device", "Origin", "Contract", "Files seen", "Files parsed",
                        "Rows seen", "Malformed rows"], body, {5, 6, 7, 8})
    else:
        lines += ["No source coverage was recorded.", ""]
    lines += ["Data from other devices, provider-hosted tasks and deleted histories may be absent. "
              "Local totals are not the complete account history.", ""]
    warnings = _rows(report.get("warnings"))
    lines += ["### Warnings", ""]
    if not warnings:
        return lines + ["No warnings.", ""]
    counts: dict[str, list[Any]] = {}
    for row in warnings:
        entry = counts.setdefault(str(row.get("code") or UNKNOWN), [0, set()])
        entry[0] += 1
        entry[1].add(str(row.get("source_id") or ""))
    lines += table(["Code", "Occurrences", "Sources"],
                   [[md(code), fmt_int(count), fmt_int(len(sources_seen))]
                    for code, (count, sources_seen) in sorted(counts.items(), key=lambda item: -item[1][0])],
                   {1, 2})
    detail = [[md(row.get("code")), md(str(row.get("source_id") or "")[:12]), fmt_int(row.get("line"))]
              for row in warnings[:WARNING_DETAIL_LIMIT]]
    lines += table(["Code", "Source", "Line"], detail, {2})
    if len(warnings) > WARNING_DETAIL_LIMIT:
        lines += [f"Showing {WARNING_DETAIL_LIMIT} of {len(warnings)} warnings; the JSON report has all.", ""]
    return lines


def _pricing_md(report: dict) -> list[str]:
    pricing = _obj(report.get("pricing"))
    lines = ["## Pricing", "", f"> {COST_NOTE}", "",
             f"- Rate card version: {md(pricing.get('version')) if pricing.get('version') else UNKNOWN}",
             f"- Verified at: {md(pricing.get('verified_at')) if pricing.get('verified_at') else UNKNOWN}"]
    sources = pricing.get("sources")
    items = sources if isinstance(sources, list) else ([sources] if sources else [])
    for item in items:
        if isinstance(item, dict):
            parts = [f"{md(key, 40)}: {md(value, 200)}" for key, value in item.items()
                     if isinstance(value, (str, int, float)) and not isinstance(value, bool)]
            if parts:
                lines.append("- Source: " + "; ".join(parts))
        elif isinstance(item, (str, int, float)) and not isinstance(item, bool):
            lines.append(f"- Source: {md(item, 200)}")
    return lines + ["", "Requests are priced individually before aggregation. A range appears when a "
                    "billing dimension such as cache-write duration or prompt tier is unknown. Unknown "
                    "models stay unpriced.", ""]


def _methodology_md(report: dict) -> list[str]:
    method = next((context.get("estimation_method") for context in _rows(report.get("contexts"))
                   if context.get("estimation_method")), None)
    lines = ["## Methodology", "",
             "- Input tokens include cache reads and cache writes; ordinary input is input minus both.",
             "- Output tokens include reasoning. Reasoning is shown as a subset and never added again.",
             "- Total processed tokens are input plus output, summed over every request in scope. They are "
             "historical work, not the current context size.",
             "- Missing values are shown as Unknown, never as zero. Totals are known lower bounds when "
             "some requests lack counts.",
             "- Repeated snapshots and overlapping sources are reconciled before aggregation, so the same "
             "activity is counted once.",
             "- Context is anchored to the latest measured request. Category sizes are character-based "
             "estimates of recorded visible content, not provider tokenization. The unattributed residual "
             "is kept separate and categories are never rescaled to fit the measurement.",
             "- Tool and skill figures are visible content sizes and invocation counts, not causal charges.",
             "- Quota figures are provider observations with their own windows and resets."]
    if method:
        lines.append(f"- Context estimation method: {md(method, 200)}.")
    return lines + [""]


def render_markdown(report: dict) -> str:
    session = report.get("mode") == "session"
    sections = ([_context_md, _summary_md, _comparison_md, _insights_md, _contributors_md, _groups_md]
                if session else
                [_summary_md, _comparison_md, _insights_md, _groups_md, _context_md, _contributors_md])
    sections += [_quotas_md, _coverage_md, _pricing_md, _methodology_md]
    lines = _scope_md(report)
    for section in sections:
        lines += section(report)
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"
