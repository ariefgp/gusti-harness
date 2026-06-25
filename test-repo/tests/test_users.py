"""These FAIL until validation is added — bad payloads currently 500/KeyError."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_rejects_missing_email():
    r = client.post("/users", json={"age": 30})
    assert r.status_code == 422


def test_rejects_bad_age():
    r = client.post("/users", json={"email": "a@b.com", "age": "old"})
    assert r.status_code == 422


def test_accepts_valid_user():
    r = client.post("/users", json={"email": "a@b.com", "age": 30})
    assert r.status_code == 200
    assert r.json() == {"created": "a@b.com", "age": 30}
