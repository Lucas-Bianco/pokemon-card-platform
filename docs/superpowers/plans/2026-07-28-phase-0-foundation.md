# Phase 0 — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the local data foundation — a card catalog of all 20,479 Pokémon cards, a resilient price layer, and a collection store — that every later phase reads from.

**Architecture:** A Python package (`cardplatform`) backed by SQLite via SQLAlchemy. The catalog is bulk-loaded from the `pokemon-tcg-data` JSON dump (not the flaky API). Prices come from `pokemontcg.io` behind a provider interface, written as immutable timestamped snapshots so history accumulates from day one. A small FastAPI app exposes reads. No recognition or ML in this phase.

**Tech Stack:** Python 3.12, SQLAlchemy 2.x, Pydantic Settings, httpx, tenacity, FastAPI, pytest.

---

## Scope note

The approved spec covers Phase 0 **and** Phase 1. This plan implements **Phase 0 only**. That is
sequencing, not a scope reduction — Phase 1 (rectification, embeddings, OCR, fusion, UI) gets its own
plan immediately after, and it depends on the catalog and image URLs this phase produces. Phase 0
ships independently useful software: a queryable local card database with live pricing.

## Deviation from spec: SQLite instead of Postgres

The spec (§4.4) names Postgres. **This plan uses SQLite instead**, for Phase 0:

- Docker is not installed on the target machine, and a native Postgres install is meaningful setup
  friction for a **single-user, local-first** app (§4.2).
- SQLite handles 20k cards and price history with no measurable difficulty at this scale.
- Zero configuration: no server, no port, no credentials.

**This is reversible by design.** All access goes through SQLAlchemy ORM with no SQLite-specific SQL,
so switching to Postgres later is a connection-string change plus a migration. If Phase 5's deal
sniper needs concurrent writers, revisit then.

**Flag for Lucas:** if you'd rather run Postgres from the start, say so before Task 4 — that is the
last cheap moment to change it.

## Verified facts this plan depends on

Confirmed live on 2026-07-28. Do not re-derive:

| Fact | Value |
|---|---|
| Catalog dump | `https://github.com/PokemonTCG/pokemon-tcg-data`, `master` branch |
| Sets file | `sets/en.json` — flat array, **174 sets** |
| Cards files | `cards/en/<set_id>.json` — flat array per set (e.g. `base1.json` = 102 cards) |
| Card image URLs | `images.small` and `images.large` on each card |
| Pricing in dump | **Absent.** Prices only come from the live API |
| Price API shape | `GET /v2/cards/{id}` → `tcgplayer.prices.{variant}.{low,mid,high,market}` |
| Price variants | Per-printing keys, e.g. `holofoil`, `reverseHolofoil`, `normal`, `1stEdition` |
| API reliability | **~17% success rate.** Retries are mandatory, not optional |
| Dump file encoding | **UTF-8** — and Windows Python defaults to cp1252, which corrupts `é` |

---

## File structure

```
backend/
  pyproject.toml
  src/cardplatform/
    __init__.py
    config.py              # Settings: paths, URLs, tunables
    db/
      __init__.py
      models.py            # SQLAlchemy models: Set, Card, PriceSnapshot, CollectionItem
      session.py           # Engine + session factory
    catalog/
      __init__.py
      dump.py              # Download the JSON dump from GitHub
      loader.py            # Parse dump -> DB rows (UTF-8 safe)
    prices/
      __init__.py
      provider.py          # PriceProvider protocol + PriceQuote dataclass
      pokemontcg.py        # pokemontcg.io implementation, retry-hardened
      service.py           # Snapshot writing + latest-price queries
    collection/
      __init__.py
      store.py             # Add/remove/list collection items, valuation
    api.py                 # FastAPI read endpoints
    cli.py                 # Command-line entry points
  tests/
    conftest.py            # In-memory DB fixture
    test_config.py
    test_models.py
    test_dump.py
    test_loader.py
    test_price_provider.py
    test_price_service.py
    test_collection.py
    test_api.py
```

Each module has one responsibility. `prices/provider.py` defines the interface that keeps
pokemontcg.io swappable (spec §3.1, consequence 6).

---

## Task 1: Environment setup

No tests — this is verification of the machine. Do not skip; both checks catch failures that are
silent or deeply confusing later.

**Files:** none created.

- [ ] **Step 1: Install Python 3.12**

The machine has only Python 3.14, which lacks reliable wheels for PyTorch, FAISS, and PaddleOCR
(needed in Phase 1). Install 3.12 alongside it — this does not remove 3.14.

```bash
winget install --id Python.Python.3.12 -e
```

- [ ] **Step 2: Verify 3.12 is available**

Open a **new** terminal (PATH is stale in existing ones), then run:

```bash
py --list
```

Expected: a line containing `-V:3.12`. If absent, the install failed — do not continue.

- [ ] **Step 3: Create the virtual environment**

```bash
py -3.12 -m venv C:\ClaudeKnowledge\backend\.venv
```

- [ ] **Step 4: Verify the venv reports 3.12**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe --version
```

Expected: `Python 3.12.x`. If it says 3.14, the wrong interpreter built the venv — delete
`backend\.venv` and redo Step 3.

- [ ] **Step 5: Install PyTorch with CUDA 12.8 (Blackwell support)**

The RTX 5070 Ti is Blackwell (sm_120). Default PyTorch wheels do not support it and will silently
fall back to CPU.

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\pip.exe install torch --index-url https://download.pytorch.org/whl/cu128
```

- [ ] **Step 6: Verify the GPU is actually visible to PyTorch**

This is the check that catches the silent CPU fallback.

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -c "import torch; print('cuda:', torch.cuda.is_available()); print('device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NONE'); print('capability:', torch.cuda.get_device_capability(0) if torch.cuda.is_available() else 'NONE')"
```

Expected output:
```
cuda: True
device: NVIDIA GeForce RTX 5070 Ti
capability: (12, 0)
```

If `cuda: False`, or capability is not `(12, 0)`, stop. Phase 1 will be unusably slow. Reinstall with
the `cu128` index URL above.

---

## Task 2: Project scaffolding

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/src/cardplatform/__init__.py`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/test_smoke.py`

- [ ] **Step 1: Write `backend/pyproject.toml`**

```toml
[project]
name = "cardplatform"
version = "0.1.0"
description = "Local-first Pokemon card recognition and valuation platform"
requires-python = ">=3.12,<3.13"
dependencies = [
    "sqlalchemy>=2.0",
    "pydantic>=2.7",
    "pydantic-settings>=2.3",
    "httpx>=0.27",
    "tenacity>=8.3",
    "fastapi>=0.111",
    "uvicorn>=0.30",
]

[project.optional-dependencies]
dev = ["pytest>=8.2", "pytest-cov>=5.0", "respx>=0.21"]

[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

- [ ] **Step 2: Create the package and test markers**

`backend/src/cardplatform/__init__.py`:

```python
"""Local-first Pokemon card recognition and valuation platform."""

__version__ = "0.1.0"
```

`backend/tests/__init__.py`: create as an empty file.

- [ ] **Step 3: Write the smoke test**

`backend/tests/test_smoke.py`:

```python
import sys

import cardplatform


def test_package_imports():
    assert cardplatform.__version__ == "0.1.0"


def test_running_on_python_312():
    assert sys.version_info[:2] == (3, 12)
```

- [ ] **Step 4: Install the project in editable mode**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\pip.exe install -e "C:\ClaudeKnowledge\backend[dev]"
```

- [ ] **Step 5: Run the smoke test**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_smoke.py -v
```

Expected: 2 passed. `test_running_on_python_312` failing means the wrong venv is active.

- [ ] **Step 6: Commit**

```bash
git add backend/pyproject.toml backend/src backend/tests && git commit -m "feat: scaffold cardplatform package with pytest"
```

---

## Task 3: Configuration module

**Files:**
- Create: `backend/src/cardplatform/config.py`
- Test: `backend/tests/test_config.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_config.py`:

```python
from pathlib import Path

from cardplatform.config import Settings


def test_defaults_point_at_data_dir():
    s = Settings()
    assert s.data_dir.name == "data"
    assert s.db_path.suffix == ".sqlite3"
    assert s.db_path.parent == s.data_dir


def test_database_url_is_sqlite():
    s = Settings()
    assert s.database_url.startswith("sqlite:///")


def test_dump_urls_are_wellformed():
    s = Settings()
    assert s.dump_sets_url.endswith("/sets/en.json")
    assert "pokemon-tcg-data" in s.dump_sets_url
    assert s.dump_cards_url("base1").endswith("/cards/en/base1.json")


def test_env_override(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CARDPLATFORM_DATA_DIR", str(tmp_path))
    s = Settings()
    assert s.data_dir == tmp_path
```

- [ ] **Step 2: Run it to verify it fails**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_config.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'cardplatform.config'`

- [ ] **Step 3: Write the implementation**

`backend/src/cardplatform/config.py`:

```python
"""Application settings. Override any field with a CARDPLATFORM_ prefixed env var."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DUMP_BASE = "https://raw.githubusercontent.com/PokemonTCG/pokemon-tcg-data/master"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CARDPLATFORM_", extra="ignore")

    data_dir: Path = Field(default=_REPO_ROOT / "data")

    # Catalog dump (GitHub). Used instead of the API, which fails ~83% of requests.
    dump_base_url: str = Field(default=_DUMP_BASE)

    # Live price API. Only used for prices; never for bulk catalog loading.
    api_base_url: str = Field(default="https://api.pokemontcg.io/v2")
    api_key: str | None = Field(default=None)

    # The API is unreliable, so retry generously.
    http_timeout_seconds: float = Field(default=30.0)
    http_max_attempts: int = Field(default=8)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "cardplatform.sqlite3"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.db_path}"

    @property
    def dump_sets_url(self) -> str:
        return f"{self.dump_base_url}/sets/en.json"

    def dump_cards_url(self, set_id: str) -> str:
        return f"{self.dump_base_url}/cards/en/{set_id}.json"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
```

- [ ] **Step 4: Run the tests**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_config.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/cardplatform/config.py backend/tests/test_config.py && git commit -m "feat: add settings module with env overrides"
```

---

## Task 4: Database models — Set and Card

**Files:**
- Create: `backend/src/cardplatform/db/__init__.py`
- Create: `backend/src/cardplatform/db/models.py`
- Test: `backend/tests/test_models.py`
- Create: `backend/tests/conftest.py`

- [ ] **Step 1: Write the test fixture**

`backend/tests/conftest.py`:

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from cardplatform.db.models import Base


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def db(engine) -> Session:
    factory = sessionmaker(bind=engine)
    with factory() as session:
        yield session
```

- [ ] **Step 2: Write the failing test**

`backend/tests/test_models.py`:

```python
from cardplatform.db.models import Card, CardSet


def test_can_persist_a_set(db):
    s = CardSet(
        id="base1",
        name="Base",
        series="Base",
        printed_total=102,
        total=102,
        ptcgo_code="BS",
        release_date="1999/01/09",
        image_symbol="https://images.pokemontcg.io/base1/symbol.png",
        image_logo="https://images.pokemontcg.io/base1/logo.png",
    )
    db.add(s)
    db.commit()

    got = db.get(CardSet, "base1")
    assert got.name == "Base"
    assert got.printed_total == 102


def test_can_persist_a_card_linked_to_set(db):
    db.add(CardSet(id="base1", name="Base", series="Base", printed_total=102, total=102))
    db.add(
        Card(
            id="base1-4",
            set_id="base1",
            name="Charizard",
            number="4",
            rarity="Rare Holo",
            supertype="Pokémon",
            subtypes=["Stage 2"],
            artist="Mitsuhiro Arita",
            image_small="https://images.pokemontcg.io/base1/4.png",
            image_large="https://images.pokemontcg.io/base1/4_hires.png",
        )
    )
    db.commit()

    card = db.get(Card, "base1-4")
    assert card.name == "Charizard"
    assert card.card_set.name == "Base"
    assert card.subtypes == ["Stage 2"]


def test_accented_names_survive_roundtrip(db):
    """Guards the cp1252 mojibake bug: 'Pokémon' must not become 'PokÃ©mon'."""
    db.add(CardSet(id="base1", name="Base", series="Base", printed_total=102, total=102))
    db.add(Card(id="base1-4", set_id="base1", name="Charizard", number="4", supertype="Pokémon"))
    db.commit()
    db.expunge_all()

    card = db.get(Card, "base1-4")
    assert card.supertype == "Pokémon"
    assert "Ã" not in card.supertype
```

- [ ] **Step 3: Run it to verify it fails**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_models.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'cardplatform.db'`

- [ ] **Step 4: Write the implementation**

`backend/src/cardplatform/db/__init__.py`: create as an empty file.

`backend/src/cardplatform/db/models.py`:

```python
"""SQLAlchemy models for catalog, prices, and collection."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CardSet(Base):
    """A Pokemon TCG set. Named CardSet because `Set` shadows typing.Set."""

    __tablename__ = "card_sets"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, index=True)
    series: Mapped[str | None] = mapped_column(String, default=None)
    printed_total: Mapped[int | None] = mapped_column(Integer, default=None)
    total: Mapped[int | None] = mapped_column(Integer, default=None)
    ptcgo_code: Mapped[str | None] = mapped_column(String, default=None)
    release_date: Mapped[str | None] = mapped_column(String, index=True, default=None)
    image_symbol: Mapped[str | None] = mapped_column(String, default=None)
    image_logo: Mapped[str | None] = mapped_column(String, default=None)

    cards: Mapped[list[Card]] = relationship(back_populates="card_set")


class Card(Base):
    __tablename__ = "cards"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    set_id: Mapped[str] = mapped_column(ForeignKey("card_sets.id"), index=True)
    name: Mapped[str] = mapped_column(String, index=True)
    number: Mapped[str] = mapped_column(String, index=True)
    rarity: Mapped[str | None] = mapped_column(String, default=None)
    supertype: Mapped[str | None] = mapped_column(String, default=None)
    subtypes: Mapped[list[str] | None] = mapped_column(JSON, default=None)
    artist: Mapped[str | None] = mapped_column(String, default=None)
    national_pokedex_numbers: Mapped[list[int] | None] = mapped_column(JSON, default=None)
    image_small: Mapped[str | None] = mapped_column(String, default=None)
    image_large: Mapped[str | None] = mapped_column(String, default=None)

    card_set: Mapped[CardSet] = relationship(back_populates="cards")


class PriceSnapshot(Base):
    """Immutable point-in-time price observation.

    Rows are never updated. History accrues so Phase 2 can chart P/L and Phase 5 can
    detect underpriced listings against a baseline.
    """

    __tablename__ = "price_snapshots"
    __table_args__ = (
        UniqueConstraint("card_id", "source", "variant", "source_updated_at", name="uq_snapshot"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    card_id: Mapped[str] = mapped_column(ForeignKey("cards.id"), index=True)
    source: Mapped[str] = mapped_column(String, index=True)  # "tcgplayer" | "cardmarket"
    variant: Mapped[str] = mapped_column(String, index=True)  # "holofoil", "reverseHolofoil", ...
    low: Mapped[float | None] = mapped_column(Float, default=None)
    mid: Mapped[float | None] = mapped_column(Float, default=None)
    high: Mapped[float | None] = mapped_column(Float, default=None)
    market: Mapped[float | None] = mapped_column(Float, default=None)
    source_updated_at: Mapped[str | None] = mapped_column(String, default=None)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class CollectionItem(Base):
    __tablename__ = "collection_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    card_id: Mapped[str] = mapped_column(ForeignKey("cards.id"), index=True)
    variant: Mapped[str] = mapped_column(String, default="normal")
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    condition: Mapped[str | None] = mapped_column(String, default=None)
    acquired_price: Mapped[float | None] = mapped_column(Float, default=None)
    acquired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    notes: Mapped[str | None] = mapped_column(String, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    card: Mapped[Card] = relationship()
```

- [ ] **Step 5: Run the tests**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_models.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/src/cardplatform/db backend/tests/test_models.py backend/tests/conftest.py && git commit -m "feat: add catalog, price, and collection models"
```

---

## Task 5: Database session factory

**Files:**
- Create: `backend/src/cardplatform/db/session.py`
- Test: `backend/tests/test_session.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_session.py`:

```python
from pathlib import Path

from sqlalchemy import inspect

from cardplatform.config import Settings
from cardplatform.db.session import Database


def test_init_creates_file_and_tables(tmp_path: Path):
    settings = Settings(data_dir=tmp_path)
    database = Database(settings)
    database.create_all()

    assert settings.db_path.exists()
    tables = set(inspect(database.engine).get_table_names())
    assert {"cards", "card_sets", "price_snapshots", "collection_items"} <= tables


def test_session_is_usable(tmp_path: Path):
    from cardplatform.db.models import CardSet

    database = Database(Settings(data_dir=tmp_path))
    database.create_all()

    with database.session() as s:
        s.add(CardSet(id="sv1", name="Scarlet & Violet", series="Scarlet & Violet"))
        s.commit()

    with database.session() as s:
        assert s.get(CardSet, "sv1").name == "Scarlet & Violet"
```

- [ ] **Step 2: Run it to verify it fails**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_session.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'cardplatform.db.session'`

- [ ] **Step 3: Write the implementation**

`backend/src/cardplatform/db/session.py`:

```python
"""Engine and session management."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from cardplatform.config import Settings, settings as default_settings
from cardplatform.db.models import Base


class Database:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or default_settings
        self.settings.ensure_dirs()
        self.engine: Engine = create_engine(self.settings.database_url, future=True)
        _enable_sqlite_pragmas(self.engine)
        self._factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        with self._factory() as s:
            yield s


def _enable_sqlite_pragmas(engine: Engine) -> None:
    """WAL improves concurrent reads; foreign_keys is off by default in SQLite."""

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()
```

- [ ] **Step 4: Run the tests**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_session.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/cardplatform/db/session.py backend/tests/test_session.py && git commit -m "feat: add database session factory with sqlite pragmas"
```

---

## Task 6: Catalog dump downloader

**Files:**
- Create: `backend/src/cardplatform/catalog/__init__.py`
- Create: `backend/src/cardplatform/catalog/dump.py`
- Test: `backend/tests/test_dump.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_dump.py`:

```python
import json
from pathlib import Path

import httpx
import respx

from cardplatform.catalog.dump import DumpClient
from cardplatform.config import Settings


@respx.mock
def test_fetch_sets_decodes_utf8(tmp_path: Path):
    """The dump is UTF-8. Windows defaults to cp1252, which would corrupt this."""
    payload = [{"id": "base1", "name": "Base", "series": "Base"}]
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    settings = Settings(data_dir=tmp_path)
    respx.get(settings.dump_sets_url).mock(return_value=httpx.Response(200, content=body))

    sets = DumpClient(settings).fetch_sets()

    assert sets[0]["id"] == "base1"


@respx.mock
def test_accented_characters_are_not_mojibaked(tmp_path: Path):
    payload = [{"id": "base1-4", "name": "Charizard", "supertype": "Pokémon"}]
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    settings = Settings(data_dir=tmp_path)
    respx.get(settings.dump_cards_url("base1")).mock(return_value=httpx.Response(200, content=body))

    cards = DumpClient(settings).fetch_cards("base1")

    assert cards[0]["supertype"] == "Pokémon"
    assert "Ã" not in cards[0]["supertype"]


@respx.mock
def test_missing_set_file_returns_empty_list(tmp_path: Path):
    settings = Settings(data_dir=tmp_path)
    respx.get(settings.dump_cards_url("nope")).mock(return_value=httpx.Response(404))

    assert DumpClient(settings).fetch_cards("nope") == []
```

- [ ] **Step 2: Run it to verify it fails**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_dump.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'cardplatform.catalog'`

- [ ] **Step 3: Write the implementation**

`backend/src/cardplatform/catalog/__init__.py`: create as an empty file.

`backend/src/cardplatform/catalog/dump.py`:

```python
"""Fetches the pokemon-tcg-data JSON dump from GitHub.

Used instead of api.pokemontcg.io for catalog data: on 2026-07-28 the API returned
HTTP 500 for 10 of 12 requests, while raw.githubusercontent.com served reliably.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from cardplatform.config import Settings, settings as default_settings


class DumpClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or default_settings

    def fetch_sets(self) -> list[dict[str, Any]]:
        return self._get_json(self.settings.dump_sets_url)

    def fetch_cards(self, set_id: str) -> list[dict[str, Any]]:
        return self._get_json(self.settings.dump_cards_url(set_id))

    def _get_json(self, url: str) -> list[dict[str, Any]]:
        response = httpx.get(url, timeout=self.settings.http_timeout_seconds, follow_redirects=True)
        if response.status_code == 404:
            return []
        response.raise_for_status()
        # Decode explicitly: httpx may guess, and Windows' cp1252 default turns 'é' into 'Ã©'.
        return json.loads(response.content.decode("utf-8"))
```

- [ ] **Step 4: Run the tests**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_dump.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/cardplatform/catalog backend/tests/test_dump.py && git commit -m "feat: add catalog dump downloader with explicit utf-8 decoding"
```

---

## Task 7: Catalog loader

**Files:**
- Create: `backend/src/cardplatform/catalog/loader.py`
- Test: `backend/tests/test_loader.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_loader.py`:

```python
from cardplatform.catalog.loader import CatalogLoader
from cardplatform.db.models import Card, CardSet

SET_PAYLOAD = [
    {
        "id": "base1",
        "name": "Base",
        "series": "Base",
        "printedTotal": 102,
        "total": 102,
        "ptcgoCode": "BS",
        "releaseDate": "1999/01/09",
        "images": {
            "symbol": "https://images.pokemontcg.io/base1/symbol.png",
            "logo": "https://images.pokemontcg.io/base1/logo.png",
        },
    }
]

CARD_PAYLOAD = [
    {
        "id": "base1-4",
        "name": "Charizard",
        "number": "4",
        "rarity": "Rare Holo",
        "supertype": "Pokémon",
        "subtypes": ["Stage 2"],
        "artist": "Mitsuhiro Arita",
        "nationalPokedexNumbers": [6],
        "images": {
            "small": "https://images.pokemontcg.io/base1/4.png",
            "large": "https://images.pokemontcg.io/base1/4_hires.png",
        },
    }
]


class FakeDump:
    def __init__(self, sets, cards_by_set):
        self._sets = sets
        self._cards = cards_by_set

    def fetch_sets(self):
        return self._sets

    def fetch_cards(self, set_id):
        return self._cards.get(set_id, [])


def test_loads_sets_and_cards(db):
    loader = CatalogLoader(db, FakeDump(SET_PAYLOAD, {"base1": CARD_PAYLOAD}))

    result = loader.load_all()

    assert result.sets_loaded == 1
    assert result.cards_loaded == 1
    card = db.get(Card, "base1-4")
    assert card.name == "Charizard"
    assert card.supertype == "Pokémon"
    assert card.image_small.endswith("/base1/4.png")
    assert card.national_pokedex_numbers == [6]
    assert db.get(CardSet, "base1").ptcgo_code == "BS"


def test_load_is_idempotent(db):
    loader = CatalogLoader(db, FakeDump(SET_PAYLOAD, {"base1": CARD_PAYLOAD}))

    loader.load_all()
    second = loader.load_all()

    assert second.cards_loaded == 1
    assert db.query(Card).count() == 1
    assert db.query(CardSet).count() == 1


def test_reload_updates_changed_fields(db):
    loader = CatalogLoader(db, FakeDump(SET_PAYLOAD, {"base1": CARD_PAYLOAD}))
    loader.load_all()

    updated = [dict(CARD_PAYLOAD[0], rarity="Rare Holo VMAX")]
    CatalogLoader(db, FakeDump(SET_PAYLOAD, {"base1": updated})).load_all()

    assert db.get(Card, "base1-4").rarity == "Rare Holo VMAX"


def test_missing_optional_fields_are_tolerated(db):
    sparse = [{"id": "base1-5", "name": "Clefairy", "number": "5"}]
    loader = CatalogLoader(db, FakeDump(SET_PAYLOAD, {"base1": sparse}))

    loader.load_all()

    card = db.get(Card, "base1-5")
    assert card.rarity is None
    assert card.image_small is None
```

- [ ] **Step 2: Run it to verify it fails**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_loader.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'cardplatform.catalog.loader'`

- [ ] **Step 3: Write the implementation**

`backend/src/cardplatform/catalog/loader.py`:

```python
"""Loads the JSON dump into the database. Idempotent: safe to re-run."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.orm import Session

from cardplatform.db.models import Card, CardSet


class DumpSource(Protocol):
    def fetch_sets(self) -> list[dict[str, Any]]: ...
    def fetch_cards(self, set_id: str) -> list[dict[str, Any]]: ...


@dataclass
class LoadResult:
    sets_loaded: int = 0
    cards_loaded: int = 0


class CatalogLoader:
    def __init__(self, session: Session, dump: DumpSource) -> None:
        self.session = session
        self.dump = dump

    def load_all(self) -> LoadResult:
        result = LoadResult()

        for raw_set in self.dump.fetch_sets():
            self._upsert_set(raw_set)
            result.sets_loaded += 1

            for raw_card in self.dump.fetch_cards(raw_set["id"]):
                self._upsert_card(raw_card, raw_set["id"])
                result.cards_loaded += 1

        self.session.commit()
        return result

    def _upsert_set(self, raw: dict[str, Any]) -> None:
        images = raw.get("images") or {}
        existing = self.session.get(CardSet, raw["id"])
        target = existing or CardSet(id=raw["id"])

        target.name = raw.get("name", "")
        target.series = raw.get("series")
        target.printed_total = raw.get("printedTotal")
        target.total = raw.get("total")
        target.ptcgo_code = raw.get("ptcgoCode")
        target.release_date = raw.get("releaseDate")
        target.image_symbol = images.get("symbol")
        target.image_logo = images.get("logo")

        if existing is None:
            self.session.add(target)

    def _upsert_card(self, raw: dict[str, Any], set_id: str) -> None:
        images = raw.get("images") or {}
        existing = self.session.get(Card, raw["id"])
        target = existing or Card(id=raw["id"])

        target.set_id = set_id
        target.name = raw.get("name", "")
        target.number = raw.get("number", "")
        target.rarity = raw.get("rarity")
        target.supertype = raw.get("supertype")
        target.subtypes = raw.get("subtypes")
        target.artist = raw.get("artist")
        target.national_pokedex_numbers = raw.get("nationalPokedexNumbers")
        target.image_small = images.get("small")
        target.image_large = images.get("large")

        if existing is None:
            self.session.add(target)
```

- [ ] **Step 4: Run the tests**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_loader.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/cardplatform/catalog/loader.py backend/tests/test_loader.py && git commit -m "feat: add idempotent catalog loader"
```

---

## Task 8: Price provider interface and pokemontcg.io implementation

**Files:**
- Create: `backend/src/cardplatform/prices/__init__.py`
- Create: `backend/src/cardplatform/prices/provider.py`
- Create: `backend/src/cardplatform/prices/pokemontcg.py`
- Test: `backend/tests/test_price_provider.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_price_provider.py`:

```python
import httpx
import respx

from cardplatform.config import Settings
from cardplatform.prices.pokemontcg import PokemonTcgIoProvider
from cardplatform.prices.provider import PriceQuote

CARD_RESPONSE = {
    "data": {
        "id": "hgss4-1",
        "tcgplayer": {
            "updatedAt": "2026/07/28",
            "prices": {
                "holofoil": {"low": 6.5, "mid": 10.63, "high": 80.34, "market": 9.71},
                "reverseHolofoil": {"low": 6.61, "mid": 15.52, "high": 250.0, "market": 13.41},
            },
        },
        "cardmarket": {
            "updatedAt": "2026/07/01",
            "prices": {"averageSellPrice": 2.67, "lowPrice": 0.44, "trendPrice": 3.64},
        },
    }
}


@respx.mock
def test_parses_per_variant_tcgplayer_prices():
    settings = Settings()
    respx.get(f"{settings.api_base_url}/cards/hgss4-1").mock(
        return_value=httpx.Response(200, json=CARD_RESPONSE)
    )

    quotes = PokemonTcgIoProvider(settings).fetch("hgss4-1")

    holo = next(q for q in quotes if q.source == "tcgplayer" and q.variant == "holofoil")
    assert holo.market == 9.71
    assert holo.low == 6.5
    assert holo.source_updated_at == "2026/07/28"

    reverse = next(q for q in quotes if q.variant == "reverseHolofoil")
    assert reverse.market == 13.41
    assert isinstance(reverse, PriceQuote)


@respx.mock
def test_parses_cardmarket_as_separate_source():
    settings = Settings()
    respx.get(f"{settings.api_base_url}/cards/hgss4-1").mock(
        return_value=httpx.Response(200, json=CARD_RESPONSE)
    )

    quotes = PokemonTcgIoProvider(settings).fetch("hgss4-1")

    cm = next(q for q in quotes if q.source == "cardmarket")
    assert cm.market == 2.67
    assert cm.source_updated_at == "2026/07/01"


@respx.mock
def test_retries_then_succeeds_on_flaky_api():
    """The live API failed 10 of 12 requests on 2026-07-28. Retry is mandatory."""
    settings = Settings(http_max_attempts=4)
    route = respx.get(f"{settings.api_base_url}/cards/hgss4-1")
    route.side_effect = [
        httpx.Response(500),
        httpx.Response(500),
        httpx.Response(200, json=CARD_RESPONSE),
    ]

    quotes = PokemonTcgIoProvider(settings).fetch("hgss4-1")

    assert len(quotes) > 0
    assert route.call_count == 3


@respx.mock
def test_gives_up_after_max_attempts():
    settings = Settings(http_max_attempts=3)
    respx.get(f"{settings.api_base_url}/cards/x-1").mock(return_value=httpx.Response(500))

    quotes = PokemonTcgIoProvider(settings).fetch("x-1")

    assert quotes == []


@respx.mock
def test_card_with_no_price_block_returns_empty():
    settings = Settings()
    respx.get(f"{settings.api_base_url}/cards/x-2").mock(
        return_value=httpx.Response(200, json={"data": {"id": "x-2"}})
    )

    assert PokemonTcgIoProvider(settings).fetch("x-2") == []
```

- [ ] **Step 2: Run it to verify it fails**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_price_provider.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'cardplatform.prices'`

- [ ] **Step 3: Write the provider interface**

`backend/src/cardplatform/prices/__init__.py`: create as an empty file.

`backend/src/cardplatform/prices/provider.py`:

```python
"""Price provider interface.

pokemontcg.io joined Scrydex in 2026 and its long-term free availability is uncertain
(spec §3.1). Every price source implements this protocol so a replacement can be added
without touching callers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PriceQuote:
    card_id: str
    source: str
    variant: str
    low: float | None = None
    mid: float | None = None
    high: float | None = None
    market: float | None = None
    source_updated_at: str | None = None


class PriceProvider(Protocol):
    name: str

    def fetch(self, card_id: str) -> list[PriceQuote]:
        """Return every available quote for a card. Returns [] on failure — never raises."""
        ...
```

- [ ] **Step 4: Write the pokemontcg.io implementation**

`backend/src/cardplatform/prices/pokemontcg.py`:

```python
"""pokemontcg.io price provider.

Measured 2026-07-28: the API returned HTTP 500 for 10 of 12 requests. Retries with
exponential backoff are essential, and total failure must degrade to [] rather than raise.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from tenacity import RetryError, retry, retry_if_result, stop_after_attempt, wait_exponential

from cardplatform.config import Settings, settings as default_settings
from cardplatform.prices.provider import PriceQuote

logger = logging.getLogger(__name__)

_CARDMARKET_FIELD_MAP = {
    "market": "averageSellPrice",
    "low": "lowPrice",
    "mid": "trendPrice",
}


class PokemonTcgIoProvider:
    name = "pokemontcg.io"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or default_settings

    def fetch(self, card_id: str) -> list[PriceQuote]:
        payload = self._get_card(card_id)
        if payload is None:
            return []

        data = payload.get("data") or {}
        quotes: list[PriceQuote] = []
        quotes.extend(self._parse_tcgplayer(card_id, data.get("tcgplayer")))
        quotes.extend(self._parse_cardmarket(card_id, data.get("cardmarket")))
        return quotes

    def _get_card(self, card_id: str) -> dict[str, Any] | None:
        headers = {"X-Api-Key": self.settings.api_key} if self.settings.api_key else {}
        url = f"{self.settings.api_base_url}/cards/{card_id}"

        @retry(
            stop=stop_after_attempt(self.settings.http_max_attempts),
            wait=wait_exponential(multiplier=1, min=1, max=20),
            retry=retry_if_result(lambda r: r is None),
        )
        def _attempt() -> dict[str, Any] | None:
            try:
                response = httpx.get(
                    url, headers=headers, timeout=self.settings.http_timeout_seconds
                )
            except httpx.HTTPError as exc:
                logger.warning("price fetch transport error for %s: %s", card_id, exc)
                return None
            if response.status_code != 200:
                logger.warning("price fetch HTTP %s for %s", response.status_code, card_id)
                return None
            return response.json()

        try:
            return _attempt()
        except RetryError:
            logger.error("price fetch gave up for %s after %s attempts", card_id, self.settings.http_max_attempts)
            return None

    @staticmethod
    def _parse_tcgplayer(card_id: str, block: dict[str, Any] | None) -> list[PriceQuote]:
        if not block:
            return []
        updated = block.get("updatedAt")
        quotes = []
        for variant, values in (block.get("prices") or {}).items():
            if not isinstance(values, dict):
                continue
            quotes.append(
                PriceQuote(
                    card_id=card_id,
                    source="tcgplayer",
                    variant=variant,
                    low=values.get("low"),
                    mid=values.get("mid"),
                    high=values.get("high"),
                    market=values.get("market"),
                    source_updated_at=updated,
                )
            )
        return quotes

    @staticmethod
    def _parse_cardmarket(card_id: str, block: dict[str, Any] | None) -> list[PriceQuote]:
        """Cardmarket has no per-variant breakdown and lagged ~4 weeks when measured."""
        if not block:
            return []
        prices = block.get("prices") or {}
        if not prices:
            return []
        return [
            PriceQuote(
                card_id=card_id,
                source="cardmarket",
                variant="aggregate",
                low=prices.get(_CARDMARKET_FIELD_MAP["low"]),
                mid=prices.get(_CARDMARKET_FIELD_MAP["mid"]),
                high=None,
                market=prices.get(_CARDMARKET_FIELD_MAP["market"]),
                source_updated_at=block.get("updatedAt"),
            )
        ]
```

- [ ] **Step 5: Run the tests**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_price_provider.py -v
```

Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/src/cardplatform/prices backend/tests/test_price_provider.py && git commit -m "feat: add price provider interface and retry-hardened pokemontcg.io source"
```

---

## Task 9: Price service — snapshots and latest-price queries

**Files:**
- Create: `backend/src/cardplatform/prices/service.py`
- Test: `backend/tests/test_price_service.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_price_service.py`:

```python
import pytest

from cardplatform.db.models import Card, CardSet, PriceSnapshot
from cardplatform.prices.provider import PriceQuote
from cardplatform.prices.service import PriceService


class FakeProvider:
    name = "fake"

    def __init__(self, quotes):
        self.quotes = quotes
        self.calls = []

    def fetch(self, card_id):
        self.calls.append(card_id)
        return self.quotes


@pytest.fixture
def seeded(db):
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(Card(id="base1-4", set_id="base1", name="Charizard", number="4"))
    db.commit()
    return db


def test_records_snapshot_per_variant(seeded):
    provider = FakeProvider(
        [
            PriceQuote("base1-4", "tcgplayer", "holofoil", market=9.71, source_updated_at="2026/07/28"),
            PriceQuote("base1-4", "tcgplayer", "reverseHolofoil", market=13.41, source_updated_at="2026/07/28"),
        ]
    )

    written = PriceService(seeded, provider).refresh_card("base1-4")

    assert written == 2
    assert seeded.query(PriceSnapshot).count() == 2


def test_same_source_timestamp_is_not_duplicated(seeded):
    quote = PriceQuote("base1-4", "tcgplayer", "holofoil", market=9.71, source_updated_at="2026/07/28")
    service = PriceService(seeded, FakeProvider([quote]))

    service.refresh_card("base1-4")
    second = service.refresh_card("base1-4")

    assert second == 0
    assert seeded.query(PriceSnapshot).count() == 1


def test_new_source_timestamp_appends_history(seeded):
    day_one = PriceQuote("base1-4", "tcgplayer", "holofoil", market=9.71, source_updated_at="2026/07/28")
    day_two = PriceQuote("base1-4", "tcgplayer", "holofoil", market=11.02, source_updated_at="2026/07/29")

    PriceService(seeded, FakeProvider([day_one])).refresh_card("base1-4")
    PriceService(seeded, FakeProvider([day_two])).refresh_card("base1-4")

    assert seeded.query(PriceSnapshot).count() == 2


def test_latest_price_prefers_tcgplayer(seeded):
    quotes = [
        PriceQuote("base1-4", "tcgplayer", "holofoil", market=9.71, source_updated_at="2026/07/28"),
        PriceQuote("base1-4", "cardmarket", "aggregate", market=2.67, source_updated_at="2026/07/01"),
    ]
    service = PriceService(seeded, FakeProvider(quotes))
    service.refresh_card("base1-4")

    latest = service.latest_price("base1-4", variant="holofoil")

    assert latest.source == "tcgplayer"
    assert latest.market == 9.71


def test_latest_price_returns_none_when_unpriced(seeded):
    service = PriceService(seeded, FakeProvider([]))
    assert service.latest_price("base1-4", variant="holofoil") is None
```

- [ ] **Step 2: Run it to verify it fails**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_price_service.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'cardplatform.prices.service'`

- [ ] **Step 3: Write the implementation**

`backend/src/cardplatform/prices/service.py`:

```python
"""Writes price snapshots and answers latest-price queries.

Snapshots are immutable and deduplicated on the source's own updatedAt stamp, so
re-running a refresh does not inflate history with identical rows.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from cardplatform.db.models import PriceSnapshot
from cardplatform.prices.provider import PriceProvider

# TCGplayer refreshed daily when measured; Cardmarket lagged ~4 weeks. Prefer the fresher feed.
_SOURCE_PRIORITY = {"tcgplayer": 0, "cardmarket": 1}


class PriceService:
    def __init__(self, session: Session, provider: PriceProvider) -> None:
        self.session = session
        self.provider = provider

    def refresh_card(self, card_id: str) -> int:
        """Fetch and persist new snapshots. Returns the number of rows written."""
        written = 0
        for quote in self.provider.fetch(card_id):
            if self._already_recorded(quote.card_id, quote.source, quote.variant, quote.source_updated_at):
                continue
            self.session.add(
                PriceSnapshot(
                    card_id=quote.card_id,
                    source=quote.source,
                    variant=quote.variant,
                    low=quote.low,
                    mid=quote.mid,
                    high=quote.high,
                    market=quote.market,
                    source_updated_at=quote.source_updated_at,
                )
            )
            written += 1
        self.session.commit()
        return written

    def latest_price(self, card_id: str, variant: str) -> PriceSnapshot | None:
        """Most recent snapshot for a card+variant, preferring the fresher source."""
        rows = self.session.scalars(
            select(PriceSnapshot)
            .where(PriceSnapshot.card_id == card_id, PriceSnapshot.variant == variant)
            .order_by(PriceSnapshot.fetched_at.desc())
        ).all()
        if not rows:
            return None
        return min(rows, key=lambda r: _SOURCE_PRIORITY.get(r.source, 99))

    def _already_recorded(
        self, card_id: str, source: str, variant: str, source_updated_at: str | None
    ) -> bool:
        existing = self.session.scalars(
            select(PriceSnapshot).where(
                PriceSnapshot.card_id == card_id,
                PriceSnapshot.source == source,
                PriceSnapshot.variant == variant,
                PriceSnapshot.source_updated_at == source_updated_at,
            )
        ).first()
        return existing is not None
```

- [ ] **Step 4: Run the tests**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_price_service.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/cardplatform/prices/service.py backend/tests/test_price_service.py && git commit -m "feat: add price snapshot service with dedupe and source priority"
```

---

## Task 10: Collection store

**Files:**
- Create: `backend/src/cardplatform/collection/__init__.py`
- Create: `backend/src/cardplatform/collection/store.py`
- Test: `backend/tests/test_collection.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_collection.py`:

```python
import pytest

from cardplatform.collection.store import CollectionStore
from cardplatform.db.models import Card, CardSet, PriceSnapshot


@pytest.fixture
def seeded(db):
    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(Card(id="base1-4", set_id="base1", name="Charizard", number="4"))
    db.add(Card(id="base1-5", set_id="base1", name="Clefairy", number="5"))
    db.commit()
    return db


def test_add_item(seeded):
    store = CollectionStore(seeded)

    item = store.add("base1-4", variant="holofoil", quantity=2, acquired_price=120.0)

    assert item.id is not None
    assert item.quantity == 2
    assert len(store.list_items()) == 1


def test_adding_same_card_variant_increments_quantity(seeded):
    store = CollectionStore(seeded)

    store.add("base1-4", variant="holofoil", quantity=1)
    store.add("base1-4", variant="holofoil", quantity=3)

    items = store.list_items()
    assert len(items) == 1
    assert items[0].quantity == 4


def test_different_variants_are_separate_rows(seeded):
    store = CollectionStore(seeded)

    store.add("base1-4", variant="holofoil", quantity=1)
    store.add("base1-4", variant="reverseHolofoil", quantity=1)

    assert len(store.list_items()) == 2


def test_remove_reduces_then_deletes(seeded):
    store = CollectionStore(seeded)
    store.add("base1-4", variant="holofoil", quantity=3)

    store.remove("base1-4", variant="holofoil", quantity=1)
    assert store.list_items()[0].quantity == 2

    store.remove("base1-4", variant="holofoil", quantity=5)
    assert store.list_items() == []


def test_unknown_card_is_rejected(seeded):
    store = CollectionStore(seeded)

    with pytest.raises(ValueError, match="unknown card"):
        store.add("does-not-exist", variant="normal")


def test_total_value_uses_latest_market_price(seeded):
    seeded.add(
        PriceSnapshot(
            card_id="base1-4",
            source="tcgplayer",
            variant="holofoil",
            market=100.0,
            source_updated_at="2026/07/28",
        )
    )
    seeded.commit()
    store = CollectionStore(seeded)
    store.add("base1-4", variant="holofoil", quantity=2, acquired_price=60.0)

    valuation = store.total_value()

    assert valuation.market_value == 200.0
    assert valuation.cost_basis == 120.0
    assert valuation.unrealized == 80.0


def test_unpriced_items_do_not_break_valuation(seeded):
    store = CollectionStore(seeded)
    store.add("base1-5", variant="normal", quantity=1, acquired_price=5.0)

    valuation = store.total_value()

    assert valuation.market_value == 0.0
    assert valuation.cost_basis == 5.0
    assert valuation.unpriced_items == 1
```

- [ ] **Step 2: Run it to verify it fails**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_collection.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'cardplatform.collection'`

- [ ] **Step 3: Write the implementation**

`backend/src/cardplatform/collection/__init__.py`: create as an empty file.

`backend/src/cardplatform/collection/store.py`:

```python
"""Collection storage and valuation.

Valuation is deliberately conservative: an item with no price snapshot contributes zero
to market value and is counted in `unpriced_items`, rather than being silently guessed at.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from cardplatform.db.models import Card, CollectionItem, PriceSnapshot

_SOURCE_PRIORITY = {"tcgplayer": 0, "cardmarket": 1}


@dataclass(frozen=True)
class Valuation:
    market_value: float
    cost_basis: float
    unrealized: float
    unpriced_items: int


class CollectionStore:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(
        self,
        card_id: str,
        variant: str = "normal",
        quantity: int = 1,
        acquired_price: float | None = None,
        condition: str | None = None,
        notes: str | None = None,
    ) -> CollectionItem:
        if self.session.get(Card, card_id) is None:
            raise ValueError(f"unknown card: {card_id}")

        existing = self._find(card_id, variant)
        if existing is not None:
            existing.quantity += quantity
            self.session.commit()
            return existing

        item = CollectionItem(
            card_id=card_id,
            variant=variant,
            quantity=quantity,
            acquired_price=acquired_price,
            condition=condition,
            notes=notes,
        )
        self.session.add(item)
        self.session.commit()
        return item

    def remove(self, card_id: str, variant: str = "normal", quantity: int = 1) -> None:
        item = self._find(card_id, variant)
        if item is None:
            return
        item.quantity -= quantity
        if item.quantity <= 0:
            self.session.delete(item)
        self.session.commit()

    def list_items(self) -> list[CollectionItem]:
        return list(self.session.scalars(select(CollectionItem).order_by(CollectionItem.id)).all())

    def total_value(self) -> Valuation:
        market = 0.0
        cost = 0.0
        unpriced = 0

        for item in self.list_items():
            price = self._latest_market(item.card_id, item.variant)
            if price is None:
                unpriced += 1
            else:
                market += price * item.quantity
            if item.acquired_price is not None:
                cost += item.acquired_price * item.quantity

        return Valuation(
            market_value=market,
            cost_basis=cost,
            unrealized=market - cost,
            unpriced_items=unpriced,
        )

    def _find(self, card_id: str, variant: str) -> CollectionItem | None:
        return self.session.scalars(
            select(CollectionItem).where(
                CollectionItem.card_id == card_id, CollectionItem.variant == variant
            )
        ).first()

    def _latest_market(self, card_id: str, variant: str) -> float | None:
        rows = self.session.scalars(
            select(PriceSnapshot)
            .where(
                PriceSnapshot.card_id == card_id,
                PriceSnapshot.variant == variant,
                PriceSnapshot.market.is_not(None),
            )
            .order_by(PriceSnapshot.fetched_at.desc())
        ).all()
        if not rows:
            return None
        best = min(rows, key=lambda r: _SOURCE_PRIORITY.get(r.source, 99))
        return best.market
```

- [ ] **Step 4: Run the tests**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_collection.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/cardplatform/collection backend/tests/test_collection.py && git commit -m "feat: add collection store with conservative valuation"
```

---

## Task 11: CLI — sync the catalog for real

**Files:**
- Create: `backend/src/cardplatform/cli.py`
- Modify: `backend/pyproject.toml` (add `[project.scripts]`)

- [ ] **Step 1: Write the CLI**

`backend/src/cardplatform/cli.py`:

```python
"""Command-line entry points for catalog and price maintenance."""

from __future__ import annotations

import argparse
import logging
import sys

from cardplatform.catalog.dump import DumpClient
from cardplatform.catalog.loader import CatalogLoader
from cardplatform.db.session import Database
from cardplatform.prices.pokemontcg import PokemonTcgIoProvider
from cardplatform.prices.service import PriceService

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("cardplatform")


def sync_catalog() -> int:
    database = Database()
    database.create_all()
    with database.session() as session:
        result = CatalogLoader(session, DumpClient()).load_all()
    print(f"Loaded {result.sets_loaded} sets and {result.cards_loaded} cards.")
    return 0


def refresh_prices(card_ids: list[str]) -> int:
    database = Database()
    database.create_all()
    provider = PokemonTcgIoProvider()
    total = 0
    with database.session() as session:
        service = PriceService(session, provider)
        for card_id in card_ids:
            written = service.refresh_card(card_id)
            total += written
            print(f"{card_id}: {written} new snapshot(s)")
    print(f"Wrote {total} snapshot(s).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cardplatform")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("sync-catalog", help="Load all sets and cards from the GitHub dump")

    prices = sub.add_parser("refresh-prices", help="Fetch prices for one or more card ids")
    prices.add_argument("card_ids", nargs="+")

    args = parser.parse_args(argv)

    if args.command == "sync-catalog":
        return sync_catalog()
    if args.command == "refresh-prices":
        return refresh_prices(args.card_ids)
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Register the console script**

Add to `backend/pyproject.toml`, after the `[project.optional-dependencies]` block:

```toml
[project.scripts]
cardplatform = "cardplatform.cli:main"
```

- [ ] **Step 3: Reinstall so the script is registered**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\pip.exe install -e "C:\ClaudeKnowledge\backend[dev]"
```

- [ ] **Step 4: Run the real catalog sync**

This hits GitHub 175 times (1 sets file + 174 card files) and takes a few minutes.

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\cardplatform.exe sync-catalog
```

Expected: `Loaded 174 sets and 20479 cards.` The card count may drift slightly upward as new sets
release — anything near 20,479 is correct. A count of 0 means the dump URLs are wrong.

- [ ] **Step 5: Spot-check the data, especially the encoding**

Create `backend/scripts/spot_check.py`:

```python
"""Verifies the loaded catalog, especially that UTF-8 survived the load."""

from cardplatform.db.models import Card
from cardplatform.db.session import Database

with Database().session() as session:
    card = session.get(Card, "base1-4")
    assert card is not None, "base1-4 missing — catalog did not load"
    print("name:      ", repr(card.name))
    print("supertype: ", repr(card.supertype))
    print("set:       ", card.card_set.name)
    print("image:     ", card.image_small)
    assert "Ã" not in (card.supertype or ""), "MOJIBAKE — utf-8 decode regressed in dump.py"
    print("OK")
```

Run it:

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe backend/scripts/spot_check.py
```

Expected: `'Charizard' 'Pokémon'`, an image URL, then `OK`. If it prints `PokÃ©mon` or asserts, the
UTF-8 decode in `dump.py` regressed.

- [ ] **Step 6: Fetch real prices for one card**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\cardplatform.exe refresh-prices base1-4 hgss4-1
```

Expected: one or more `N new snapshot(s)` lines. Given the API's ~17% success rate this may take
several seconds per card while retries back off — that is the retry logic working, not a hang. If a
card reports 0 snapshots after retries, that is acceptable degradation.

- [ ] **Step 7: Commit**

```bash
git add backend/src/cardplatform/cli.py backend/pyproject.toml backend/scripts/spot_check.py && git commit -m "feat: add cli for catalog sync and price refresh"
```

---

## Task 12: FastAPI read endpoints

**Files:**
- Create: `backend/src/cardplatform/api.py`
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_api.py`:

```python
import pytest
from fastapi.testclient import TestClient

from cardplatform.api import create_app, get_session
from cardplatform.db.models import Card, CardSet, PriceSnapshot


@pytest.fixture
def client(db):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db

    db.add(CardSet(id="base1", name="Base", series="Base"))
    db.add(
        Card(
            id="base1-4",
            set_id="base1",
            name="Charizard",
            number="4",
            rarity="Rare Holo",
            image_small="https://images.pokemontcg.io/base1/4.png",
        )
    )
    db.add(
        PriceSnapshot(
            card_id="base1-4",
            source="tcgplayer",
            variant="holofoil",
            market=100.0,
            source_updated_at="2026/07/28",
        )
    )
    db.commit()
    return TestClient(app)


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_get_card(client):
    response = client.get("/cards/base1-4")

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Charizard"
    assert body["set_name"] == "Base"
    assert body["image_small"].endswith("/4.png")


def test_get_missing_card_is_404(client):
    assert client.get("/cards/nope-1").status_code == 404


def test_search_by_name(client):
    response = client.get("/cards", params={"name": "chari"})

    assert response.status_code == 200
    results = response.json()
    assert len(results) == 1
    assert results[0]["id"] == "base1-4"


def test_card_prices_include_staleness_stamp(client):
    response = client.get("/cards/base1-4/prices")

    assert response.status_code == 200
    prices = response.json()
    assert prices[0]["variant"] == "holofoil"
    assert prices[0]["market"] == 100.0
    assert prices[0]["source_updated_at"] == "2026/07/28"


def test_collection_endpoints(client):
    added = client.post("/collection", json={"card_id": "base1-4", "variant": "holofoil", "quantity": 2})
    assert added.status_code == 201

    listing = client.get("/collection")
    assert listing.status_code == 200
    assert listing.json()[0]["quantity"] == 2

    valuation = client.get("/collection/valuation")
    assert valuation.json()["market_value"] == 200.0
```

- [ ] **Step 2: Run it to verify it fails**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_api.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'cardplatform.api'`

- [ ] **Step 3: Write the implementation**

`backend/src/cardplatform/api.py`:

```python
"""FastAPI read/write endpoints over the local catalog and collection.

Prices are always returned with their source timestamp so the UI can show staleness
explicitly rather than implying every number is current (spec §5).
"""

from __future__ import annotations

from typing import Iterator

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from cardplatform.collection.store import CollectionStore
from cardplatform.db.models import Card, PriceSnapshot
from cardplatform.db.session import Database

_database: Database | None = None


def get_database() -> Database:
    global _database
    if _database is None:
        _database = Database()
        _database.create_all()
    return _database


def get_session() -> Iterator[Session]:
    with get_database().session() as session:
        yield session


class CardOut(BaseModel):
    id: str
    name: str
    number: str
    rarity: str | None
    set_id: str
    set_name: str
    image_small: str | None
    image_large: str | None


class PriceOut(BaseModel):
    source: str
    variant: str
    low: float | None
    mid: float | None
    high: float | None
    market: float | None
    source_updated_at: str | None


class CollectionItemIn(BaseModel):
    card_id: str
    variant: str = "normal"
    quantity: int = 1
    acquired_price: float | None = None
    condition: str | None = None


class CollectionItemOut(BaseModel):
    id: int
    card_id: str
    card_name: str
    variant: str
    quantity: int
    acquired_price: float | None


class ValuationOut(BaseModel):
    market_value: float
    cost_basis: float
    unrealized: float
    unpriced_items: int


def create_app() -> FastAPI:
    app = FastAPI(title="Card Platform", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/cards", response_model=list[CardOut])
    def search_cards(
        name: str = Query(min_length=1),
        limit: int = Query(default=25, le=100),
        session: Session = Depends(get_session),
    ) -> list[CardOut]:
        rows = session.scalars(
            select(Card).where(Card.name.ilike(f"%{name}%")).order_by(Card.name).limit(limit)
        ).all()
        return [_card_out(c) for c in rows]

    @app.get("/cards/{card_id}", response_model=CardOut)
    def get_card(card_id: str, session: Session = Depends(get_session)) -> CardOut:
        card = session.get(Card, card_id)
        if card is None:
            raise HTTPException(status_code=404, detail="card not found")
        return _card_out(card)

    @app.get("/cards/{card_id}/prices", response_model=list[PriceOut])
    def get_prices(card_id: str, session: Session = Depends(get_session)) -> list[PriceOut]:
        rows = session.scalars(
            select(PriceSnapshot)
            .where(PriceSnapshot.card_id == card_id)
            .order_by(PriceSnapshot.fetched_at.desc())
        ).all()
        seen: set[tuple[str, str]] = set()
        latest: list[PriceOut] = []
        for row in rows:
            key = (row.source, row.variant)
            if key in seen:
                continue
            seen.add(key)
            latest.append(
                PriceOut(
                    source=row.source,
                    variant=row.variant,
                    low=row.low,
                    mid=row.mid,
                    high=row.high,
                    market=row.market,
                    source_updated_at=row.source_updated_at,
                )
            )
        return latest

    @app.post("/collection", response_model=CollectionItemOut, status_code=201)
    def add_to_collection(
        payload: CollectionItemIn, session: Session = Depends(get_session)
    ) -> CollectionItemOut:
        store = CollectionStore(session)
        try:
            item = store.add(
                payload.card_id,
                variant=payload.variant,
                quantity=payload.quantity,
                acquired_price=payload.acquired_price,
                condition=payload.condition,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return _item_out(item, session)

    @app.get("/collection", response_model=list[CollectionItemOut])
    def list_collection(session: Session = Depends(get_session)) -> list[CollectionItemOut]:
        return [_item_out(i, session) for i in CollectionStore(session).list_items()]

    @app.get("/collection/valuation", response_model=ValuationOut)
    def collection_valuation(session: Session = Depends(get_session)) -> ValuationOut:
        v = CollectionStore(session).total_value()
        return ValuationOut(
            market_value=v.market_value,
            cost_basis=v.cost_basis,
            unrealized=v.unrealized,
            unpriced_items=v.unpriced_items,
        )

    return app


def _card_out(card: Card) -> CardOut:
    return CardOut(
        id=card.id,
        name=card.name,
        number=card.number,
        rarity=card.rarity,
        set_id=card.set_id,
        set_name=card.card_set.name if card.card_set else "",
        image_small=card.image_small,
        image_large=card.image_large,
    )


def _item_out(item, session: Session) -> CollectionItemOut:  # noqa: ANN001
    card = session.get(Card, item.card_id)
    return CollectionItemOut(
        id=item.id,
        card_id=item.card_id,
        card_name=card.name if card else "",
        variant=item.variant,
        quantity=item.quantity,
        acquired_price=item.acquired_price,
    )


app = create_app()
```

- [ ] **Step 4: Run the tests**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_api.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Run the full suite**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\python.exe -m pytest backend/tests -v
```

Expected: **41 passed** — smoke 2, config 4, models 3, session 2, dump 3, loader 4, price provider 5,
price service 5, collection 7, api 6.

- [ ] **Step 6: Start the server and check it against real data**

```bash
C:\ClaudeKnowledge\backend\.venv\Scripts\uvicorn.exe cardplatform.api:app --reload --port 8000
```

Then in a browser open `http://127.0.0.1:8000/docs` and try `GET /cards?name=charizard`. Expected: a
list including `base1-4` Charizard. Stop the server with Ctrl+C.

- [ ] **Step 7: Commit**

```bash
git add backend/src/cardplatform/api.py backend/tests/test_api.py && git commit -m "feat: add fastapi endpoints for cards, prices, and collection"
```

---

## Task 13: Update project docs and push

**Files:**
- Modify: `PROJECT.md`
- Modify: `docs/index.html`

- [ ] **Step 1: Mark Phase 0 complete in `PROJECT.md`**

In the roadmap table, change the Phase 0 row's status from `Designed` to `Complete`.

- [ ] **Step 2: Mark Phase 0 complete on the site**

In `docs/index.html`, find the Phase 00 roadmap row and change its status chip from
`<span class="st now">Building</span>` to `<span class="st done">Complete</span>`.

- [ ] **Step 3: Commit and push**

```bash
git add PROJECT.md docs/index.html && git commit -m "docs: mark phase 0 complete" && git push origin main
```

- [ ] **Step 4: Verify the site updated**

Wait about a minute, then load https://lucas-bianco.github.io/pokemon-card-platform/ and confirm
Phase 00 shows Complete in green.

---

## Definition of done

Phase 0 is complete when:

- [ ] `pytest backend/tests` passes with no failures.
- [ ] `cardplatform sync-catalog` has populated ~174 sets and ~20,479 cards locally.
- [ ] `Card('base1-4').supertype` reads exactly `Pokémon` — no mojibake.
- [ ] `cardplatform refresh-prices base1-4` writes snapshots, and re-running writes 0 new rows.
- [ ] The API serves card search, card detail, prices with staleness stamps, and collection CRUD.
- [ ] Every price read still works with the network disconnected (served from local snapshots).

## What Phase 1 builds on this

The next plan (recognition) consumes: `Card.image_small` URLs to build the reference embedding index,
the `Card` table as the search target, `PriceService.latest_price(card_id, variant)` to value a scanned
card, and `CollectionStore.add()` to save it. No Phase 0 interface should need to change.
