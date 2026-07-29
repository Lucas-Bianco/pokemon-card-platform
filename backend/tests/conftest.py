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
