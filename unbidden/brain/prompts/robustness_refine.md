Some of the property-based tests you wrote failed on an assertion. For each, decide from the library's documented
behavior whether the failure is expected (the property was too strict: for example, rendering drops control
characters by design) or reveals a bug (the library breaks a promise it makes).

- If expected, narrow the property or the strategy so it states what the library actually promises, and keep
  looking for real violations (for example, exclude control characters but keep backslashes and brackets).
- If it reveals a bug, keep the test exactly as it is.

Reply with the complete test file in one fenced block whose first line is `# file: {{path}}`. No explanations.

The failures:
```
{{failures}}
```

The current file:
```python
{{tests}}
```
