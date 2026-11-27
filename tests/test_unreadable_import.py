"""Analyze a month: files that aren't a bank CSV at all are reported as unreadable,
not sent to Check your columns."""

from pathlib import Path

import pytest

from finsight.month_analysis import UnreadableCsvError, analyze_month

FIXTURES = Path(__file__).resolve().parent / "fixtures"

NOT_A_CSV = {
    "empty file": b"",
    "binary garbage": bytes(range(256)) * 4,
    "a PDF": b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Length 42 /Filter /FlateDecode >>\nstream\nx\x9c\x00\x01\x02\x03\x00\nendstream\n",
    "a zip (xlsx)": b"PK\x03\x04\x14\x00\x06\x00\x08\x00\x00\x00!\x00\xb5U0#\xf4\x00\x00\x00L\x02\x00\x00\x13\x00",
}


@pytest.mark.parametrize("data", NOT_A_CSV.values(), ids=NOT_A_CSV.keys())
def test_a_file_that_is_not_a_csv_is_unreadable(data):
    with pytest.raises(UnreadableCsvError):
        analyze_month(data, [])


def test_an_unrecognised_but_readable_csv_still_asks_to_check_columns():
    analysis = analyze_month((FIXTURES / "undetectable_columns.csv").read_bytes(), [])

    assert analysis.columns_need_checking


def test_a_latin1_csv_with_accents_is_readable():
    analysis = analyze_month((FIXTURES / "comma_decimal_cp1252.csv").read_bytes(), [])

    assert not analysis.columns_need_checking
