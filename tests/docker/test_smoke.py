"""
Docker Compose smoke tests.

Run against a live stack: `docker compose up -d` then `pytest tests/docker/`.
These are read-only probes that verify services are reachable and configured correctly.
"""

import pytest
import requests

API_URL = "http://localhost:8000"
FRONTEND_URL = "http://localhost:3000"


@pytest.fixture(scope="module")
def api_reachable():
    try:
        requests.get(f"{API_URL}/health", timeout=5)
        return True
    except requests.ConnectionError:
        pytest.skip("Docker Compose stack not running (api unreachable)")


@pytest.fixture(scope="module")
def frontend_reachable():
    try:
        requests.get(FRONTEND_URL, timeout=5)
        return True
    except requests.ConnectionError:
        pytest.skip("Docker Compose stack not running (frontend unreachable)")


def test_api_health(api_reachable):
    resp = requests.get(f"{API_URL}/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"


def test_frontend_serves_html(frontend_reachable):
    resp = requests.get(FRONTEND_URL)
    assert resp.status_code == 200
    assert "Classic Car Video Analyzer" in resp.text


def test_frontend_serves_js(frontend_reachable):
    resp = requests.get(f"{FRONTEND_URL}/app.js?v=2")
    assert resp.status_code == 200
    assert "API_BASE" in resp.text


def test_frontend_proxies_api(frontend_reachable):
    resp = requests.get(f"{FRONTEND_URL}/api/jobs")
    assert resp.status_code == 200
    data = resp.json()
    assert "jobs" in data
    assert "total" in data


def test_cors_headers(api_reachable):
    resp = requests.options(
        f"{API_URL}/api/jobs",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" in resp.headers
