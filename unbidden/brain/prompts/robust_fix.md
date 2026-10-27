You fix a crash in a Python library with the smallest change that makes the failing test pass without changing
any other behavior. Never catch the exception just to hide it; fix the cause.

The failing property-based test:
```python
{{test}}
```

How it failed (falsifying example and traceback excerpt):
```
{{failure}}
```

The file where it crashes, `{{path}}`:
```python
{{source}}
```

Reply with the complete new content of `{{path}}` in one fenced block whose first line is `# file: {{path}}`.
No explanations.
