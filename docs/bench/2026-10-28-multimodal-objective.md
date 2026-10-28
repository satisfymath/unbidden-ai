# Stage 4, block 3: the multimodal objective, written before any implementation (2026-10-28)

Written after block 2 worked in development (RESULTS.md, stage 4; D-042) and before any multimodal code, fixture or
model call for this block. Changes after this point are recorded as amendments below, with their reason.

## The objective

**"Every short bin is visibly flagged on the picker's restock board."** A goal in the Depot lab's mandate. The board
is a page of the Depot app (`depotapp`, compose project `depotapp-staging`, 127.0.0.1:18095): one row per bin with
its stock and a red "SHORT" badge where the bin's last-7-day picks exceed what it can supply. The page is rendered
by the app from the picks database and the Depot API, the same sources the block 1 goal reads.

Why it needs more than one kind of evidence:
- **Data/API** say which bins *are* short (the existing reconciliation: picks from PostgreSQL, stock from Depot).
- **The rendered page** says which bins a person *sees* flagged. That is the claim the goal is about.
- **Code** (the app's template and stylesheet in its repository) says *why* the two differ, and is where the fix goes.
No single source decides the goal: the data cannot see the screen, the screen cannot say what is true, and neither
says what to change.

## Seeded defects (development set; the evaluation set is written separately and frozen before it runs)

| Id | What is wrong | Seen by data vs DOM | Seen by the browser/DOM | Seen only on screen |
|---|---|---|---|---|
| v1 | A sticky footer overlaps the last rows; their badges are in the DOM, visible to no one | no | no (the elements exist, are "visible") | yes |
| v2 | The template computes supply as `quantity + incoming`, ignoring `reserved`: wrong bins flagged | yes | the badge set is wrong | the badges look fine |
| v3 | The "short" class is styled with the "ok" colour: every badge is there, none is red | no | only by reading computed style | yes |
| h1 | Healthy control: the board is right | — | — | Unbidden must say nothing is wrong |

The truth for each case is computed by the lab from the database, the service and the seeded change, never by a
model.

## What "done" means

For each defect, Unbidden finds it from the goal alone (no hint naming the defect), localizes the cause in the app's
code, makes the change in a worktree of the lab repository, deploys it to the lab's staging (its own compose
project), and verifies it:
- **functionally**: the badges in the DOM are exactly the truly short bins;
- **visually**: every short bin's badge is visible and red on the rendered page, no other is.
The result is VERIFIED only if both hold. It is never pushed anywhere (a local lab repository; no PR, no merge).
For h1, the expected outcome is "nothing to do", with the evidence.

## Arms compared (question B of the evaluation, reported apart from question A)

1. **Browser/DOM only**: the existing model-free `browser_judge` plus DOM extraction (badge texts, classes, bounding
   boxes, `elementFromPoint` occlusion checks, computed colours).
2. **Vision**: the screenshot judged by a multimodal Meta model (the existing `visual_judge`, Spark or Wonder),
   with the data's short set as context.
3. **Vision + SAM**: SAM 3.1 segments the badges on the screenshot; their count, positions and colours are
   compared with the short set without a language model's reading of the image.
Each arm is measured on the same captures: defects detected, false alarms on h1, correct localization, verified
fixes, model calls, latency and cost per medium (screenshots and segmentations counted like tokens).

## Models: feasibility first, integration only on measured utility

Small feasibility tests, each a few cents at most, recorded with model, request, latency and cost:
- **Spark 1.3 and Wonder 1.0 with images**: can they read the board (which rows show a red badge)?
- **SAM 3.1** (`/v1/responses`, `/v1/files`): can it segment the badges with a text prompt, and how precisely?
- **Muse Image 1.0**: no role is expected in this objective (it generates or edits images; nothing here needs one).
  Tested once for availability; not integrated unless a use appears that measurably helps.
- **Muse Voice**: no role is expected (no audio in the lab). Tested once for availability; not integrated.

## Provenance, privacy and cost

Every screenshot is kept locally with its digest; any image that leaves goes through the egress gate (mandate
`models.screenshots_to_frontier: allow` only in this lab's mandate, whose data is synthetic) and the spend ledger,
as every remote call does. The capture runs in the pinned Playwright container on an internal network that reaches
only the app. The stage budget (D-042) applies; this block's share is capped at US$1 of development spend.

## Out of this block

Real user-facing applications, accessibility audits in general, any visual check outside the lab.

## Feasibility results (2026-10-28, after the objective above was written)

One call each on a synthetic board (`docs/bench/multimodal/board.png`: six rows, red badges on rows 2, 4 and 6, the
sixth 20 of its 30 px visible under a footer), through the spend ledger. Records: `docs/bench/multimodal/`.

| Model | Asked | Result | Latency | Cost |
|---|---|---|---|---|
| Spark 1.3 (image in chat) | colour and visibility of each row's badge | 6/6 rows right, row 6 "not fully visible" | 5.8 s | $0.0050 |
| Wonder 1.0 (image in chat) | same | 6/6 right, same | 5.2 s | $0.0161 |
| SAM 3.1, "red rectangle" | segment | exactly the 3 red badges, conf. 0.93–0.94; row 6's box ends at y=349, the visible part (its element spans 330–360) | 1.0 s | $0.0025 |
| SAM 3.1, "rectangle" | segment | every rectangle, badges and labels | 1.2 s | $0.0025 |
| Muse Image 1.0 | generate a table image | works (1 image, 1.7 MB) | 8.2 s | $0.01 |
| Muse Voice Transcribe 1.0 | a 2.4 s synthesized sentence, WAV 16 kHz then 24 kHz | wrong both times ("groovy British to the people happy for") | 2.0 s | <$0.001 |

Total $0.04. What this decides, before any implementation:
- **Vision (Spark) is the visual arm's default**: right on colour and on partial occlusion, at a third of Wonder's
  cost. Wonder is kept as the comparison only.
- **SAM is worth its arm.** It returns pixel geometry, not a description: a badge's segmented box compared with its
  DOM bounding box measures occlusion exactly (v1) and needs no language model's reading of the image. It is the
  arm most likely to make the visual verification deterministic.
- **Muse Image: not integrated.** It works, but nothing in this objective needs an image generated.
- **Muse Voice: not integrated.** No role in the objective, and it failed on the one synthetic clip (a synthesized
  voice may be atypical input; not investigated further, since it has no use here).

## Amendment 1 (2026-10-28, before any board code): the goal's contract

Version 1 above is kept as written. This amendment makes the contract precise and corrects two claims of version 1.
The objective stays: **every bin with a shortfall is correctly flagged on the restock board.**

**Corrections to version 1.**
- *An overlap is not visible only on screen.* The table above marks v1 "no" for the browser/DOM. That was wrong: the
  browser can see an element covered by another through geometry and hit-testing (`elementFromPoint` at sample
  points of the badge returns the covering element). v1 is detectable by method A; whether it is, is measured.
- *SAM is a prediction, not a measurement.* Geometry computed from a mask is deterministic, but the mask is SAM's
  prediction and can be wrong (missed, merged or misplaced regions). SAM's output is evaluated against the
  checker's truth, its errors counted, and it is never a source of acceptance.

**Shortfall and its source of truth.** A bin is short when its picks over the last 7 days exceed what it can supply:
`picks_7d > quantity - reserved + incoming`, shortfall = the difference. `picks_7d` is the sum of `picks.units` with
`picked_at > now() - 7 days` in the `depot` database; `quantity`, `reserved` and `incoming` are Depot's (its
service state). The harness computes it with its own SQL and its own read of Depot, written for the harness. It
never imports, calls or copies the board's code, so a defective board cannot judge itself.

**Flagged, on the rendered page** (a desktop viewport, 1280 px wide; the page scrolled through, see below). The bin's
row is the element holding the bin's id in its text. Its flag is an element inside that row:
- *bound to its row*: a descendant of the row in the DOM, and its box centred vertically within the row's box (both in
  page coordinates);
- *legible*: its text contains `SHORT`; font size at least 11 px; contrast between its text colour and its background
  at least 4.5:1 (WCAG AA); opacity above 0.5, not `visibility: hidden`, not `display: none`, at least 8 × 8 px;
- *an alert*: its background is red: hue within 20° of 0°, saturation at least 0.4, lightness 0.25 to 0.65 (computed
  style), and the screenshot's pixels at its box agree (their median colour satisfies the same rule);
- *visible*: at most **10 %** of its area occluded. Occlusion is measured by hit-testing a 5 × 3 grid of points of
  its box with the box in the viewport (scrolled into view, then also at its natural scroll positions): a point is
  covered when the topmost element there is neither the flag nor inside it.
A bin that is not short is flagged falsely when its row carries a visible red alert; a row carrying `OK` (or any
non-alert state) may be styled any way that is not a red alert.

**Long pages.** The checker and every observation method scroll the whole document in viewport steps with 10 %
overlap, keeping each step's screenshot and scroll offset, and map every box to page coordinates
(`page_y = viewport_y + scrollY`; screenshot pixels = CSS px × devicePixelRatio). Sticky and fixed elements are
occluders at every scroll position where they overlap. A row is checked at the scroll position where it is fully in
the viewport; a row that can never be fully shown (taller than the viewport) is checked in parts.

**False alarm.** In perception: reporting a discrepancy on a row that has none, or a defect on a healthy board. In
the cycle: changing a healthy board's code at all (the healthy control must end with no commit).

**VERIFIED** (by the harness's checker, model-free, after the change is deployed), all of:
1. every truly short bin is flagged on its own row (bound, legible, alert, visible) and no other bin is;
2. every bin appears exactly once and the numbers shown agree with the truth (rows are not hidden or dropped);
3. inventory and history are untouched: Depot's state for every bin and the `picks` table (row count and a checksum)
   are as before; the agent's grants allow reading them only;
4. the change is code in the app's repository, deployed to the lab's staging by its declared steps, and the app's
   own checks pass.
Model judgments (Spark, Wonder, SAM) are recorded beside the checker's result. They are never required nor
sufficient for VERIFIED; a disagreement between a model and the checker is kept and reported.

**What the agent may not do.** Satisfy the goal by hiding rows, removing information, changing data (restocking,
deleting picks) or touching the harness. It may change the board's code and deploy it to the lab's staging only.
