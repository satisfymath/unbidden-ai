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
