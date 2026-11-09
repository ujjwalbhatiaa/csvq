#!/usr/bin/env python3
"""csvq - run SQL-like queries against CSV files.

Usage:
    csvq "SELECT name, age FROM data.csv WHERE age > 30 ORDER BY age DESC LIMIT 5"
    csvq --count "SELECT * FROM data.csv WHERE city = 'Edmonton'"
    csvq --json "SELECT * FROM data.csv"
    csvq --delimiter ';' "SELECT * FROM data.csv"

Supported SQL subset:
    SELECT <cols | *> FROM <file>
        [WHERE <expr>] [ORDER BY <col> [ASC|DESC]] [LIMIT <n>]

WHERE expressions support =, !=, <, >, <=, >=, AND, OR, parentheses,
single-quoted string literals and numbers. Column names are the CSV
header names. Values are compared numerically when both sides look
numeric, otherwise as strings.
"""

import argparse
import csv
import json
import re
import sys

__version__ = "1.0.0"

KEYWORDS = {"SELECT", "FROM", "WHERE", "ORDER", "BY", "LIMIT", "AND", "OR",
            "ASC", "DESC"}

TOKEN_RE = re.compile(r"""
    \s*(?:
        (?P<string>'(?:[^']|'')*')
      | (?P<path>/[A-Za-z0-9_.\-/]*)
      | (?P<number>-?\d+(?:\.\d+)?)
      | (?P<op><=|>=|!=|=|<|>)
      | (?P<punct>[(),*])
      | (?P<word>[A-Za-z_][A-Za-z0-9_.\-/]*)
    )
""", re.VERBOSE)


class CsvqError(Exception):
    """A user-facing error: bad SQL, missing file, unknown column."""


class Token:
    def __init__(self, kind, value):
        self.kind = kind
        self.value = value

    def __repr__(self):
        return f"Token({self.kind!r}, {self.value!r})"


def tokenize(sql):
    """Split a query string into tokens."""
    tokens = []
    pos = 0
    while pos < len(sql):
        match = TOKEN_RE.match(sql, pos)
        if not match or match.end() == pos:
            raise CsvqError(f"Could not parse near: {sql[pos:pos + 20]!r}")
        pos = match.end()
        if match.group("string") is not None:
            raw = match.group("string")
            tokens.append(Token("string", raw[1:-1].replace("''", "'")))
        elif match.group("path") is not None:
            # Absolute file paths tokenize as words so FROM accepts them.
            tokens.append(Token("word", match.group("path")))
        elif match.group("number") is not None:
            tokens.append(Token("number", match.group("number")))
        elif match.group("op") is not None:
            tokens.append(Token("op", match.group("op")))
        elif match.group("punct") is not None:
            tokens.append(Token("punct", match.group("punct")))
        else:
            word = match.group("word")
            upper = word.upper()
            if upper in KEYWORDS:
                tokens.append(Token("keyword", upper))
            else:
                tokens.append(Token("word", word))
    tokens.append(Token("eof", None))
    return tokens


class Parser:
    """Recursive-descent parser for the csvq SQL subset."""

    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos]

    def next(self):
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def expect(self, kind, value=None):
        token = self.next()
        if token.kind != kind or (value is not None and token.value != value):
            wanted = value if value is not None else kind
            raise CsvqError(f"Expected {wanted!r} but found {token.value!r}")
        return token

    def expect_keyword(self, word):
        token = self.next()
        if token.kind != "keyword" or token.value != word:
            raise CsvqError(f"Expected {word!r} but found {token.value!r}")

    def at_keyword(self, word):
        token = self.peek()
        return token.kind == "keyword" and token.value == word

    def parse(self):
        self.expect_keyword("SELECT")
        columns = self.parse_column_list()
        self.expect_keyword("FROM")
        token = self.next()
        if token.kind != "word":
            raise CsvqError(f"Expected a file name after FROM, found {token.value!r}")
        filename = token.value
        where = None
        order_by = None
        order_desc = False
        limit = None
        if self.at_keyword("WHERE"):
            self.next()
            where = self.parse_or()
        if self.at_keyword("ORDER"):
            self.next()
            self.expect_keyword("BY")
            col = self.next()
            if col.kind != "word":
                raise CsvqError(f"Expected a column name after ORDER BY, found {col.value!r}")
            order_by = col.value
            if self.at_keyword("ASC"):
                self.next()
            elif self.at_keyword("DESC"):
                self.next()
                order_desc = True
        if self.at_keyword("LIMIT"):
            self.next()
            token = self.next()
            if token.kind != "number" or "." in token.value or int(token.value) < 0:
                raise CsvqError(f"LIMIT expects a non-negative integer, found {token.value!r}")
            limit = int(token.value)
        if self.peek().kind != "eof":
            raise CsvqError(f"Unexpected trailing input: {self.peek().value!r}")
        return {
            "columns": columns,
            "file": filename,
            "where": where,
            "order_by": order_by,
            "order_desc": order_desc,
            "limit": limit,
        }

    def parse_column_list(self):
        if self.peek().kind == "punct" and self.peek().value == "*":
            self.next()
            return ["*"]
        columns = []
        while True:
            token = self.next()
            if token.kind != "word":
                raise CsvqError(f"Expected a column name, found {token.value!r}")
            columns.append(token.value)
            if self.peek().kind == "punct" and self.peek().value == ",":
                self.next()
                continue
            return columns

    def parse_or(self):
        node = self.parse_and()
        while self.at_keyword("OR"):
            self.next()
            node = ("OR", node, self.parse_and())
        return node

    def parse_and(self):
        node = self.parse_atom()
        while self.at_keyword("AND"):
            self.next()
            node = ("AND", node, self.parse_atom())
        return node

    def parse_atom(self):
        if self.peek().kind == "punct" and self.peek().value == "(":
            self.next()
            node = self.parse_or()
            token = self.next()
            if token.kind != "punct" or token.value != ")":
                raise CsvqError(f"Expected ')' but found {token.value!r}")
            return node
        return self.parse_comparison()

    def parse_comparison(self):
        left = self.parse_operand()
        token = self.next()
        if token.kind != "op":
            raise CsvqError(f"Expected a comparison operator, found {token.value!r}")
        right = self.parse_operand()
        return ("CMP", token.value, left, right)

    def parse_operand(self):
        token = self.next()
        if token.kind == "word":
            return ("col", token.value)
        if token.kind in ("string", "number"):
            return ("lit", token.value)
        raise CsvqError(f"Expected a column or a value, found {token.value!r}")


def parse_query(sql):
    """Parse a query string into a query dict."""
    if not sql or not sql.strip():
        raise CsvqError("Empty query")
    return Parser(tokenize(sql)).parse()


def _is_number(value):
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _compare(op, left, right):
    """Compare two cell values; numeric when both sides look numeric."""
    if _is_number(left) and _is_number(right):
        left, right = float(left), float(right)
    if op == "=":
        return left == right
    if op == "!=":
        return left != right
    if op == "<":
        return left < right
    if op == ">":
        return left > right
    if op == "<=":
        return left <= right
    if op == ">=":
        return left >= right
    raise CsvqError(f"Unknown operator {op!r}")


def _eval(node, row, columns):
    kind = node[0]
    if kind == "AND":
        return _eval(node[1], row, columns) and _eval(node[2], row, columns)
    if kind == "OR":
        return _eval(node[1], row, columns) or _eval(node[2], row, columns)
    _, op, left, right = node
    return _compare(op, _operand_value(left, row, columns),
                    _operand_value(right, row, columns))


def _operand_value(operand, row, columns):
    kind, value = operand
    if kind == "lit":
        return value
    column = _resolve_column(value, columns)
    return row[column]


def _resolve_column(name, columns):
    """Find a header name, case-insensitively."""
    for column in columns:
        if column.lower() == name.lower():
            return column
    raise CsvqError(f"Unknown column: {name!r}")


def _sort_key(value):
    if _is_number(value):
        return (0, float(value), "")
    return (1, 0.0, value)


def run_query(query, delimiter=","):
    """Execute a parsed query against its CSV file. Returns (columns, rows)."""
    try:
        with open(query["file"], newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle, delimiter=delimiter)
            if reader.fieldnames is None:
                raise CsvqError(f"No header row found in {query['file']!r}")
            headers = reader.fieldnames
            rows = list(reader)
    except FileNotFoundError:
        raise CsvqError(f"File not found: {query['file']!r}")
    except OSError as exc:
        raise CsvqError(f"Could not read {query['file']!r}: {exc}")

    if query["columns"] == ["*"]:
        columns = list(headers)
    else:
        columns = [_resolve_column(name, headers) for name in query["columns"]]

    if query["where"] is not None:
        _resolve_where_columns(query["where"], headers)
        rows = [row for row in rows if _eval(query["where"], row, headers)]

    if query["order_by"] is not None:
        order_col = _resolve_column(query["order_by"], headers)
        rows.sort(key=lambda row: _sort_key(row[order_col]),
                  reverse=query["order_desc"])

    if query["limit"] is not None:
        rows = rows[:query["limit"]]

    return columns, [{col: row[col] for col in columns} for row in rows]


def _resolve_where_columns(node, headers):
    kind = node[0]
    if kind in ("AND", "OR"):
        _resolve_where_columns(node[1], headers)
        _resolve_where_columns(node[2], headers)
    else:
        for operand in (node[2], node[3]):
            if operand[0] == "col":
                _resolve_column(operand[1], headers)


def format_table(columns, rows):
    """Render rows as a plain-text table."""
    widths = [len(col) for col in columns]
    for row in rows:
        for i, col in enumerate(columns):
            widths[i] = max(widths[i], len(str(row[col])))
    lines = []
    lines.append(" | ".join(col.ljust(widths[i]) for i, col in enumerate(columns)))
    lines.append("-+-".join("-" * width for width in widths))
    for row in rows:
        lines.append(" | ".join(str(row[col]).ljust(widths[i])
                                for i, col in enumerate(columns)))
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="csvq",
        description="Run SQL-like queries against CSV files.")
    parser.add_argument("query", help="SQL query, e.g. "
                        "\"SELECT name FROM data.csv WHERE age > 30\"")
    parser.add_argument("--count", action="store_true",
                        help="Print only the number of matching rows")
    parser.add_argument("--json", action="store_true",
                        help="Print matching rows as JSON")
    parser.add_argument("--table", action="store_true",
                        help="Print matching rows as a table (default)")
    parser.add_argument("--delimiter", default=",",
                        help="CSV field delimiter (default: ',')")
    args = parser.parse_args(argv)

    try:
        query = parse_query(args.query)
        columns, rows = run_query(query, delimiter=args.delimiter)
    except CsvqError as exc:
        print(f"csvq: error: {exc}", file=sys.stderr)
        return 2

    if args.count:
        print(len(rows))
    elif args.json:
        print(json.dumps(rows, indent=2))
    else:
        if rows:
            print(format_table(columns, rows))
        elif columns:
            print(format_table(columns, []))
    return 0


if __name__ == "__main__":
    sys.exit(main())
