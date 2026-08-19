"""Tests for `cardplatform find-sealed-deals` CLI (Phase 05c)."""
from __future__ import annotations

import pytest

from cardplatform.cli import main
from cardplatform.config import Settings


def test_find_sealed_deals_no_key_prints_honest_message(monkeypatch, capsys):
    # Real Settings instance (not a shim) so the schema can't drift silently.
    monkeypatch.setattr(
        "cardplatform.cli.settings",
        Settings(
            listings_api_key=None,
            sealed_flip_min_abs=20.0,
            sealed_flip_min_pct=0.05,
            sealed_sold_comp_limit=10,
        ),
    )
    rc = main(["find-sealed-deals", "--query", "booster box"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "no listings source key" in out.lower() or "set" in out.lower()


def test_find_sealed_deals_missing_query_exits_nonzero(monkeypatch, capsys):
    monkeypatch.setattr(
        "cardplatform.cli.settings",
        Settings(listings_api_key="k"),
    )
    # argparse raises SystemExit(2) for a missing required arg (the existing
    # main() does not catch it); a non-zero exit is the honest signal.
    with pytest.raises(SystemExit) as exc:
        main(["find-sealed-deals"])
    assert exc.value.code != 0
