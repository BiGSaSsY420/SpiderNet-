"""Chunker behaviour, including the non-advancing-cursor hang."""

import pytest

from app.utils.file_parser import split_text_into_chunks


def test_overlap_equal_to_chunk_size_terminates():
    """overlap >= chunk_size used to leave the cursor stationary and spin forever."""
    chunks = split_text_into_chunks("x" * 2000, chunk_size=100, overlap=100)
    assert chunks
    assert all(c for c in chunks)


def test_overlap_greater_than_chunk_size_terminates():
    chunks = split_text_into_chunks("y" * 1000, chunk_size=50, overlap=500)
    assert chunks


def test_negative_overlap_is_not_allowed_to_skip_text():
    chunks = split_text_into_chunks("z" * 500, chunk_size=100, overlap=-50)
    assert "".join(chunks).count("z") >= 500


def test_zero_chunk_size_raises_rather_than_hanging():
    with pytest.raises(ValueError):
        split_text_into_chunks("abc" * 100, chunk_size=0, overlap=0)


def test_short_text_returns_single_chunk():
    assert split_text_into_chunks("short", chunk_size=500) == ["short"]


def test_whitespace_only_text_returns_nothing():
    assert split_text_into_chunks("   \n\n  ", chunk_size=500) == []


def test_chunks_cover_the_whole_input():
    text = "".join(f"Sentence number {i}. " for i in range(200))
    chunks = split_text_into_chunks(text, chunk_size=200, overlap=20)
    assert len(chunks) > 1
    # every chunk is non-empty and within a sane bound of the requested size
    assert all(0 < len(c) <= 200 + 20 for c in chunks)
    # nothing is dropped: the first and last content both survive
    assert "Sentence number 0." in chunks[0]
    assert "Sentence number 199." in chunks[-1]


def test_splits_prefer_sentence_boundaries():
    text = "第一句话。" * 60
    chunks = split_text_into_chunks(text, chunk_size=100, overlap=10)
    assert len(chunks) > 1
    assert chunks[0].endswith("。")
