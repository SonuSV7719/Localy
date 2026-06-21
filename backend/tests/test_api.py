"""
Integration tests for the REST API endpoints.
"""

from __future__ import annotations

import sys
sys.path.insert(0, 'src')

from fastapi.testclient import TestClient
from localy.main import create_app


def test_health_check() -> None:
    """Test the /health API endpoint."""
    app = create_app()
    client = TestClient(app)

    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_check() -> None:
    """Test the /ready API endpoint."""
    app = create_app()
    client = TestClient(app)

    response = client.get("/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert "model_loaded" in data


def test_list_models_unauthorized() -> None:
    """Test v1 list models endpoint requires API key if configured.

    By default, settings.api_key is None, so it should be authorized.
    """
    app = create_app()
    client = TestClient(app)

    response = client.get("/v1/models")
    assert response.status_code == 200
    data = response.json()
    assert data["object"] == "list"
    assert "data" in data
