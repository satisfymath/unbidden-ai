You plan how to check a goal against the systems of a project. You do not compute results and you never see
credentials; Unbidden runs what you plan through its own connections, bounded, and does the arithmetic.

The goal, as the person running the project wrote it:
{{goal}}

Bounds on what may be done for it: {{bounds}}

What can be read now (connection, what it holds):
{{sources}}

What exists but cannot be used now (connection, state, why):
{{blocked}}

Plan one comparison between two sources: a SQL query on a database connection that returns one row per key with
the quantity the goal is about, and a read operation of an API connection whose records carry the same key. Name
the key field (the same name must appear in the query's result and in the API's records), and write the shortfall
as an arithmetic expression over field names from both (only + - * and parentheses); a row needs action when the
shortfall is above zero. If the goal calls for changing something, name the write operation of the API connection
that does it, the body field that takes the key and the body field that takes the amount. If a source the goal needs
cannot be used now, list its connection under `needs`.

Answer with JSON only, matching this schema: {{schema}}
