"""
Integration Tests
─────────────────
Tests full HTTP request/response cycle using FastAPI TestClient.
Uses SQLite in-memory for speed; no external services required.
"""

import io
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient

from app.main import app
from app.core.config import settings


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_headers(client: TestClient) -> dict[str, str]:
    """Register and login a test user, return auth headers."""
    client.post("/v1/auth/register", json={
        "email": "test@example.com",
        "username": "testuser",
        "password": "TestPass123",
    })
    resp = client.post("/v1/auth/login", json={
        "email": "test@example.com",
        "password": "TestPass123",
    })
    token = resp.json()["tokens"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ── Health Endpoint ───────────────────────────────────────────────────────────


class TestHealth:

    def test_health_returns_200(self, client: TestClient):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_response_schema(self, client: TestClient):
        data = client.get("/health").json()
        assert "status" in data
        assert "version" in data
        assert "environment" in data

    def test_root_returns_api_info(self, client: TestClient):
        data = client.get("/").json()
        assert "docs" in data
        assert "version" in data


# ── Auth Endpoints ────────────────────────────────────────────────────────────


class TestAuth:

    def test_register_success(self, client: TestClient):
        resp = client.post("/v1/auth/register", json={
            "email": "newuser@example.com",
            "username": "newuser",
            "password": "NewPass123",
        })
        assert resp.status_code == 201
        body = resp.json()
        assert body["user"]["email"] == "newuser@example.com"
        assert "access_token" in body["tokens"]
        assert "refresh_token" in body["tokens"]

    def test_register_duplicate_email(self, client: TestClient):
        payload = {"email": "dup@example.com", "username": "dup1", "password": "DupPass123"}
        client.post("/v1/auth/register", json=payload)
        resp = client.post("/v1/auth/register", json={**payload, "username": "dup2"})
        assert resp.status_code == 409

    def test_register_weak_password(self, client: TestClient):
        resp = client.post("/v1/auth/register", json={
            "email": "weak@example.com",
            "username": "weakuser",
            "password": "short",
        })
        assert resp.status_code == 422

    def test_login_invalid_credentials(self, client: TestClient):
        resp = client.post("/v1/auth/login", json={
            "email": "nobody@example.com",
            "password": "WrongPass123",
        })
        assert resp.status_code == 401

    def test_get_me_requires_auth(self, client: TestClient):
        resp = client.get("/v1/auth/me")
        assert resp.status_code == 401

    def test_get_me_success(self, client: TestClient, auth_headers: dict):
        resp = client.get("/v1/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        assert "email" in resp.json()


# ── Dataset Endpoints ─────────────────────────────────────────────────────────


class TestDatasets:

    def test_upload_requires_auth(self, client: TestClient):
        resp = client.post("/v1/datasets/upload", files={"file": ("test.csv", b"a,b\n1,2")})
        assert resp.status_code == 401

    def test_upload_csv_success(self, client: TestClient, auth_headers: dict):
        csv_content = b"id,name,value\n1,Alice,100\n2,Bob,200\n3,Carol,300\n"
        resp = client.post(
            "/v1/datasets/upload",
            headers=auth_headers,
            files={"file": ("data.csv", io.BytesIO(csv_content), "text/csv")},
            data={"name": "Test Dataset", "description": "A test upload"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "Test Dataset"
        assert body["row_count"] == 3
        assert body["column_count"] == 3
        assert body["status"] == "ready"
        return body["id"]

    def test_list_datasets_empty(self, client: TestClient, auth_headers: dict):
        resp = client.get("/v1/datasets/", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert "total" in body

    def test_upload_unsupported_format(self, client: TestClient, auth_headers: dict):
        resp = client.post(
            "/v1/datasets/upload",
            headers=auth_headers,
            files={"file": ("test.pdf", b"%PDF-1.4", "application/pdf")},
            data={"name": "Bad Upload"},
        )
        assert resp.status_code == 422

    def test_get_nonexistent_dataset(self, client: TestClient, auth_headers: dict):
        resp = client.get("/v1/datasets/nonexistent-id", headers=auth_headers)
        assert resp.status_code == 404


# ── NL Query Endpoint ─────────────────────────────────────────────────────────


class TestNLQuery:

    def test_nl_query_requires_auth(self, client: TestClient):
        resp = client.post("/v1/ai/query", json={
            "query": "How many users?",
            "dataset_id": "some-id",
        })
        assert resp.status_code == 401

    def test_nl_query_nonexistent_dataset(self, client: TestClient, auth_headers: dict):
        resp = client.post(
            "/v1/ai/query",
            headers=auth_headers,
            json={"query": "Show all rows", "dataset_id": "does-not-exist"},
        )
        assert resp.status_code == 404

    def test_nl_query_too_short(self, client: TestClient, auth_headers: dict):
        resp = client.post(
            "/v1/ai/query",
            headers=auth_headers,
            json={"query": "Hi", "dataset_id": "some-id"},
        )
        assert resp.status_code == 422


# ── Error Handling ────────────────────────────────────────────────────────────


class TestErrorHandling:

    def test_404_returns_structured_error(self, client: TestClient):
        resp = client.get("/v1/nonexistent/endpoint")
        assert resp.status_code == 404

    def test_invalid_json_returns_422(self, client: TestClient, auth_headers: dict):
        resp = client.post(
            "/v1/ai/feedback",
            headers=auth_headers,
            json={"rating": 10, "query_id": "x"},  # rating > 5 is invalid
        )
        assert resp.status_code == 422
        body = resp.json()
        assert body["success"] is False
        assert "error" in body
