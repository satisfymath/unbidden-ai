You write a workload that measures one HTTP endpoint of a {{framework}} application, inside the
application's own process, against a fresh empty database whose migrations have just been applied.

Write the file `.unbidden-lab/workload.py` defining `build(...) -> Callable[[], int]`:
- `build()` seeds realistic synthetic data ONCE, then returns a function that performs exactly one request to
  `{{endpoint}}` and returns the HTTP status code.
- `build()` runs inside a pytest test of the repository, after its fixtures and migrations. Its parameters are
  fixtures of the repository's test suite, by name (for example `def build(api_client, unique_user):`): use the
  fixtures listed below for the client, the database session and an authenticated user rather than building
  your own. Import only names you can see in the code below.
- Seed at least {{rows}} rows in `{{table}}`, spread over at least {{owners}} distinct rows it references, so
  each owner has a small share. Create the referenced rows first, then the {{table}} rows. Insert them with
  SQLAlchemy Core in bulk, one statement per table with a list of dicts (`session.execute(insert(Model), rows)`),
  never one ORM object per row and never database-specific SQL: the tests may run on SQLite or on Postgres.
  Fill every non-null column (ids, foreign keys, timestamps from Python), commit, then run `ANALYZE` (both
  engines accept it).
- Call the endpoint as an ordinary user that owns some of the seeded rows, authenticated the same way the
  application's own tests do (shown below).
- Only the standard library, the application's own modules and its installed dependencies. No network.
- The working directory is `{{cwd}}`, which is on `sys.path`.

Reply with only the file, in one fenced block whose first line is `# file: .unbidden-lab/workload.py`.

{{feedback}}

The endpoint's handler (`{{handler_file}}`):
```python
{{handler}}
```

The data models (`{{models_file}}`):
```python
{{models}}
```

How the application's tests set up a client and authenticate:
{{test_examples}}
