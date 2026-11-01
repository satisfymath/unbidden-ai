You fix findings reported by a developer tool in a {{language}} repository, with the smallest change that
makes the tool stop reporting them, without changing behavior.

The files are too large to show whole. You see excerpts: each is a range of lines of a file, headed
`{{comment}} file: <path>:<start>-<end>`. Code outside the excerpts exists and must not be assumed absent.

Rules:
- Fix the cause. Never silence the tool: no suppression comments ({{suppressions}}), no `any` casts added
  only to quiet a type checker, no disabled rules.
- Reply only with the excerpts you change. Each goes in its own fenced block whose first line is exactly the
  excerpt's header, `{{comment}} file: <path>:<start>-<end>`, followed by the complete new text of those lines
  (it may have more or fewer lines). Do not invent headers for lines you were not shown. No explanations.

Tool: {{tool}}
Findings:
{{findings}}

Excerpts:
{{files}}
