from cardplatform.cli import main
from cardplatform.config import Settings


class _DB:
    """Stand-in so the CLI handler uses a fresh temp DB instead of the real data/ one.
    Mirrors the Database interface the handlers use: create_all(), settings, session()."""

    def __init__(self, settings):
        from cardplatform.db.session import Database
        self._real = Database(settings)

    def create_all(self):
        self._real.create_all()

    @property
    def settings(self):
        return self._real.settings

    def session(self):
        return self._real.session()


def _settings(tmp_path, monkeypatch, **kw):
    s = Settings(data_dir=tmp_path, listings_api_key="app-id", sealed_sold_comp_limit=10, **kw)
    monkeypatch.setattr("cardplatform.cli.settings", s)
    monkeypatch.setattr("cardplatform.cli.Database", lambda: _DB(s))
    return s


def test_log_sealed_purchase_creates_and_prints(tmp_path, monkeypatch, capsys):
    _settings(tmp_path, monkeypatch)
    rc = main([
        "log-sealed-purchase", "--query", "scarlet violet booster box",
        "--quantity", "2", "--cost", "120",
    ])
    assert rc == 0
    out = capsys.readouterr().out.lower()
    assert "logged" in out
    assert "scarlet violet booster box" in out


def test_log_sealed_purchase_rejects_bad_cost(tmp_path, monkeypatch, capsys):
    _settings(tmp_path, monkeypatch)
    rc = main(["log-sealed-purchase", "--query", "box", "--cost", "-5"])
    # ValueError -> handler prints message + returns non-zero (do not crash).
    assert rc != 0
    assert "cost" in capsys.readouterr().out.lower()


def test_list_sealed_ledger_empty(tmp_path, monkeypatch, capsys):
    _settings(tmp_path, monkeypatch)
    rc = main(["list-sealed-ledger"])
    assert rc == 0
    assert "no purchases" in capsys.readouterr().out.lower()


def test_valuate_sealed_ledger_no_key(tmp_path, monkeypatch, capsys):
    s = Settings(data_dir=tmp_path, listings_api_key=None, sealed_sold_comp_limit=10)
    monkeypatch.setattr("cardplatform.cli.settings", s)
    monkeypatch.setattr("cardplatform.cli.Database", lambda: _DB(s))
    rc = main(["log-sealed-purchase", "--query", "box", "--cost", "10"])
    assert rc == 0
    rc = main(["valuate-sealed-ledger"])
    assert rc == 0
    out = capsys.readouterr().out.lower()
    assert "set cardplatform_listings_api_key" in out