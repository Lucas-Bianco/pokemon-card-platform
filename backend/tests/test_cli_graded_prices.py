"""T4: CLI refresh-graded-prices — the no-key message prints cleanly and exits 0.

The CLI has historically had near-0% coverage; per the task we keep this minimal
(a single invocation) rather than over-investing. The no-key path is the
default state and the one users hit first, so it is the one worth pinning.
"""

from __future__ import annotations

from cardplatform.cli import main


def test_refresh_graded_prices_without_key_prints_message_and_exits_zero(capsys, monkeypatch, tmp_path):
    # No CARDPLATFORM_GRADED_PRICE_API_KEY in the ambient env (conftest strips
    # them); point data_dir at a tmp path so Database() never touches the real
    # repo data/cardplatform.sqlite3.
    monkeypatch.setenv("CARDPLATFORM_DATA_DIR", str(tmp_path))
    rc = main(["refresh-graded-prices", "base1-4"])

    captured = capsys.readouterr()
    assert rc == 0
    assert "graded-price API key not set" in captured.out
    assert "CARDPLATFORM_GRADED_PRICE_API_KEY" in captured.out