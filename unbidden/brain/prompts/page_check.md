You check whether a web page shows what the data says it should. You do not compute the data: Unbidden read it from
the project's systems and computed, for every key, the value the goal is about. You compare that with what the page
shows a person, row by row.

The goal, as the person running the project wrote it:
{{goal}}

What the data says, one line per key (`key: fields; value; whether the goal says it must be flagged`):
{{expected}}

What a browser observed on the page ({{how}}). The page was scrolled top to bottom in steps. For each table row:
its cells, then its marks (elements with text of their own): text, background and text colour (computed), font
size, and `visible`, the best share of the mark not covered by another element at any scroll position, with what
covers it when it is covered. Fixed or sticky elements cover whatever scrolls under them.
{{observed}}
{{extra}}

A row is flagged only if a person scanning the page would notice it among the others. Check each of these for
every row that must be flagged, from the observations:
- its flag says so in its text, on that row's own line of the page;
- a person can read it: legible size, enough contrast between its text and its background, not transparent;
- a person can see it: mostly not covered (`visible` near 1 somewhere on the page) — a flag covered by another
  element is not seen;
- it stands out as an alert: it does not look like the rows that are not flagged. Compare its background and colour
  with the marks of rows that must not be flagged; if they look alike, a person would not notice it.
And for every row that must not be flagged: nothing on it looks like an alert.

For every key whose row the page shows wrongly, say what is wrong:
- `not_flagged`: the goal says it must be flagged and a person would not see it flagged on its own row (any check
  above fails);
- `flagged_wrongly`: a person would see it flagged and it must not be;
- `wrong_value`: a number shown differs from the data;
- `missing_row`: the key appears on no row, or on more than one.
Report only what the observations show. If the page is right, report nothing. Then say, in one sentence, what in
the page's code most likely causes what you found (or "none").

Answer with JSON only, matching this schema: {{schema}}
