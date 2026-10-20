import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.backend.database import Base, get_db
from src.backend.main import app
import src.backend.main as main


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_engine = create_engine(f"sqlite:///{tmp_path}/test.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(db_engine)
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    def session():
        with factory() as db: yield db
    app.dependency_overrides[get_db] = session
    monkeypatch.setattr(main, "SessionLocal", factory)
    monkeypatch.setattr(main, "engine", db_engine)
    with TestClient(app, follow_redirects=False) as client:
        # TestClient startup uses the bound global engine for bootstrap only; tests use the isolated DB.
        yield client
    app.dependency_overrides.clear()
    db_engine.dispose()


@pytest.fixture
def signed(client):
    response = client.post("/api/profiles", json={"name": "learner"})
    assert response.status_code == 201, response.text
    client.headers["X-Profile-ID"] = response.json()["id"]
    return client


@pytest.fixture(scope="session", autouse=True)
def close_stockfish():
    yield
    from src.backend.engine import engine_service
    engine_service.close()
