You write a reader for a text metrics endpoint of a running service, as two Python regular expressions.

1. `line`: matches one whole line (it is applied with fullmatch to the stripped line) and has exactly two named
   groups, `name` (the metric's full name) and `value` (its number, integer or decimal).
2. `entity` (or null): applied with fullmatch to a `name`, with exactly two named groups: `entity`, the thing
   measured (an upstream, a cluster, a pool, a queue), and `metric`, what is measured about it. Use null when
   names carry no such part.

Read every line whose value is ONE number at its end. Lines of another shape (histograms such as
`name: P0(0,0) P50(1,2)`, lists) may be left unread: do not bend the patterns to fit them.

Read ANY value: the numbers below are a sample and will change. Never list values or names you happen to see;
anchor on the structure of a line. Keep both patterns simple: no backreferences, no nested quantifiers such as
`(a+)+`, at most 300 characters each.

For illustration only, a reader for a different format whose lines look like `pool.web.active_connections = 12`:

```
LINE: (?P<name>[a-z0-9_.]+) = (?P<value>\d+(\.\d+)?)
ENTITY: pool\.(?P<entity>[a-z0-9_-]+)\.(?P<metric>[a-z0-9_]+)
```

Answer with exactly one such fenced block and nothing else: a `LINE:` line and an `ENTITY:` line (write
`ENTITY: none` when names carry no entity). The patterns are raw text, not JSON: write each backslash once.

{{feedback}}

Lines from the endpoint ({{source}}):
{{lines}}
