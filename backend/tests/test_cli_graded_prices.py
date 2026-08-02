"""T4: CLI refresh-graded-prices — the no-key message prints cleanly and exits 0.

The CLI has historically had near-0% coverage; per the task we keep this minimal
(a single invocation) rather than over-investing. The no-key path is the
default state and the one users hit first, so it is the one worth pinning.
"""

from __future__ import annotations

from cardplatform.cli import main
from cardplatform.config import Settings
from cardplatform.db import session as session_module


def test_refresh_graded_prices_without_key_prints_message_and_exits_zero(capsys, monkeypatch, tmp_path):
    # refresh_graded_prices constructs Database() with no args, which falls back
    # to `default_settings` — the name session.py bound to `cardplatform.config
    # .settings` AT IMPORT TIME. setenv("CARDPLATFORM_DATA_DIR", ...) is inert
    # because that binding already happened, so the test would open/migrate the
    # real data/cardplatform.sqlite3. Patch the binding session.py actually reads.
    monkeypatch.setattr(session_module, "default_settings", Settings(data_dir=tmp_path))
    rc = main(["refresh-graded-prices", "base1-4"])

    captured = capsys.readouterr()
    assert rc == 0
    assert "graded-price API key not set" in captured.out
    assert "CARDPLATFORM_GRADED_PRICE_API_KEY" in captured.out