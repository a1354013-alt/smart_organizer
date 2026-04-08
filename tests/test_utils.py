import pytest

from core import FileUtils


def test_sanitize_filename_removes_illegal_chars_and_dotdot():
    out = FileUtils.sanitize_filename('a<>:"/\\\\|?*..b.pdf')
    assert out.endswith(".pdf")
    assert "<" not in out and ">" not in out and ":" not in out
    assert ".." not in out


def test_sanitize_filename_empty_name_fallback():
    assert FileUtils.sanitize_filename("") == "untitled_file"
    assert FileUtils.sanitize_filename("..") == "untitled_file"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2026-04-08", "2026-04-08"),
        ("2026/4/8", "2026-04-08"),
        ("2026.04.08", "2026-04-08"),
        ("2026-04-08T12:34:56", "2026-04-08"),
    ],
)
def test_normalize_standard_date(raw, expected):
    assert FileUtils.normalize_standard_date(raw) == expected


def test_normalize_standard_date_invalid_returns_unknown():
    assert FileUtils.normalize_standard_date("2026-13-40") == FileUtils.DEFAULT_UNKNOWN_DATE


def test_escape_fts_query_splits_words_and_quotes():
    assert FileUtils.escape_fts_query("foo bar") == '"foo" "bar"'


def test_escape_fts_query_strips_special_syntax_chars():
    assert FileUtils.escape_fts_query('a"b -c*(d)') == '"a" "b" "c" "d"'
