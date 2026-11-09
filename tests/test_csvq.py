"""Tests for csvq - SQL-like queries against CSV files."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import csvq

PEOPLE = (
    "name,age,city\n"
    "Alice,34,Edmonton\n"
    "Bob,28,Calgary\n"
    "Carol,41,Edmonton\n"
    "Dave,30,Toronto\n"
    "Eve,22,Edmonton\n"
)


@pytest.fixture
def people_csv(tmp_path):
    path = tmp_path / "people.csv"
    path.write_text(PEOPLE)
    return path


def run_cli(*args):
    return subprocess.run(
        [sys.executable, str(Path(csvq.__file__)), *args],
        capture_output=True, text=True)


def query(csv_path, sql, delimiter=","):
    parsed = csvq.parse_query(sql.replace("people.csv", str(csv_path)))
    return csvq.run_query(parsed, delimiter=delimiter)


# --- SELECT ---

def test_select_columns(people_csv):
    columns, rows = query(people_csv, "SELECT name, age FROM people.csv")
    assert columns == ["name", "age"]
    assert rows == [
        {"name": "Alice", "age": "34"},
        {"name": "Bob", "age": "28"},
        {"name": "Carol", "age": "41"},
        {"name": "Dave", "age": "30"},
        {"name": "Eve", "age": "22"},
    ]


def test_select_star(people_csv):
    columns, rows = query(people_csv, "SELECT * FROM people.csv")
    assert columns == ["name", "age", "city"]
    assert len(rows) == 5
    assert rows[0] == {"name": "Alice", "age": "34", "city": "Edmonton"}


def test_select_single_column(people_csv):
    columns, rows = query(people_csv, "SELECT city FROM people.csv")
    assert columns == ["city"]
    assert [row["city"] for row in rows] == [
        "Edmonton", "Calgary", "Edmonton", "Toronto", "Edmonton"]


def test_keywords_case_insensitive(people_csv):
    columns, rows = query(people_csv, "select name from people.csv where age > 30")
    assert columns == ["name"]
    assert [row["name"] for row in rows] == ["Alice", "Carol"]


def test_column_names_case_insensitive(people_csv):
    _, rows = query(people_csv, "SELECT NAME FROM people.csv WHERE AGE > 40")
    assert rows == [{"name": "Carol"}]


# --- WHERE ---

def test_where_numeric_greater_than(people_csv):
    _, rows = query(people_csv, "SELECT name FROM people.csv WHERE age > 30")
    assert [row["name"] for row in rows] == ["Alice", "Carol"]


def test_where_numeric_less_than_or_equal(people_csv):
    _, rows = query(people_csv, "SELECT name FROM people.csv WHERE age <= 28")
    assert [row["name"] for row in rows] == ["Bob", "Eve"]


def test_where_numeric_less_than(people_csv):
    _, rows = query(people_csv, "SELECT name FROM people.csv WHERE age < 30")
    assert [row["name"] for row in rows] == ["Bob", "Eve"]


def test_where_numeric_greater_than_or_equal(people_csv):
    _, rows = query(people_csv, "SELECT name FROM people.csv WHERE age >= 34")
    assert [row["name"] for row in rows] == ["Alice", "Carol"]


def test_where_numeric_equals(people_csv):
    _, rows = query(people_csv, "SELECT name FROM people.csv WHERE age = 30")
    assert rows == [{"name": "Dave"}]


def test_where_numeric_not_equals(people_csv):
    _, rows = query(people_csv, "SELECT name FROM people.csv WHERE age != 30")
    assert [row["name"] for row in rows] == ["Alice", "Bob", "Carol", "Eve"]


def test_where_string_equals(people_csv):
    _, rows = query(people_csv, "SELECT name FROM people.csv WHERE city = 'Edmonton'")
    assert [row["name"] for row in rows] == ["Alice", "Carol", "Eve"]


def test_where_string_not_equals(people_csv):
    _, rows = query(people_csv, "SELECT name FROM people.csv WHERE city != 'Edmonton'")
    assert [row["name"] for row in rows] == ["Bob", "Dave"]


def test_where_string_less_than(people_csv):
    # String comparison is lexicographic.
    _, rows = query(people_csv, "SELECT name FROM people.csv WHERE city < 'Edmonton'")
    assert [row["name"] for row in rows] == ["Bob"]


def test_where_and(people_csv):
    _, rows = query(
        people_csv,
        "SELECT name FROM people.csv WHERE city = 'Edmonton' AND age > 30")
    assert [row["name"] for row in rows] == ["Alice", "Carol"]


def test_where_or(people_csv):
    _, rows = query(
        people_csv,
        "SELECT name FROM people.csv WHERE city = 'Calgary' OR city = 'Toronto'")
    assert [row["name"] for row in rows] == ["Bob", "Dave"]


def test_where_parentheses(people_csv):
    _, rows = query(
        people_csv,
        "SELECT name FROM people.csv WHERE (city = 'Edmonton' OR city = 'Calgary')"
        " AND age < 30")
    assert [row["name"] for row in rows] == ["Bob", "Eve"]


def test_where_and_or_precedence(people_csv):
    # AND binds tighter than OR: city = 'Toronto' OR (city = 'Edmonton' AND age > 40)
    _, rows = query(
        people_csv,
        "SELECT name FROM people.csv WHERE city = 'Toronto' OR city = 'Edmonton'"
        " AND age > 40")
    assert [row["name"] for row in rows] == ["Carol", "Dave"]


def test_no_matches_returns_empty(people_csv):
    _, rows = query(people_csv, "SELECT name FROM people.csv WHERE age > 100")
    assert rows == []


# --- ORDER BY / LIMIT ---

def test_order_by_asc(people_csv):
    _, rows = query(people_csv, "SELECT name, age FROM people.csv ORDER BY age ASC")
    assert [row["name"] for row in rows] == ["Eve", "Bob", "Dave", "Alice", "Carol"]


def test_order_by_desc(people_csv):
    _, rows = query(people_csv, "SELECT name, age FROM people.csv ORDER BY age DESC")
    assert [row["name"] for row in rows] == ["Carol", "Alice", "Dave", "Bob", "Eve"]


def test_order_by_default_is_asc(people_csv):
    _, rows = query(people_csv, "SELECT name FROM people.csv ORDER BY name")
    assert [row["name"] for row in rows] == ["Alice", "Bob", "Carol", "Dave", "Eve"]


def test_order_by_string_column(people_csv):
    _, rows = query(people_csv, "SELECT name FROM people.csv ORDER BY city DESC")
    # Stable sort: equal cities keep their original relative order.
    assert [row["name"] for row in rows] == ["Dave", "Alice", "Carol", "Eve", "Bob"]


def test_limit(people_csv):
    _, rows = query(people_csv, "SELECT name FROM people.csv LIMIT 2")
    assert [row["name"] for row in rows] == ["Alice", "Bob"]


def test_limit_zero(people_csv):
    _, rows = query(people_csv, "SELECT name FROM people.csv LIMIT 0")
    assert rows == []


def test_order_by_and_limit_combined(people_csv):
    _, rows = query(
        people_csv,
        "SELECT name, age FROM people.csv WHERE age > 30 ORDER BY age DESC LIMIT 1")
    assert rows == [{"name": "Carol", "age": "41"}]


# --- CLI output modes ---

def test_cli_table_output(people_csv):
    result = run_cli(f"SELECT name, age FROM {people_csv} WHERE age > 40")
    assert result.returncode == 0
    assert "Carol" in result.stdout
    assert "41" in result.stdout
    assert "name" in result.stdout


def test_cli_no_matches_exit_zero(people_csv):
    result = run_cli(f"SELECT name FROM {people_csv} WHERE age > 100")
    assert result.returncode == 0
    assert "Alice" not in result.stdout


def test_cli_count_flag(people_csv):
    result = run_cli("--count", f"SELECT * FROM {people_csv} WHERE city = 'Edmonton'")
    assert result.returncode == 0
    assert result.stdout.strip() == "3"


def test_cli_count_zero(people_csv):
    result = run_cli("--count", f"SELECT * FROM {people_csv} WHERE age > 100")
    assert result.returncode == 0
    assert result.stdout.strip() == "0"


def test_cli_json_flag(people_csv):
    result = run_cli("--json", f"SELECT name, age FROM {people_csv} WHERE age = 30")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data == [{"name": "Dave", "age": "30"}]


def test_cli_json_flag_empty(people_csv):
    result = run_cli("--json", f"SELECT * FROM {people_csv} WHERE age > 100")
    assert result.returncode == 0
    assert json.loads(result.stdout) == []


# --- Delimiter ---

def test_delimiter_option(tmp_path):
    path = tmp_path / "semi.csv"
    path.write_text("name;age\nAlice;34\nBob;28\n")
    parsed = csvq.parse_query(f"SELECT name FROM {path} WHERE age > 30")
    _, rows = csvq.run_query(parsed, delimiter=";")
    assert rows == [{"name": "Alice"}]


def test_cli_delimiter_flag(tmp_path):
    path = tmp_path / "semi.csv"
    path.write_text("name;age\nAlice;34\nBob;28\n")
    result = run_cli("--delimiter", ";", f"SELECT name FROM {path} WHERE age > 30")
    assert result.returncode == 0
    assert "Alice" in result.stdout
    assert "Bob" not in result.stdout


# --- Errors ---

def test_missing_file_exits_2(tmp_path):
    result = run_cli(f"SELECT * FROM {tmp_path / 'nope.csv'}")
    assert result.returncode == 2
    assert "not found" in result.stderr.lower()


def test_unknown_column_exits_2(people_csv):
    result = run_cli(f"SELECT salary FROM {people_csv}")
    assert result.returncode == 2
    assert "salary" in result.stderr.lower()


def test_unknown_column_in_where_exits_2(people_csv):
    result = run_cli(f"SELECT name FROM {people_csv} WHERE salary > 10")
    assert result.returncode == 2
    assert "salary" in result.stderr.lower()


def test_bad_sql_exits_2(people_csv):
    result = run_cli(f"SELECT FROM {people_csv}")
    assert result.returncode == 2
    assert result.stderr.strip() != ""


def test_trailing_garbage_exits_2(people_csv):
    result = run_cli(f"SELECT name FROM {people_csv} FROBNICATE")
    assert result.returncode == 2


def test_missing_operator_exits_2(people_csv):
    result = run_cli(f"SELECT name FROM {people_csv} WHERE age 30")
    assert result.returncode == 2


def test_unbalanced_parenthesis_exits_2(people_csv):
    result = run_cli(f"SELECT name FROM {people_csv} WHERE (age > 30")
    assert result.returncode == 2


def test_negative_limit_exits_2(people_csv):
    result = run_cli(f"SELECT name FROM {people_csv} LIMIT -1")
    assert result.returncode == 2
