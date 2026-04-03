"""Tests for backend/app/core/vision_analyzer.py -- pure logic methods."""

import json
import os

import pytest
from app.core.vision_analyzer import ConditionResult, VisionAnalyzer


@pytest.fixture
def analyzer():
    return VisionAnalyzer(model="gpt-4o", max_frames=10)


# --- _parse_response ---


def test_parse_response_clean_json(analyzer):
    raw = '{"score": 5, "notes": "excellent"}'
    result = analyzer._parse_response(raw)
    assert result == {"score": 5, "notes": "excellent"}


def test_parse_response_markdown_fenced(analyzer):
    raw = '```json\n{"score": 5}\n```'
    result = analyzer._parse_response(raw)
    assert result == {"score": 5}


def test_parse_response_invalid_json(analyzer):
    with pytest.raises(json.JSONDecodeError):
        analyzer._parse_response("not json at all")


# --- _compute_overall_score ---


def test_compute_overall_score_all_visible(analyzer):
    area_scores = {
        "exterior_paint": {"score": 4},
        "body_panels": {"score": 3},
        "chrome_trim": {"score": 5},
        "wheels_tires": {"score": 4},
        "glass": {"score": 5},
        "interior_seats": {"score": 4},
        "dashboard": {"score": 3},
        "carpet_headliner": {"score": 4},
    }
    result = analyzer._compute_overall_score(area_scores)
    # Exterior areas (1.5 weight): paint=4, body=3, chrome=5, wheels=4 -> sum=24, weight=6
    # Interior areas (1.0 weight): glass=5, seats=4, dash=3, carpet=4 -> sum=16, weight=4
    # Total: 40 / 10 = 4.0
    assert result == 4.0


def test_compute_overall_score_partial(analyzer):
    area_scores = {
        "exterior_paint": {"score": 5},
        "body_panels": {"score": 0},
        "glass": {"score": 3},
    }
    result = analyzer._compute_overall_score(area_scores)
    # Only paint (5 * 1.5 = 7.5) and glass (3 * 1.0 = 3.0) counted
    # 10.5 / 2.5 = 4.2
    assert result == 4.2


def test_compute_overall_score_empty(analyzer):
    result = analyzer._compute_overall_score({})
    assert result == 0.0


# --- _resolve_evidence_frames ---


def test_resolve_evidence_frames_valid(analyzer):
    observations = {
        "good": [{"text": "Nice paint", "image_index": 2, "area": "exterior_paint"}],
        "bad": [{"text": "Dent on panel", "image_index": 1, "area": "body_panels"}],
    }
    frame_paths = ["/frames/frame_001.jpg", "/frames/frame_002.jpg", "/frames/frame_003.jpg"]
    result = analyzer._resolve_evidence_frames(observations, frame_paths)

    assert result["good"][0]["evidence_frame"] == "frame_002.jpg"
    assert result["bad"][0]["evidence_frame"] == "frame_001.jpg"


def test_resolve_evidence_frames_out_of_range(analyzer):
    observations = {
        "good": [{"text": "Something", "image_index": 99, "area": "general"}],
        "bad": [{"text": "Other", "image_index": 0, "area": "general"}],
    }
    frame_paths = ["/frames/frame_001.jpg"]
    result = analyzer._resolve_evidence_frames(observations, frame_paths)

    assert "evidence_frame" not in result["good"][0]
    assert "evidence_frame" not in result["bad"][0]


def test_resolve_evidence_frames_string_obs(analyzer):
    observations = {
        "good": ["Plain string observation"],
        "bad": [],
    }
    result = analyzer._resolve_evidence_frames(observations, ["/frames/f1.jpg"])
    assert result["good"][0] == {"text": "Plain string observation", "image_index": 0, "area": "general"}


# --- ConditionResult ---


def test_get_evidence_frame_paths():
    cr = ConditionResult(
        observations={
            "good": [{"text": "Nice", "image_index": 1}, {"text": "Also nice", "image_index": 3}],
            "bad": [{"text": "Scratch", "image_index": 2}],
        },
        area_scores={},
        overall_score=4.0,
        overall_assessment="Good",
        images_analyzed=3,
        exterior_images_found=2,
        interior_images_found=1,
        frame_paths=["/a.jpg", "/b.jpg", "/c.jpg"],
    )
    evidence = cr.get_evidence_frame_paths()
    assert evidence == {1: "/a.jpg", 2: "/b.jpg", 3: "/c.jpg"}


# --- select_frames ---


def test_select_frames_fewer_than_max(tmp_path, analyzer):
    for i in range(5):
        (tmp_path / f"frame_{i:03d}.jpg").write_bytes(b"\xff\xd8")
    result = analyzer.select_frames(str(tmp_path))
    assert len(result) == 5


def test_select_frames_evenly_spaced(tmp_path):
    for i in range(20):
        (tmp_path / f"frame_{i:03d}.jpg").write_bytes(b"\xff\xd8")
    va = VisionAnalyzer(max_frames=10)
    result = va.select_frames(str(tmp_path))
    assert len(result) == 10
    # Should pick indices 0, 2, 4, 6, 8, 10, 12, 14, 16, 18
    basenames = [os.path.basename(p) for p in result]
    assert basenames[0] == "frame_000.jpg"
    assert basenames[-1] == "frame_018.jpg"


def test_select_frames_missing_dir(analyzer):
    with pytest.raises(FileNotFoundError):
        analyzer.select_frames("/nonexistent/path")


def test_select_frames_no_images(tmp_path, analyzer):
    (tmp_path / "readme.txt").write_text("not an image")
    with pytest.raises(ValueError, match="No image files"):
        analyzer.select_frames(str(tmp_path))
