"""Reading a whole collection from an API, and saying how sure that it is whole.

The style comes from the operation's own document: `page` (a page number, maybe a page count), `offset` (offset
and limit, maybe a total), `cursor` (a token the response hands back). `read_all` follows it and reports:
- `complete` only when the end was observed and nothing contradicts it (the declared total matches the distinct
  records read; the last page or a short batch or an empty cursor was reached);
- `incomplete` when it can name what is missing or wrong: a page limit reached, a page that repeats records, no
  progress, fewer distinct records than the declared total;
- `unknown` when the document declares no way to know (no pagination and a full-looking batch, no total).
A partial read is never presented as the set: callers that need the whole set block or narrow on anything but
`complete`. The oracle does not trust this reader alone (`cross_check`): it re-reads with another page size and
compares the records, so a service that skips a page cannot be hidden by the reader's own assumptions.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

# The bound is on what is read, not on how many requests that takes: 50 requests stopped Conduit's 20,000
# articles at 5,000 (stage 8). The request cap stays as a guard against a service that hands back tiny pages.
MAX_RECORDS = 100_000
MAX_PAGES = 2_000


class Completeness(StrEnum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    UNKNOWN = "unknown"


@dataclass
class Read:
    records: list[dict[str, Any]]
    completeness: Completeness
    why: str
    style: str
    requests: int = 0
    declared_total: int | None = None
    notes: list[str] = field(default_factory=list[str])

    def summary(self) -> dict[str, Any]:
        return {
            "records": len(self.records),
            "completeness": self.completeness.value,
            "why": self.why,
            "style": self.style,
            "requests": self.requests,
            "declared_total": self.declared_total,
        }


def records_of(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list) and (not value or isinstance(value[0], dict)):
                return [x for x in value if isinstance(x, dict)]
    return []


def _int(data: Any, *names: str) -> int | None:
    if isinstance(data, dict):
        for name in names:
            value = data.get(name)
            if isinstance(value, int) and not isinstance(value, bool):
                return value
    return None


def _token(data: Any) -> str | None:
    if isinstance(data, dict):
        for name in ("next_cursor", "next", "cursor", "next_page_token", "nextPageToken"):
            value = data.get(name)
            if isinstance(value, str) and value:
                return value
    return None


def style_of(parameters: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    """The pagination the document declares, and the parameters it uses."""
    by_name = {p["name"]: p for p in parameters if p.get("in") == "query"}
    if "offset" in by_name and "limit" in by_name:
        maximum = ((by_name["limit"].get("schema") or {}).get("maximum")) or 100
        return "offset", {"limit": int(maximum)}
    for name in ("cursor", "after", "page_token", "pageToken"):
        if name in by_name:
            return "cursor", {"param": name}
    for name in ("page", "page_number", "pageNumber"):
        if name in by_name:
            return "page", {"param": name}
    return "none", {}


def identity(record: dict[str, Any]) -> str:
    """What makes a record distinct: its id-like fields, else all of it."""
    keys = [k for k in record if k == "id" or k.endswith("_id") or k in ("sku", "key", "code", "name", "region")]
    import json

    return json.dumps({k: record[k] for k in keys} if keys else record, sort_keys=True, default=str)


class Counts:
    """Every integer beside the records, page by page, judged by how it behaves, never by its name (stage 9).

    On Conduit, `articlesCount` is the page's own length (2 for `limit=2` over 20,000 articles); a reader that took
    any `count` for the collection's size would call a partial read complete. A field is read as the collection's
    total only when it is the same on every page and equals the distinct records read once the end was observed; as
    the page's length when it equals each page's record count; an echo of a parameter we sent is not a count. A name
    or description that says "total" or "count" is the document's claim: a field so named that contradicts what was
    read makes the read incomplete, one that changes between pages says the collection changed during the read; the
    name alone never makes a read complete."""

    DOCUMENTED = re.compile(r"(?i)total|count")
    PAGE_COUNT = re.compile(r"(?i)^(pages|total_?pages|page_?count|num_?pages)$")

    def __init__(self) -> None:
        self.pages: list[tuple[int, dict[str, int], set[int]]] = []

    def add(self, data: Any, records: int, sent: dict[str, Any] | None = None) -> None:
        fields = (
            {k: v for k, v in data.items() if isinstance(v, int) and not isinstance(v, bool)}
            if isinstance(data, dict)
            else {}
        )
        echoes = {v for v in (sent or {}).values() if isinstance(v, int)}
        self.pages.append((records, fields, echoes))

    def judge(self, distinct: int, pages_read: int) -> tuple[str | None, int | None, list[str]]:
        """("confirmed" | "contradicted" | "changed" | None, the total, notes)."""
        notes: list[str] = []
        confirmed: int | None = None
        contradicted: str | None = None
        changed: str | None = None
        names = sorted({name for _, fields, _ in self.pages for name in fields})
        # A count on an empty page past the end says nothing of the set (LNbits answers `total: 0` there, 5,000 on
        # every page with records, stage 9): compared only where records were served, its difference noted.
        served = [p for p in self.pages if p[0] > 0] or self.pages
        for name in names:
            past = {fields[name] for n, fields, _ in self.pages if n == 0 and name in fields}
            rows = [(n, fields[name], echoes) for n, fields, echoes in served if name in fields]
            if not rows:
                continue
            if past - {fields[name] for _, fields, _ in served if name in fields}:
                notes.append(
                    f"{name} is {', '.join(map(str, sorted(past)))} on the empty page past the end: not compared"
                )
            values = [v for _, v, _ in rows]
            documented = bool(self.DOCUMENTED.search(name))
            if all(v in echoes for _, v, echoes in rows):
                continue  # what we asked for, sent back
            if all(v == n for n, v, _ in rows) and (len({n for n, _, _ in rows}) > 1 or distinct > values[0]):
                notes.append(f"{name} equals each page's record count: the page's length, not a total")
                continue
            if len(set(values)) == 1:
                value = values[0]
                if value == distinct:
                    confirmed = value
                    notes.append(f"{name} = {value} on every page, equal to the distinct records read")
                elif value == pages_read and self.PAGE_COUNT.search(name):
                    confirmed = distinct  # the declared number of pages, the same on every page, and all read
                    notes.append(f"{name} = {value} on every page, and {value} pages were read")
                elif value == pages_read and not documented:
                    notes.append(f"{name} = {value}, the number of pages read")
                elif documented:
                    contradicted = f"{name} declares {value}; {distinct} distinct records were read"
                else:
                    notes.append(f"{name} = {value} on every page: not explained by the read")
            elif documented:
                changed = f"{name} changed during the read ({min(values)} to {max(values)}): the collection changed"
        if contradicted:
            return "contradicted", None, [contradicted, *notes]
        if changed:
            return "changed", None, [changed, *notes]
        if confirmed is not None:
            return "confirmed", confirmed, notes
        return None, None, notes


def _end(seen: dict[str, dict[str, Any]], counts: Counts, style: str, requests: int, how: str) -> Read:
    """The verdict once the end was observed (`how`): complete only with a total the read confirms."""
    verdict, total, notes = counts.judge(len(seen), requests)
    records = list(seen.values())
    if verdict == "confirmed":
        return Read(records, Completeness.COMPLETE, f"{len(seen)} distinct records, {how}; " + "; ".join(notes),
                    style, requests, total, notes)  # fmt: skip
    if verdict == "contradicted":
        return Read(records, Completeness.INCOMPLETE, f"{notes[0]} ({how})", style, requests, None, notes)
    if verdict == "changed":
        return Read(records, Completeness.UNKNOWN, f"{notes[0]} ({how})", style, requests, None, notes)
    detail = "; ".join(notes) if notes else "no count beside the records"
    return Read(records, Completeness.UNKNOWN, f"no total confirmed ({detail}); {len(seen)} distinct records, {how}",
                style, requests, None, notes)  # fmt: skip


def read_all(
    fetch: Callable[[dict[str, Any]], Any],
    parameters: list[dict[str, Any]],
    *,
    page_size: int | None = None,
    max_pages: int = MAX_PAGES,
    max_records: int = MAX_RECORDS,
) -> Read:
    """Follow the declared pagination until its end is observed, or as far as it can be trusted. `fetch(params)`
    returns a body. Completeness comes from what the pages show (`Counts`), not from what a field is called."""
    style, info = style_of(parameters)
    seen: dict[str, dict[str, Any]] = {}
    counts = Counts()
    requests = 0

    def bound(requests: int) -> str:
        return (
            f"stopped at the read bound: {len(seen)} records in {requests} requests (bounds {max_records}, {max_pages})"
        )

    def take(batch: list[dict[str, Any]]) -> tuple[int, int]:
        new = duplicate = 0
        for record in batch:
            key = identity(record)
            if key in seen:
                duplicate += 1
            else:
                seen[key] = record
                new += 1
        return new, duplicate

    def stop(why: str) -> Read:
        return Read(list(seen.values()), Completeness.INCOMPLETE, why, style, requests)

    if style == "none":
        data = fetch({})
        batch = records_of(data)
        take(batch)
        counts.add(data, len(batch))
        requests = 1
        read = _end(seen, counts, style, 1, "one response, no pagination declared")
        if read.completeness is Completeness.UNKNOWN and "changed" not in read.why:
            # One response with nothing to page through: what it holds is the collection, unless a count disagrees.
            read.completeness, read.why = Completeness.COMPLETE, "the document declares no pagination; one response"
        return read
    if style == "offset":
        limit = min(page_size or info["limit"], info["limit"])
        offset = 0
        while requests < max_pages and len(seen) < max_records:
            sent = {"offset": offset, "limit": limit}
            data = fetch(sent)
            requests += 1
            batch = records_of(data)
            counts.add(data, len(batch), sent)
            new, duplicate = take(batch)
            if duplicate:
                return stop(f"offset {offset} returned {duplicate} record(s) already read")
            if not batch:
                return _end(seen, counts, style, requests, f"an empty page at offset {offset}")
            if new == 0:
                return stop(f"no progress at offset {offset}")
            offset += len(batch)
            if len(batch) < limit:
                return _end(seen, counts, style, requests, f"a short page ({len(batch)} < {limit}) at the end")
        return stop(bound(requests))
    if style == "cursor":
        token: str | None = None
        used: set[str] = set()
        while requests < max_pages and len(seen) < max_records:
            data = fetch({info["param"]: token} if token else {})
            requests += 1
            batch = records_of(data)
            counts.add(data, len(batch))
            new, duplicate = take(batch)
            if duplicate:
                return stop("a page repeated records")
            token = _token(data)
            if token is None:
                read = _end(seen, counts, style, requests, "the last page handed back no cursor")
                if read.completeness is Completeness.UNKNOWN and "changed" not in read.why:
                    # The cursor protocol says where it ends: no token is the service's own statement of the end.
                    read.completeness = Completeness.COMPLETE
                    read.why = f"the last page handed back no cursor; {len(seen)} records"
                return read
            if token in used:
                return stop("the cursor came back again")
            used.add(token)
        return stop(bound(requests))
    # page
    number = 1
    sizes: set[int] = set()
    while requests < max_pages and len(seen) < max_records:
        sent = {info["param"]: number}
        data = fetch(sent)
        requests += 1
        batch = records_of(data)
        counts.add(data, len(batch), sent)
        new, duplicate = take(batch)
        if duplicate:
            return stop(f"page {number} repeated records")
        if not batch:
            return _end(seen, counts, style, requests, f"an empty page ({number})")
        if new == 0:
            return stop(f"no progress at page {number}")
        if sizes and len(batch) < max(sizes):
            return _end(seen, counts, style, requests, f"a short page ({len(batch)}) at page {number}")
        declared = next((v for k, v in (data.items() if isinstance(data, dict) else [])
                         if isinstance(v, int) and Counts.PAGE_COUNT.search(k)), None)  # fmt: skip
        if declared is not None and number >= declared:
            # The page count the service declares is reached: asking past it is an error on many services.
            return _end(seen, counts, style, requests, f"the declared last page ({declared}) reached")
        sizes.add(len(batch))
        number += 1
    return stop(bound(requests))


def cross_check(
    first: Read, fetch: Callable[[dict[str, Any]], Any], parameters: list[dict[str, Any]]
) -> tuple[bool, str]:
    """The oracle's independent look: the same collection read again with another page size must hold the same
    records. A service that skips or reorders a page cannot agree with itself across page sizes."""
    style, info = style_of(parameters)
    if style != "offset":
        return True, "no other page size to read with"
    smaller = max(1, min(info["limit"], max(1, len(first.records) // 3 or 1)))
    if smaller == info["limit"]:
        smaller = max(1, info["limit"] - 1)
    second = read_all(fetch, parameters, page_size=smaller)
    a, b = {identity(r) for r in first.records}, {identity(r) for r in second.records}
    if a == b and second.completeness is first.completeness:
        return True, f"the same {len(a)} records with page size {smaller}"
    return False, (
        f"page size {info['limit']}: {len(a)} records ({first.completeness.value}); page size {smaller}: "
        f"{len(b)} ({second.completeness.value}); {len(a ^ b)} differ"
    )
