# Stage 9 demo: a proactive cycle on Conduit, with its independent check

Conduit is a development application (used to build Unbidden since stage 7): this is a demonstration of the whole cycle and of how its evidence is checked, not evaluation evidence.

## What the harness prepared (not Unbidden)

- The repository at `029eb7781c60`, its staging with synthetic data (2000 users, 20000 articles, 300000 comments, 20000 favorites), a read-only database role, a fresh API token, a new workspace with a proactive mandate (no goal), Meta's API only, envelope `demo`.
- One declared answer, if asked: adding a package registry Unbidden names. Given: [['deb.debian.org']].

## What Unbidden did

- **Reproduced the project before anything else:** its own checks at the base, passed (90 tests, 0 failed), `./scripts/test`.
- **Found, without a ticket:** 6 opportunities.
  - L4 commentaries.article_id is a foreign key without an index, joined on by 1 endpoint(s): measured in 8 alternating sessions, medians 24.1 -> 18.3 ms; index scans per candidate session [35]; **improved**
  - L4 favorites.article_id is a foreign key without an index, checked when 1 endpoint(s) delete a articles row: measured in 8 alternating sessions, medians 9.6 -> 1.7 ms; index scans per candidate session [46]; **improved**
  - L1 GET /api/articles reports articles[].favoritesCount, articlesCount: unverified against the stored data: inconclusive: no difference among the 1000 keys read, but the set's completeness is unknown (no total confirmed (articlesCount is 0 on the empty page past the end: not compared); 20000 distinct records, an empty pa
  - L1 GET /api/articles/feed reports articles[].favoritesCount, articlesCount: unverified against the stored data: inconclusive: no difference among the 0 keys read, but the set's completeness is unknown (no total confirmed (no count beside the records); 0 distinct records, an empty page at offset 0; the read-only query returne
  - L1 commentaries.author_id is a foreign key without an index, filtered on by 2 endpoint(s): cannot measure: no workload ran at the base after 5 attempts (workload attempt 5 failed: E   AssertionError: warm-up returned HTTP 204)
  - L1 articles.author_id is a foreign key without an index, filtered on by 2 endpoint(s): measured in 8 alternating sessions, medians 30.5 -> 30.6 ms; index scans per candidate session [48]; **no change of 20% or more either way**
- **Proposed:** 2 change(s), each a local branch with its migration: unbidden/commentaries-article-id-is-a-foreign-key-ad48b7, unbidden/favorites-article-id-is-a-foreign-key-wi-f64204; nothing pushed, merged or deployed.
- **Spent:** US$0.53 on the ledger (46 model calls, muse-spark-1.3; US$0.53 in the workspace's own records); 47 minutes.

## Independent check (not Unbidden: the endpoints' own SQL on the lab data, rolled back)

```
commentaries.article_id / GET comments: median 8.27 ms -> 0.06 ms (n=15)
favorites.article_id / DELETE article: median 7.74 ms -> 7.16 ms (n=15)
favorites.article_id / DELETE article, comments indexed on both sides: median 0.61 ms -> 0.20 ms (n=15)
commentaries.author_id / DELETE comment: median 0.04 ms -> 0.03 ms (n=15)
```
