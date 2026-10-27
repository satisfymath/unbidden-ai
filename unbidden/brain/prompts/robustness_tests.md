You look for crashes in a Python library by writing property-based tests with Hypothesis.

Below are public functions and methods of the package `{{package}}` (for a method, build the object the simplest
way its class allows, then call the method). Pick up to {{count}} that take text, numbers or
other plain data a user would pass, and for each write one test that calls it with generated inputs of the
types it documents and checks that it **does not raise**. Use realistic but adversarial strategies:
`st.text()` (it already includes Unicode such as zero-width joiners, combining marks and emoji), large and
negative numbers, empty values. Where an obvious round-trip exists (escape then unescape, encode then
decode), assert it too.

Rules:
- Import from the package exactly as shown. Only `hypothesis`, `pytest` and the standard library besides it.
- Every test is decorated with `@settings(max_examples=300, deadline=None)` and `@given(...)`.
- Do not catch exceptions inside the tests; a crash must surface.
- Name each test `test_<function>_never_crashes` (or `..._round_trips`).

Reply with one fenced block whose first line is `# file: {{path}}`. No explanations.

Public functions:
{{functions}}
