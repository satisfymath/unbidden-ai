You fix the code of a Python project so that tests the team wrote, which fail on its current commit, pass again,
with the smallest change that does not alter any other behavior. The tests are the specification: never change a
test, never skip it, never catch an exception just to hide it. Fix the cause in the code under test.

The failing tests and how they fail (their reports, traceback included):
```
{{failures}}
```

The test file `{{test_path}}`:
```python
{{test_source}}
```

{{sources}}

Reply with the complete new content of each code file you change, each in its own fenced block whose first line is
`# file: <path>`. Change only the files shown above that are not tests. No explanations.
