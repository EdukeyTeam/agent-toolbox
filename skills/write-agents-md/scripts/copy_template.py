#!/usr/bin/env python3
"""Copy an AGENTS template exactly; adaptation is a separate reviewed operation."""

import argparse
import hashlib
import json
import sys
from pathlib import Path


def copy_template(workflow, project_root, scope=".", candidate=False):
    root = Path(project_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Project root must be an existing directory")
    relative_scope = Path(scope)
    if relative_scope.is_absolute() or ".." in relative_scope.parts:
        raise ValueError("Scope must be a relative directory inside the project")
    directory = (root / relative_scope).resolve(strict=True)
    if not directory.is_relative_to(root):
        raise ValueError("Scope resolves outside the project root")
    if not directory.is_dir():
        raise ValueError("Scope must be an existing directory")

    source = Path(__file__).resolve().parent.parent / "assets" / f"{workflow}-AGENTS.md"
    template = source.read_bytes()
    destination = directory / ("AGENTS.md.candidate" if candidate else "AGENTS.md")
    # Windows exclusive creation can follow a dangling file symlink.
    if destination.is_symlink() or destination.exists():
        raise FileExistsError(str(destination))
    # Exclusive creation also protects against an existing regular destination.
    with destination.open("xb") as output:
        output.write(template)
    copied = destination.read_bytes()
    if copied != template:
        raise OSError("Template byte verification failed")
    return {
        "workflow": workflow,
        "source": str(source),
        "destination": str(destination),
        "sha256": hashlib.sha256(copied).hexdigest(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", required=True, choices=("web", "desktop"))
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--scope", default=".", help="Existing project-relative directory")
    parser.add_argument("--candidate", action="store_true", help="Copy to AGENTS.md.candidate")
    arguments = parser.parse_args()
    try:
        receipt = copy_template(
            arguments.workflow, arguments.project_root, arguments.scope, arguments.candidate
        )
    except FileExistsError:
        print("Destination already exists; refusing overwrite. Use a fresh candidate location.",
              file=sys.stderr)
        return 1
    except FileNotFoundError as error:
        print(f"Required project, scope or template path does not exist: {error}",
              file=sys.stderr)
        return 1
    except (OSError, ValueError) as error:
        print(f"Cannot copy template: {error}", file=sys.stderr)
        return 1
    print(json.dumps(receipt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
