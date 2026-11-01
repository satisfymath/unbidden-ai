You choose the HTTP request that measures one database relation of a running web application. You do not write
code: your answer is data, and a fixed driver sends it.

The relation: the table `{{table}}` is read by its column `{{column}}`{{parent_note}}. The database holds
{{rows}} rows of `{{table}}` spread evenly over {{owners}} rows of `{{parent}}`, written by Unbidden's seeder.

The endpoints that use this relation, as the application serves them:
{{endpoints}}

Their handlers' code:
{{handlers}}

The data models:
```python
{{models}}
```

Answer with one JSON object:
- `method` and `path`: one of the endpoints above, with the path exactly as served (its prefix included). A path
  parameter is written `{value}`.
- `query`: query parameters as an object (strings); the one that selects by `{{column}}` holds `{value}`. Use the
  parameter names the handler declares. `{}` when none.
- `body`: a JSON body, or null. Only for an endpoint that reads with a body.
- `values_sql`: one SELECT over the seeded tables that returns, one per row, the values `{value}` takes, in a
  fixed order (an ORDER BY), at least {{calls}} rows; for example the ids of `{{parent}}` that own rows. Each call
  uses the next value. For an endpoint that removes what it acts on, the values must be distinct.
- `setup_sql`: "" or UPDATE statements (separated by `;`) that give the seeded rows values the endpoint needs.
  The seeder fills only required columns and references; every optional column is NULL. If the endpoint refuses
  rows without some optional value (a weight, a price, a state), set it here, deterministically (no random()).
  Only UPDATE; it runs once after seeding, and is recorded as data adapted by you.
- `why`: one sentence: how this request makes the database read `{{table}}` by `{{column}}`.

The request must make the database read `{{table}}` by `{{column}}` on every call, and return data: the engine's
own statistics are checked after the calls, and a request that does not is refused.

{{feedback}}
