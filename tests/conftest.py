import os
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

os.environ["TESTING"] = "1"

db_url = os.environ.get("DATABASE_URL", "sqlite:///test.db")

if "postgresql" in db_url or "postgres" in db_url:
    if "_test" not in db_url and "test" not in db_url.split("/")[-1]:
        raise RuntimeError(
            f"Refusing to run tests against a database that does not contain "
            f"'test' in its name: {db_url}. Set DATABASE_URL to a dedicated "
            f"test database or unset it to use SQLite."
        )

os.environ["DATABASE_URL"] = db_url

from database import Base, get_db  # noqa: E402
from main import app  # noqa: E402

connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
engine = create_engine(db_url, connect_args=connect_args)
TestSession = sessionmaker(bind=engine)


def override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client():
    return TestClient(app, root_path="/api")


@pytest.fixture()
def db():
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
