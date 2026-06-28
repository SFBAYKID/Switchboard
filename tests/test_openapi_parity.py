"""OpenAPI contract parity — the committed spec must match the running app.

Charter Principle 1: the OpenAPI spec is the source of truth. The committed
spec/openapi.json must not lie about the running service. If this fails, regenerate
with `python scripts/export_openapi.py` and review the diff.
"""

from __future__ import annotations

import json
import pathlib

from switchboard.api.main import app

_SPEC_PATH = pathlib.Path(__file__).resolve().parents[1] / "spec" / "openapi.json"


def test_committed_spec_matches_running_app() -> None:
    committed = json.loads(_SPEC_PATH.read_text())
    generated = app.openapi()
    assert generated == committed, (
        "spec/openapi.json is stale — run `python scripts/export_openapi.py` "
        "and commit the result."
    )
