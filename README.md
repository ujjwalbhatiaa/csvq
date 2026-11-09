# csvq

Run SQL-like queries against CSV files — no database, no dependencies, just Python.

```sh
csvq "SELECT name, age FROM data.csv WHERE age > 30 ORDER BY age DESC LIMIT 5"
```

## Install

csvq is a single Python file and needs nothing beyond Python 3.8+.

```sh
# Run it directly
python3 csvq.py "SELECT * FROM data.csv"

# Or make it executable and put it on your PATH
chmod +x csvq.py
cp csvq.py /usr/local/bin/csvq
```

## Usage

```
csvq [--count] [--json] [--table] [--delimiter DELIM] "SQL query"
```

| Flag | What it does |
| --- | --- |
| `--count` | Print only the number of matching rows |
| `--json` | Print matching rows as JSON |
| `--table` | Print matching rows as a table (default) |
| `--delimiter DELIM` | CSV field delimiter (default: `,`) |

### Supported SQL

```
SELECT <columns | *> FROM <file>
  [WHERE <expression>]
  [ORDER BY <column> [ASC | DESC]]
  [LIMIT <n>]
```

- **WHERE** supports `=`, `!=`, `<`, `>`, `<=`, `>=`, `AND`, `OR`, and parentheses, plus single-quoted string literals (`'Edmonton'`) and numbers.
- Column names are the CSV header names.
- Values are compared numerically when both sides look numeric, otherwise as strings.
- Missing file, bad SQL, or an unknown column prints a clean error and exits with code `2`. No matches prints an empty table and exits `0`.

## Examples

Given `employees.csv`:

```csv
name,age,city,role
Alice,34,Edmonton,Backend Engineer
Bob,28,Calgary,Data Analyst
Carol,41,Edmonton,ML Engineer
Dave,30,Toronto,QA Engineer
Eve,22,Edmonton,Intern
```

```sh
# Pick columns, filter, sort, limit
$ csvq "SELECT name, age FROM employees.csv WHERE age > 30 ORDER BY age DESC LIMIT 2"
name  | age
------+----
Carol | 41
Alice | 34

# Count matching rows
$ csvq --count "SELECT * FROM employees.csv WHERE city = 'Edmonton'"
3

# JSON output
$ csvq --json "SELECT name FROM employees.csv WHERE role = 'Intern'"
[
  {
    "name": "Eve"
  }
]

# Combine conditions
$ csvq "SELECT name FROM employees.csv WHERE city = 'Edmonton' AND age < 30"
name
----
Eve

# Semicolon-delimited files
$ csvq --delimiter ';' "SELECT name FROM data.csv WHERE age > 30"
```

## Tests

```sh
python3 -m pytest
```

## License

MIT — see [LICENSE](LICENSE).
