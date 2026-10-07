#!/usr/bin/env python3
"""Publish an existing map with statistics, without invoking or changing a mapper.

Low-level mapper output/cache stays outside the examined repository. Only this
explicit export step writes the readable report and its evidence sidecars.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
from pathlib import Path

ESTIMATOR = "ceil(Unicode characters / 4); a size estimate, not a model tokenizer"
IMPLEMENTATIONS = ("python", "rust", "bundle")


def _count(value, label):
    if type(value) is not int or value < 0:
        raise ValueError(f"{label} must be a nonnegative integer")
    return value


def _regular_bytes(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"missing or non-regular artifact: {path}")
    return path.read_bytes()


def _json_object(data, label):
    try:
        value = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ValueError(f"invalid {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _validate_artifacts(root, raw_bytes, metadata, inventory):
    if metadata.get("status") != "complete":
        raise ValueError("only a complete generated symbol map can be exported")
    if inventory.get("status") not in (None, "complete"):
        raise ValueError("inventory is not complete")
    for value in (metadata.get("source_root"), inventory.get("root")):
        if not isinstance(value, str) or Path(value).resolve() != root:
            raise ValueError("artifacts do not belong to the supplied repository")
    if "revision" not in metadata or "revision" not in inventory:
        raise ValueError("artifacts lack the original examined revision")
    if metadata["revision"] != inventory["revision"]:
        raise ValueError("map and inventory revision differ")
    if metadata["revision"] is not None and not isinstance(metadata["revision"], str):
        raise ValueError("revision must be a string or null")
    fingerprints = (metadata.get("working_copy_fingerprint"), inventory.get("fingerprint"))
    if any(not isinstance(value, str) or not value.strip() for value in fingerprints):
        raise ValueError("map and inventory need nonempty working-copy fingerprints")
    if fingerprints[0] != fingerprints[1]:
        raise ValueError("map and inventory working-copy fingerprints differ")
    if hashlib.sha256(raw_bytes).hexdigest() != metadata.get("map_sha256"):
        raise ValueError("raw map hash differs from map_sha256")
    coverage = metadata.get("coverage")
    if not isinstance(coverage, dict):
        raise ValueError("missing coverage metadata")
    for key in ("candidates_seen", "selected_files", "parsed_files", "definitions_found", "definitions_in_map"):
        _count(coverage.get(key), "coverage." + key)
    if not isinstance(inventory.get("files"), list) or len(inventory["files"]) != coverage["selected_files"]:
        raise ValueError("inventory files do not match selected-file coverage")
    if coverage["parsed_files"] > coverage["selected_files"] or coverage["definitions_in_map"] > coverage["definitions_found"]:
        raise ValueError("inconsistent coverage counts")
    omitted = coverage["definitions_found"] - coverage["definitions_in_map"]
    if "definitions_omitted" in coverage and _count(coverage["definitions_omitted"], "coverage.definitions_omitted") != omitted:
        raise ValueError("inconsistent omitted-definition count")
    if "selection" in metadata:
        selection = metadata["selection"]
        if not isinstance(selection, dict):
            raise ValueError("selection metadata must be an object")
        mode = selection.get("mode")
        if mode not in (None, "budget", "ranked", "all-definitions"):
            raise ValueError("unknown selection mode")
        if mode == "all-definitions" and omitted:
            raise ValueError("all-definitions map omits captured definitions")
    if "rendering" in metadata:
        rendering = metadata["rendering"]
        if not isinstance(rendering, dict) or rendering.get("format") not in ("lines", "grouped"):
            raise ValueError("invalid rendering metadata")
        clipped = rendering.get("clipped_declarations")
        if not isinstance(clipped, list) or any(not isinstance(entry, dict) for entry in clipped):
            raise ValueError("clipped declarations must be a list of objects")
        for entry in clipped:
            if not isinstance(entry.get("path"), str) or not isinstance(entry.get("reason"), str):
                raise ValueError("clipped declaration lacks path/reason")
            for key in ("line", "start_line", "end_line"):
                if key in entry:
                    _count(entry[key], "clipped declaration." + key)
    limits = metadata.get("limits")
    if not isinstance(limits, dict):
        raise ValueError("missing budget metadata")
    _count(limits.get("budget"), "limits.budget")
    if type(metadata.get("truncated")) is not bool:
        raise ValueError("missing truncation metadata")
    for key in ("skipped", "parse_failures"):
        if not isinstance(metadata.get(key), list):
            raise ValueError(f"missing {key} metadata")
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeError as exc:
        raise ValueError("raw map must be UTF-8") from exc


def _evidence_label(path, report):
    try:
        label = os.path.relpath(path, report.parent)
        return label.replace(os.sep, "/")
    except ValueError:  # Windows destinations on different drives.
        return str(path)


def _report(raw, metadata, implementation, elapsed_seconds, paths):
    coverage = metadata["coverage"]
    raw_estimate = math.ceil(len(raw) / 4)
    elapsed = "not supplied (export does not measure generation)" if elapsed_seconds is None else f"{elapsed_seconds:g} seconds (measured subprocess wall time)"
    truncation = "yes; scan or map is truncated; coverage is not complete" if metadata["truncated"] else "no; exclusions, unsupported files and parse failures still limit coverage"
    revision = json.dumps(metadata["revision"], ensure_ascii=False)
    source = json.dumps(metadata["source_root"], ensure_ascii=False)
    details = (
        "# Repository map export\n\n"
        f"- Implementation: {implementation}\n"
        f"- Examined source: {source}\n"
        f"- Examined revision: {revision}; dirty working copy: {metadata.get('dirty', 'unknown')}\n"
        f"- Candidates seen: {coverage['candidates_seen']}\n"
        f"- Files selected / parsed: {coverage['selected_files']} / {coverage['parsed_files']}\n"
        f"- Definitions found / selected: {coverage['definitions_found']} / {coverage['definitions_in_map']}\n"
        f"- Captured definitions omitted: {coverage['definitions_found'] - coverage['definitions_in_map']}\n"
        f"- Selection mode / rendering: {metadata.get('selection', {}).get('mode', 'budget')} / {metadata.get('rendering', {}).get('format', 'lines')}\n"
        f"- Declaration snippets clipped: {len(metadata.get('rendering', {}).get('clipped_declarations', []))}\n"
        f"- Map budget: {metadata['limits']['budget']} estimated tokens\n"
        f"- Truncated: {truncation}\n"
        f"- Skipped entries / parse failures: {len(metadata['skipped'])} / {len(metadata['parse_failures'])}\n"
        f"- Original generation wall time: {elapsed}\n"
        f"- Raw content: {len(raw)} Unicode characters, {len(raw.encode('utf-8'))} UTF-8 bytes, approximately {raw_estimate} tokens\n"
    )
    suffix = (
        f"- Token estimator: {ESTIMATOR}\n"
        f"- Raw map SHA-256: {metadata['map_sha256']}\n"
        f"- Evidence sidecars: {json.dumps(_evidence_label(paths["raw"], paths["report"]), ensure_ascii=False)}, "
        f"{json.dumps(_evidence_label(paths["metadata"], paths["report"]), ensure_ascii=False)}, {json.dumps(_evidence_label(paths["inventory"], paths["report"]), ensure_ascii=False)}\n\n"
        "Generation status `complete` means the selected map was published, not that every repository file or relationship was analyzed. "
        "Read the sidecars for scope, skips, parser failures and the original working-copy fingerprint.\n\n---\n\n"
    )
    estimate = 0
    while True:
        report = details + f"- Whole annotated report: approximately {estimate} tokens\n" + suffix + raw
        updated = math.ceil(len(report) / 4)
        if estimate == updated:
            return report
        estimate = updated


def _copy_exclusive(source, destination):
    """No-clobber fallback for filesystems that cannot create hard links.

    Unlike a hard-link publication, the new file is visible while copying.
    On failure, cleanup checks file identity before removing the created file.
    Concurrent exports to the same destination are unsupported.
    """
    created = None
    try:
        with destination.open("xb") as output:
            created = os.fstat(output.fileno())
            with source.open("rb") as input_file:
                shutil.copyfileobj(input_file, output)
    except FileExistsError as exc:
        raise ValueError(f"output already exists; use --force to overwrite: {destination}") from exc
    except BaseException:
        if created is not None:
            try:
                current = destination.stat(follow_symlinks=False)
                if os.path.samestat(created, current):
                    destination.unlink()
            except FileNotFoundError:
                pass
        raise


def _publish(payloads, force, report_path):
    """Stage all bytes first; publish evidence before publishing the report.

    Publication is per file, not a transaction across the evidence set.
    Hard-link publication/replacement is atomic; unsupported filesystems use
    exclusive creation, which prevents clobbering but exposes partial bytes
    during copying. After staging, --force removes the old report before any
    evidence replacement, so interruption cannot leave a stale readable map.
    """
    temporary_paths = []
    try:
        for path, payload in payloads:
            with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix=".repo-map-export-", delete=False) as handle:
                temporary = Path(handle.name)
                temporary_paths.append((temporary, path))
                handle.write(payload)
        if force:
            report_path.unlink(missing_ok=True)
        for temporary, path in temporary_paths:
            if force:
                os.replace(temporary, path)
            else:
                try:
                    os.link(temporary, path)
                except FileExistsError as exc:
                    raise ValueError(f"output already exists; use --force to overwrite: {path}") from exc
                except OSError as exc:
                    unsupported = exc.errno in (errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EXDEV, errno.EPERM)
                    unsupported = unsupported or getattr(exc, "winerror", None) in (1, 50)
                    if not unsupported:
                        raise
                    _copy_exclusive(temporary, path)
                temporary.unlink()
    finally:
        for temporary, _ in temporary_paths:
            temporary.unlink(missing_ok=True)

def export_map(repository, artifact_dir, *, implementation, output_file=None, evidence_dir=None, elapsed_seconds=None, force=False):
    """Validate and export a complete map; return the four published paths."""
    if implementation not in IMPLEMENTATIONS:
        raise ValueError(f"implementation must be one of {', '.join(IMPLEMENTATIONS)}")
    if elapsed_seconds is not None and (type(elapsed_seconds) not in (int, float) or not math.isfinite(elapsed_seconds) or elapsed_seconds < 0):
        raise ValueError("elapsed seconds must be a finite nonnegative measured duration")
    root = Path(repository).resolve(strict=True)
    artifacts = Path(artifact_dir).resolve(strict=True)
    if not root.is_dir() or not artifacts.is_dir():
        raise ValueError("repository and artifact directory must be directories")
    if artifacts.is_relative_to(root):
        raise ValueError("artifact directory must be outside the source repository")
    output = Path(output_file) if output_file is not None else root / "docs/repo-maps" / f"repo-map.{implementation}.md"
    output = output.absolute()
    if output.is_symlink():
        raise ValueError("output file must not be a symlink")
    output = output.resolve()
    if output.is_relative_to(artifacts):
        raise ValueError("exports must not modify the artifact directory")
    base = output.with_suffix("")
    evidence = Path(evidence_dir) if evidence_dir is not None else output.parent / "artifacts" / base.name
    if evidence.is_symlink() or (evidence.exists() and not evidence.is_dir()):
        raise ValueError("evidence directory must be an ordinary directory")
    evidence = evidence.resolve()
    if evidence.is_relative_to(artifacts):
        raise ValueError("exports must not modify the artifact directory")
    paths = {
        "report": output, "raw": evidence / (base.name + ".raw.md"),
        "metadata": evidence / (base.name + ".meta.json"),
        "inventory": evidence / (base.name + ".inventory.json"),
    }
    if len(set(paths.values())) != 4:
        raise ValueError("report filename collides with an evidence sidecar")
    for path in paths.values():
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError(f"output must be an ordinary file: {path}")
        if path.exists() and not force:
            raise ValueError(f"output already exists; use --force to overwrite: {path}")
    raw_bytes = _regular_bytes(artifacts / "repo-map.md")
    metadata = _json_object(_regular_bytes(artifacts / "map.meta.json"), "map metadata")
    inventory_bytes = _regular_bytes(artifacts / "inventory.json")
    inventory = _json_object(inventory_bytes, "inventory")
    raw = _validate_artifacts(root, raw_bytes, metadata, inventory)
    report = _report(raw, metadata, implementation, elapsed_seconds, paths)
    report_bytes = report.encode("utf-8")
    # map_sha256 and estimated_tokens retain their original raw-map semantics.
    metadata["export"] = {
        "schema_version": 1, "implementation": implementation, "artifact_dir": str(artifacts),
        "report_file": str(output), "raw_file": str(paths["raw"]), "evidence_dir": str(evidence),
        "raw_unicode_characters": len(raw), "raw_utf8_bytes": len(raw_bytes),
        "raw_estimated_tokens": math.ceil(len(raw) / 4),
        "report_unicode_characters": len(report), "report_utf8_bytes": len(report_bytes),
        "report_estimated_tokens": math.ceil(len(report) / 4), "estimator": ESTIMATOR,
        "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
    }
    if elapsed_seconds is not None:
        metadata["export"]["generation_elapsed_seconds"] = elapsed_seconds
    metadata_bytes = (json.dumps(metadata, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    payloads = [(paths["raw"], raw_bytes), (paths["inventory"], inventory_bytes),
                (paths["metadata"], metadata_bytes), (paths["report"], report_bytes)]
    # No output directory or file is created until every input has been checked.
    output.parent.mkdir(parents=True, exist_ok=True)
    evidence.mkdir(parents=True, exist_ok=True)
    _publish(payloads, force, paths["report"])
    return paths


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", help="original examined repository")
    parser.add_argument("--artifact-dir", required=True, help="existing raw mapper artifacts outside the repository")
    parser.add_argument("--implementation", required=True, choices=IMPLEMENTATIONS)
    parser.add_argument("--output-file", help="report filename; default: <repository>/docs/repo-maps/repo-map.<implementation>.md")
    parser.add_argument("--evidence-dir", help="sidecar directory; default: <report-parent>/artifacts/<report-stem>")
    parser.add_argument("--elapsed-seconds", type=float, help="original measured subprocess wall time; do not use export duration")
    parser.add_argument("--force", action="store_true", help="explicitly replace existing report and sidecars")
    args = parser.parse_args(argv)
    try:
        paths = export_map(args.repository, args.artifact_dir, implementation=args.implementation,
                           output_file=args.output_file, evidence_dir=args.evidence_dir, elapsed_seconds=args.elapsed_seconds, force=args.force)
    except (OSError, ValueError) as exc:
        print(f"repo map export failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({key: str(path) for key, path in paths.items()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
