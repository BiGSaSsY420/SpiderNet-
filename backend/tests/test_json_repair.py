"""LLM JSON repair: must fix truncation without ever corrupting good content."""

import json
import pytest

from app.utils.json_repair import repair_json, strip_wrappers


# --- the shapes the old implementation got wrong -------------------------

def test_truncated_mid_string():
    assert repair_json('{"name": "Alice') == {"name": "Alice"}


def test_braces_inside_a_string_are_not_counted():
    """The old brace-counting repair turned this into invalid JSON."""
    out = repair_json('{"bio": "uses {braces} here", "n": 1')
    # "n" is dropped on purpose: a trailing 1 could be a truncated 15.
    assert out == {"bio": "uses {braces} here"}


def test_unterminated_trailing_number_is_dropped_not_guessed():
    """123 truncated to 12 parses fine and is silently wrong - so drop it."""
    assert repair_json('{"rounds": 10, "agents": 12') == {"rounds": 10}


def test_scalar_closed_by_a_delimiter_is_kept():
    assert repair_json('{"rounds": 10, "agents": 12}') == {"rounds": 10, "agents": 12}


def test_trailing_comma_is_dropped():
    assert repair_json('{"a": 1,') == {"a": 1}


def test_dangling_key_is_dropped():
    assert repair_json('{"a": 1, "b":') == {"a": 1}


def test_ends_with_opening_quote():
    assert repair_json('{"a": "') == {"a": ""}


def test_unrepairable_returns_none_not_garbage():
    """Structurally broken (not merely truncated) input must not be guessed at."""
    assert repair_json('{"a": [1,2]]}') is None


# --- the property that matters most --------------------------------------

VALID = [
    {"a": 1},
    {"bio": "text with {braces} and [brackets]"},
    {"nested": {"deep": {"deeper": [1, 2, {"x": "y"}]}}},
    {"unicode": "中文内容，含标点。"},
    {"escaped": 'a \\" quote and a \\\\ backslash'},
    {"empty_obj": {}, "empty_arr": [], "null": None, "bool": True},
]


@pytest.mark.parametrize("payload", VALID)
def test_valid_json_passes_through_unchanged(payload):
    assert repair_json(json.dumps(payload, ensure_ascii=False)) == payload


def _is_truthful_prefix(partial, full) -> bool:
    """Is `partial` a faithful (possibly truncated) view of `full`?"""
    if isinstance(partial, dict) and isinstance(full, dict):
        return all(k in full and _is_truthful_prefix(v, full[k])
                   for k, v in partial.items())
    if isinstance(partial, list) and isinstance(full, list):
        return (len(partial) <= len(full)
                and all(_is_truthful_prefix(p, f) for p, f in zip(partial, full)))
    if isinstance(partial, str) and isinstance(full, str):
        return full.startswith(partial)
    return partial == full


@pytest.mark.parametrize("payload", VALID)
def test_truncation_never_yields_wrong_values(payload):
    """
    The property that matters: for every possible truncation point, the repair
    either returns None or returns something truthful. It may lose data; it may
    never invent or alter it.
    """
    text = json.dumps(payload, ensure_ascii=False)
    for cut in range(1, len(text)):
        out = repair_json(text[:cut])
        if out is None:
            continue
        assert _is_truthful_prefix(out, payload), (
            f"prefix {text[:cut]!r} repaired to {out!r}, which misstates {payload!r}"
        )


# --- wrappers -------------------------------------------------------------

def test_markdown_fences_are_stripped():
    assert repair_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert repair_json('```\n{"a": 1}\n```') == {"a": 1}
    assert repair_json('```JSON\n{"a": 1}\n```') == {"a": 1}


def test_think_blocks_are_stripped():
    assert repair_json('<think>reasoning here</think>{"a": 1}') == {"a": 1}


def test_unclosed_think_block_discards_the_tail():
    assert strip_wrappers('{"a": 1}<think>dangling') == '{"a": 1}'


def test_prose_before_the_object_is_ignored():
    assert repair_json('Here is the config:\n{"a": 1}') == {"a": 1}


def test_empty_input_returns_none():
    assert repair_json('') is None
    assert repair_json('   ') is None
    assert repair_json('not json at all') is None


def test_json_array_at_top_level_is_rejected():
    """Callers expect an object; a bare array is not a valid config."""
    assert repair_json('[1, 2, 3]') is None
