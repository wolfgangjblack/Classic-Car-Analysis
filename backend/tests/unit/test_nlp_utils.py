"""Tests for backend/app/core/nlp_utils.py -- chunk_transcript_by_time."""

from app.core.nlp_utils import chunk_transcript_by_time


def _make_transcript(segments):
    """Helper: build a transcript dict from a list of (start, end, text) tuples."""
    return {
        "segments": [
            {"start": s, "end": e, "text": t} for s, e, t in segments
        ]
    }


def test_single_segment():
    transcript = _make_transcript([(0.0, 10.0, "Hello world")])
    chunks = chunk_transcript_by_time(transcript, chunk_size=60)
    assert len(chunks) == 1
    assert "Hello world" in chunks[0]


def test_multiple_chunks():
    transcript = _make_transcript([
        (0.0, 30.0, "First part"),
        (30.0, 55.0, "Second part"),
        (60.0, 90.0, "Third part"),
        (90.0, 115.0, "Fourth part"),
    ])
    chunks = chunk_transcript_by_time(transcript, chunk_size=60)
    assert len(chunks) == 2
    assert "First part" in chunks[0]
    assert "Third part" in chunks[1]


def test_empty_segments():
    transcript = {"segments": []}
    chunks = chunk_transcript_by_time(transcript, chunk_size=60)
    assert chunks == []


def test_chunk_boundary():
    transcript = _make_transcript([
        (0.0, 59.0, "Just before boundary"),
        (59.0, 61.0, "Crosses boundary"),
    ])
    chunks = chunk_transcript_by_time(transcript, chunk_size=60)
    assert len(chunks) >= 1
    combined = " ".join(chunks)
    assert "Just before boundary" in combined
    assert "Crosses boundary" in combined


def test_custom_chunk_size():
    transcript = _make_transcript([
        (0.0, 10.0, "A"),
        (10.0, 25.0, "B"),
        (30.0, 50.0, "C"),
        (55.0, 70.0, "D"),
        (70.0, 85.0, "E"),
    ])
    chunks = chunk_transcript_by_time(transcript, chunk_size=30)
    assert len(chunks) == 3
