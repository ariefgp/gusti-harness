"""Second endpoint's tests — also FAIL until validation lands."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_rejects_missing_item():
    r = client.post("/orders", json={"quantity": 2})
    assert r.status_code == 422


def test_rejects_non_positive_quantity():
    r = client.post("/orders", json={"item": "widget", "quantity": 0})
    assert r.status_code == 422


def test_accepts_valid_order():
    r = client.post("/orders", json={"item": "widget", "quantity": 2})
    assert r.status_code == 200
    assert r.json() == {"item": "widget", "quantity": 2}
