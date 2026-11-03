You read HTTP handlers of a web application and say, for each one, which database tables it reads and which it
writes, directly or through the functions it calls that are shown with it.

Choose only from these table names: {{tables}}. If a handler touches none of them, answer with empty lists for it.
A write is an insert, update or delete. Answer with JSON only: one entry per handler, keyed by the handler's name
exactly as given, matching this schema: {{schema}}

{{handlers}}
