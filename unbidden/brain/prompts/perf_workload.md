You write a workload that measures one HTTP endpoint of a {{framework}} application, inside the
application's own process, against a fresh empty database whose migrations have just been applied.

Write the file `.unbidden-lab/workload.py` defining `build(...) -> Callable[[], Response]`:
- `build()` seeds realistic synthetic data ONCE, then returns a function that performs exactly one request to
  `{{endpoint}}` and returns the client's response object itself (not only its status code): its status and its
  content are both checked, and the content is compared between the code before and after the change.
- `build()` runs inside a pytest test of the repository, after its fixtures and migrations. Its parameters are
  fixtures of the repository's test suite, by name (for example `def build(api_client, unique_user):`): use only
  the fixtures listed below (the ones visible where the workload runs) for the client, the database session and
  an authenticated user, rather than building your own. No `*args` or `**kwargs`: every parameter is a fixture.
  Import only names you can see in the code below.
- Seed at least {{rows}} rows in `{{table}}`, spread over at least {{owners}} distinct rows it references, so
  each owner has a small share. Create the referenced rows first, then the {{table}} rows. {{insert_rule}}
  Fill every non-null column (ids, foreign keys, timestamps from Python), commit, then run `ANALYZE` (both
  engines accept it).
- Call the endpoint as an ordinary user that owns some of the seeded rows, authenticated the same way the
  application's own tests do (shown below).
- The returned function is called {{calls}} times. The database's own statistics are read after the calls: the
  request must make it read `{{table}}` by the relation under study on every call, and the rows must be there. If the endpoint consumes what it acts on (a merge or a delete
  removes a row), prepare {{calls}} separate targets in `build()` and use a new one on each call, so every call
  does the same work and returns success.
- Only the standard library, the application's own modules and its installed dependencies. No network.
- The working directory is `{{cwd}}`, which is on `sys.path`.

{{async_rule}}

Reply with only the file, in one fenced block whose first line is `# file: .unbidden-lab/workload.py`.

{{feedback}}

The endpoint's handler (`{{handler_file}}`):
```python
{{handler}}
```

{{schema_label}} (`{{models_file}}`):
```python
{{models}}
```

The tables `{{table}}` references, whose rows you create first (fill their required columns too):
{{related_models}}

How the application's tests set up a client and authenticate:
{{test_examples}}
