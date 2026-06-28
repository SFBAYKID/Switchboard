"""Export FastAPI's generated OpenAPI document to the committed spec artifact.

The OpenAPI spec is the source of truth for the internal API shape (charter
Principle 1). Switchboard is code-first, spec-pinned (postman-setup.md): endpoints +
Pydantic models are authored in FastAPI, then the generated spec is EXPORTED and
COMMITTED to `spec/openapi.json`. CI regenerates and fails on drift (a git diff
check), so contract changes are explicit and reviewable, and Postman imports the
committed file.

Usage (from the repo root):
    python scripts/export_openapi.py

Importing the app does not read secrets or run the lifespan, so this works without a
configured environment.
"""

from __future__ import annotations

import json
import pathlib

from switchboard.api.main import app

# Repo root is the parent of this scripts/ directory.
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SPEC_PATH = _REPO_ROOT / "spec" / "openapi.json"


def export() -> pathlib.Path:
    """Write the generated OpenAPI document to spec/openapi.json (stable formatting)."""

    spec = app.openapi()
    _SPEC_PATH.parent.mkdir(parents=True, exist_ok=True)
    # sort_keys + trailing newline => stable, diff-friendly output for the CI check.
    _SPEC_PATH.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n")
    return _SPEC_PATH


if __name__ == "__main__":
    path = export()
    print(f"Wrote {path}")
