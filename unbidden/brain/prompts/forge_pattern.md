You write one Python regular expression that parses HTTP access lines of a service's log.

It must use these named groups: `method`, `path`, `status` (and optionally `level`). It must read ANY
three-digit status (`(?P<status>\d{3})`) and ANY uppercase HTTP method (`(?P<method>[A-Z]+)`), including
values that do not appear below: the lines you see are a sample, and the most important lines (errors) may be
missing from it. Never list the values you happen to see. It must match the
access lines below and extract exactly the expected values listed under "Tests". Keep it simple and linear:
no backreferences, no nested quantifiers such as `(a+)+`, at most 300 characters. Prefer explicit character
classes (`[A-Z]+`, `\S+`, `\d{3}`) over `.*`.

For illustration only, a general adapter for a different format (nginx "combined"), whose lines look like
`10.0.0.1 - - [10/Oct/2026:13:55:36 +0000] "GET /index.html HTTP/1.1" 200 2326 "-" "curl/8.0"`:
`"(?P<method>[A-Z]+) (?P<path>/\S*) HTTP/[\d.]+" (?P<status>\d{3})`
Anchor on the stable structure of a line, not on its values.

Answer with JSON only, matching this schema: {{schema}}

{{feedback}}

Tests (line → expected fields):
{{tests}}

More lines from the same log:
{{lines}}
