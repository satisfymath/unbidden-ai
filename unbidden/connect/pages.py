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

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

MAX_PAGES = 50


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


def read_all(
    fetch: Callable[[dict[str, Any]], Any],
    parameters: list[dict[str, Any]],
    *,
    page_size: int | None = None,
    max_pages: int = MAX_PAGES,
) -> Read:
    """Follow the declared pagination to the end, or as far as it can be trusted. `fetch(params)` returns a body."""
    style, info = style_of(parameters)
    seen: dict[str, dict[str, Any]] = {}
    requests = 0

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

    if style == "none":
        data = fetch({})
        batch = records_of(data)
        take(batch)
        total = _int(data, "total", "count", "total_count")
        if total is not None:
            state = Completeness.COMPLETE if total == len(seen) else Completeness.INCOMPLETE
            return Read(list(seen.values()), state, f"{len(seen)} of a declared {total}", style, 1, total)
        return Read(
            list(seen.values()), Completeness.COMPLETE, "the document declares no pagination; one response", style, 1
        )
    if style == "offset":
        limit = min(page_size or info["limit"], info["limit"])
        offset, total = 0, None
        while requests < max_pages:
            data = fetch({"offset": offset, "limit": limit})
            requests += 1
            batch = records_of(data)
            total = _int(data, "total", "count", "total_count") if total is None else total
            new, duplicate = take(batch)
            if duplicate:
                return Read(
                    list(seen.values()),
                    Completeness.INCOMPLETE,
                    f"offset {offset} returned {duplicate} record(s) already read",
                    style,
                    requests,
                    total,
                )
            if not batch:
                break
            if new == 0:
                return Read(
                    list(seen.values()),
                    Completeness.INCOMPLETE,
                    f"no progress at offset {offset}",
                    style,
                    requests,
                    total,
                )
            offset += len(batch)
            if total is not None and offset >= total:
                if len(batch) == limit:
                    # The declared total is reached on a full page: one more page says whether it was the whole
                    # (a count that is the page's own length, not the collection's, looks exactly like this).
                    more = records_of(fetch({"offset": offset, "limit": limit}))
                    requests += 1
                    if more:
                        return Read(
                            list(seen.values()),
                            Completeness.INCOMPLETE,
                            f"the declared total {total} is contradicted: offset {offset} returned {len(more)} more",
                            style,
                            requests,
                            total,
                        )
                break
            if total is None and len(batch) < limit:
                break
        else:
            return Read(
                list(seen.values()),
                Completeness.INCOMPLETE,
                f"stopped after {max_pages} requests",
                style,
                requests,
                total,
            )
        if total is None:
            return Read(
                list(seen.values()), Completeness.UNKNOWN, "no total declared; ended on a short batch", style, requests
            )
        state = Completeness.COMPLETE if len(seen) == total else Completeness.INCOMPLETE
        return Read(list(seen.values()), state, f"{len(seen)} distinct of a declared {total}", style, requests, total)
    if style == "cursor":
        token: str | None = None
        used: set[str] = set()
        while requests < max_pages:
            data = fetch({info["param"]: token} if token else {})
            requests += 1
            new, duplicate = take(records_of(data))
            if duplicate:
                return Read(list(seen.values()), Completeness.INCOMPLETE, "a page repeated records", style, requests)
            token = _token(data)
            if token is None:
                return Read(
                    list(seen.values()), Completeness.COMPLETE, "the last page handed back no cursor", style, requests
                )
            if token in used:
                return Read(list(seen.values()), Completeness.INCOMPLETE, "the cursor came back again", style, requests)
            used.add(token)
        return Read(
            list(seen.values()), Completeness.INCOMPLETE, f"stopped after {max_pages} requests", style, requests
        )
    # page
    pages: int | None = None
    total = None
    number = 1
    while requests < max_pages:
        data = fetch({info["param"]: number})
        requests += 1
        batch = records_of(data)
        pages = _int(data, "pages", "total_pages", "page_count") if pages is None else pages
        total = _int(data, "total", "count", "total_count") if total is None else total
        new, duplicate = take(batch)
        if duplicate:
            return Read(
                list(seen.values()), Completeness.INCOMPLETE, f"page {number} repeated records", style, requests, total
            )
        if not batch or (pages is not None and number >= pages):
            break
        number += 1
    else:
        return Read(
            list(seen.values()), Completeness.INCOMPLETE, f"stopped after {max_pages} pages", style, requests, total
        )
    if total is not None and total != len(seen):
        return Read(
            list(seen.values()),
            Completeness.INCOMPLETE,
            f"{len(seen)} distinct of a declared {total}",
            style,
            requests,
            total,
        )
    if pages is None and total is None:
        return Read(
            list(seen.values()), Completeness.UNKNOWN, "ended on an empty page; no count declared", style, requests
        )
    return Read(
        list(seen.values()),
        Completeness.COMPLETE,
        f"{len(seen)} records over {requests} page(s)",
        style,
        requests,
        total,
    )


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
