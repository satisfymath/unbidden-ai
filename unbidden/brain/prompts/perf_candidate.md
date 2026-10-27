You improve the performance of a web application without changing its behavior.

Problem found by measuring the running system: {{problem}}

Make the database able to serve these queries without scanning the whole table: add the index that fits
the filter and the ordering the handlers below use. Do it the way this repository changes its schema: a new
Alembic migration in `{{migrations_dir}}` whose `down_revision` is `{{head}}`, with `upgrade` and `downgrade`,
and the same index declared on the model so models and migrations agree.

Reply with the complete content of every file you create or change, each in its own fenced block whose
first line is `# file: <path>`. Change nothing else. No explanations.

The newest migration, as an example of this repository's style (`{{head_file}}`):
```python
{{head_example}}
```

The model file (`{{models_file}}`):
```python
{{models}}
```

The handlers that read this table:
{{handlers}}
