You read one HTTP handler of a web application and say which database tables it reads and which it writes,
directly or through the functions it calls that are shown below.

Choose only from these table names: {{tables}}. If the handler touches none of them, answer with empty lists.
A write is an insert, update or delete. Answer with JSON only, matching this schema: {{schema}}

Handler `{{endpoint}}` in `{{file}}`:
```
{{code}}
```
