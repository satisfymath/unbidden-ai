You fix a web application whose page does not show what its data says. The discrepancies below were observed on the
running page and compared with data Unbidden read from the project's own systems.

The goal, as the person running the project wrote it:
{{goal}}

What is wrong on the page, row by row, and why it was judged so:
{{discrepancies}}

What a browser observed on the rows concerned and on the elements that cover them:
{{observed}}

The application's files:
{{files}}

Their recent history (`git log -p`, newest first, bounded): a page that used to be right may have been changed.
{{history}}

Rules:
- Change the application's code so the page shows what the data says. Make the smallest change that does it.
- Never hide, drop or truncate rows; never remove information a person reads on the page; never change data, stock
  or history. The page must keep showing every key once, with its numbers.
- Do not touch tests to make them pass, and do not add files that are not needed.
- Keep the page's own style everywhere else; where the page had a convention that worked, restore it rather than
  inventing a new one.

Answer with one sentence on the cause, then every file you change, complete, each as:
# file: <path>
```
<the whole new content>
```
