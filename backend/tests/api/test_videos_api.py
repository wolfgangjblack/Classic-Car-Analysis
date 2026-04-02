"""Tests for backend/app/api/videos.py -- upload and URL submission."""

import io
from unittest.mock import patch


def test_upload_valid_mp4(test_client):
    fake_video = io.BytesIO(b"\x00\x00\x00\x1cftypisom" + b"\x00" * 100)

    with patch("app.api.videos.shutil.copyfileobj"):
        resp = test_client.post(
            "/api/videos/upload",
            files={"file": ("test_video.mp4", fake_video, "video/mp4")},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pending"
    assert data["original_filename"] == "test_video.mp4"
    assert data["source_type"] == "upload"


def test_upload_invalid_extension(test_client):
    fake_file = io.BytesIO(b"not a video")
    resp = test_client.post(
        "/api/videos/upload",
        files={"file": ("document.txt", fake_file, "text/plain")},
    )
    assert resp.status_code == 400


def test_submit_url_valid(test_client):
    resp = test_client.post(
        "/api/videos/url",
        json={"url": "https://www.youtube.com/watch?v=test123"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["source_type"] == "url"
    assert data["status"] == "pending"


def test_submit_url_invalid_scheme(test_client):
    resp = test_client.post(
        "/api/videos/url",
        json={"url": "ftp://example.com/video.mp4"},
    )
    assert resp.status_code == 400
