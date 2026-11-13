"""A Steam workshop name must not become an Excel formula in exported CSV."""
import csv
import io

from backend.exporter import csv_response


def test_excel_formula_injection_is_escaped():
    rows = [["=HYPERLINK(\"https://evil.example\")", " +SUM(1,1)", "@cmd", "ordinary", 123, -5]]
    response = csv_response("demo.csv", ["a", "b", "c", "d", "e", "f"], rows)
    parsed = list(csv.reader(io.StringIO(response.body.decode("utf-8-sig"))))
    assert parsed[1] == ["'=HYPERLINK(\"https://evil.example\")", "' +SUM(1,1)", "'@cmd", "ordinary", "123", "-5"]


def test_empty_rows_and_filename_are_stable():
    response = csv_response("items.csv", ["ID", "name"], [[7, None]])
    assert response.headers["content-disposition"] == "attachment; filename=items.csv"
    assert list(csv.reader(io.StringIO(response.body.decode("utf-8-sig")))) == [["ID", "name"], ["7", ""]]
