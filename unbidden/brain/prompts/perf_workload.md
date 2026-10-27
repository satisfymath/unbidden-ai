You write a workload that measures one HTTP endpoint of a {{framework}} application, inside the
application's own process, against a fresh empty database whose migrations have just been applied.

Write the file `.unbidden-lab/workload.py` defining `build() -> Callable[[], int]`:
- `build()` seeds realistic synthetic data ONCE, then returns a function that performs exactly one request to
  `{{endpoint}}` and returns the HTTP status code.
- Seed at least {{rows}} rows in `{{table}}`, spread over at least {{owners}} distinct rows it references, so
  each owner has a small share. Create the referenced rows first, then the {{table}} rows, both with simple
  set-based SQL (`INSERT ... SELECT ... FROM generate_series(1, N) AS g(i)`), assigning each row's owner with
  plain arithmetic on `g.i` over the owners you created (no regular expressions, no clever joins). Never one
  ORM object per row. Commit, then run `ANALYZE`.
- `build()` runs inside a pytest test of the repository, after its fixtures and migrations; reuse the
  application's own engine/session and helpers.
- Call the endpoint as an ordinary user that owns some of the seeded rows, authenticated the same way the
  application's own tests do (shown below). Use the framework's test client on the application object.
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
