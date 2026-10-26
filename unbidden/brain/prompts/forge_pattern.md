You write one Python regular expression that parses HTTP access lines of a service's log.

It must use these named groups: `method`, `path`, `status` (and optionally `level`). It must match the
access lines below and extract exactly the expected values listed under "Tests". Keep it simple and linear:
no backreferences, no nested quantifiers such as `(a+)+`, at most 300 characters. Prefer explicit character
classes (`[A-Z]+`, `\S+`, `\d{3}`) over `.*`.

Answer with JSON only, matching this schema: {{schema}}

{{feedback}}

Tests (line → expected fields):
{{tests}}

More lines from the same log:
{{lines}}
