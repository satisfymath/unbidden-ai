You fix the code of a Python project so that tests the team wrote, which fail on its current commit, pass again,
with the smallest change that does not alter any other behavior. The tests are the specification: never change a
test, never skip it, never catch an exception just to hide it. Fix the cause in the code under test.

The failing tests and how they fail (their reports, traceback included):
```
{{failures}}
```

The failing tests, from `{{test_path}}` (other tests of the file left out):
```python
{{test_source}}
```

{{how}}

{{sources}}
