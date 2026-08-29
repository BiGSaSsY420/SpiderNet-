"""Seed material arrives as user-uploaded files, so parsing must not crash on them."""

import pytest

from app.services.text_processor import TextProcessor
from app.utils.file_parser import FileParser, _read_text_with_fallback


# --- encoding fallbacks --------------------------------------------------

def test_utf8_is_read_directly(tmp_path):
    path = tmp_path / "note.txt"
    path.write_text("第一句话。Hello.", encoding="utf-8")

    assert _read_text_with_fallback(str(path)) == "第一句话。Hello."


def test_gbk_text_is_detected_rather_than_mangled(tmp_path):
    """Chinese source documents are routinely GBK; UTF-8 decoding raises on them."""
    path = tmp_path / "legacy.txt"
    path.write_bytes("中文内容测试，这是一段用于编码探测的文字。".encode("gbk"))

    text = _read_text_with_fallback(str(path))
    assert "中文内容" in text


def test_undecodable_bytes_fall_back_instead_of_raising(tmp_path):
    path = tmp_path / "binary.txt"
    path.write_bytes(b"\xff\xfe\x00\x01 plain tail")

    text = _read_text_with_fallback(str(path))
    assert isinstance(text, str)


def test_an_empty_file_reads_as_an_empty_string(tmp_path):
    path = tmp_path / "empty.txt"
    path.write_bytes(b"")

    assert _read_text_with_fallback(str(path)) == ""


# --- format dispatch -----------------------------------------------------

@pytest.mark.parametrize("name", ["doc.txt", "doc.md", "doc.markdown", "DOC.TXT", "doc.MD"])
def test_supported_text_formats_are_extracted(tmp_path, name):
    path = tmp_path / name
    path.write_text("content here", encoding="utf-8")

    assert FileParser.extract_text(str(path)) == "content here"


@pytest.mark.parametrize("name", ["doc.docx", "doc.exe", "doc", "doc.pdf.zip"])
def test_unsupported_formats_are_rejected(tmp_path, name):
    path = tmp_path / name
    path.write_text("content", encoding="utf-8")

    with pytest.raises(ValueError):
        FileParser.extract_text(str(path))


def test_a_missing_file_is_reported_as_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        FileParser.extract_text(str(tmp_path / "nope.txt"))


def test_pdf_text_is_extracted(tmp_path):
    fitz = pytest.importorskip("fitz")

    path = tmp_path / "doc.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Extracted from a PDF")
    doc.save(str(path))
    doc.close()

    assert "Extracted from a PDF" in FileParser.extract_text(str(path))


# --- merging several uploads --------------------------------------------

def test_multiple_files_are_merged_with_their_names(tmp_path):
    first = tmp_path / "a.txt"
    second = tmp_path / "b.md"
    first.write_text("alpha", encoding="utf-8")
    second.write_text("beta", encoding="utf-8")

    merged = FileParser.extract_from_multiple([str(first), str(second)])

    assert "a.txt" in merged and "alpha" in merged
    assert "b.md" in merged and "beta" in merged


def test_one_bad_file_does_not_lose_the_others(tmp_path):
    """A single unreadable upload must not fail the whole ingest."""
    good = tmp_path / "good.txt"
    good.write_text("keep me", encoding="utf-8")

    merged = FileParser.extract_from_multiple([str(tmp_path / "missing.txt"), str(good)])

    assert "keep me" in merged
    assert "提取失败" in merged


def test_merging_nothing_returns_an_empty_string():
    assert FileParser.extract_from_multiple([]) == ""


# --- TextProcessor -------------------------------------------------------

def test_preprocess_normalises_line_endings():
    assert TextProcessor.preprocess_text("a\r\nb\rc") == "a\nb\nc"


def test_preprocess_collapses_runs_of_blank_lines():
    assert TextProcessor.preprocess_text("a\n\n\n\n\nb") == "a\n\nb"


def test_preprocess_trims_each_line_and_the_whole_text():
    assert TextProcessor.preprocess_text("  \n  padded  \n  ends  \n  ") == "padded\nends"


def test_preprocess_leaves_clean_text_alone():
    text = "第一段。\n\n第二段。"
    assert TextProcessor.preprocess_text(text) == text


def test_preprocess_handles_an_empty_string():
    assert TextProcessor.preprocess_text("") == ""


def test_text_stats_count_chars_lines_and_words():
    stats = TextProcessor.get_text_stats("one two\nthree")

    assert stats == {"total_chars": 13, "total_lines": 2, "total_words": 3}


def test_text_stats_on_an_empty_string():
    assert TextProcessor.get_text_stats("") == {
        "total_chars": 0,
        "total_lines": 1,
        "total_words": 0,
    }


def test_split_text_delegates_to_the_chunker():
    chunks = TextProcessor.split_text("x" * 1200, chunk_size=500, overlap=50)

    assert len(chunks) > 1
    assert all(chunks)


def test_extract_from_files_delegates_to_the_parser(tmp_path):
    path = tmp_path / "seed.txt"
    path.write_text("seed material", encoding="utf-8")

    assert "seed material" in TextProcessor.extract_from_files([str(path)])
