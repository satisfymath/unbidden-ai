You write a reader for a text metrics endpoint of a running service, as two Python regular expressions.

1. `line`: matches one whole line (it is applied with fullmatch to the stripped line) and has exactly two named
   groups, `name` (the metric's full name) and `value` (its number, integer or decimal).
2. `entity` (or null): applied with fullmatch to a `name`, with exactly two named groups: `entity`, the thing
   measured (an upstream, a cluster, a pool, a queue), and `metric`, what is measured about it. Use null when
   names carry no such part.

Read ANY value: the numbers below are a sample and will change. Never list values or names you happen to see;
anchor on the structure of a line. Keep both patterns simple: no backreferences, no nested quantifiers such as
`(a+)+`, at most 300 characters each.

For illustration only, a reader for a different format whose lines look like `pool.web.active_connections = 12`:
{"line": "(?P<name>[a-z0-9_.]+) = (?P<value>\\d+(\\.\\d+)?)", "entity": "pool\\.(?P<entity>[a-z0-9_-]+)\\.(?P<metric>[a-z0-9_]+)"}

Answer with JSON only, matching this schema: {{schema}}

{{feedback}}

Lines from the endpoint ({{source}}):
{{lines}}
