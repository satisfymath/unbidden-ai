"""What the restock board shows for each bin: its supply, its recent picks, and whether it is short."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Row:
    bin: str
    zone: str
    supply: int
    picks: int
    shortfall: int

    @property
    def short(self) -> bool:
        return self.shortfall > 0


def supply(stock: dict[str, int]) -> int:
    """Units a bin can still hand out: what is on hand and not promised, plus what is on its way."""
    return stock["quantity"] - stock["reserved"] + stock["incoming"]


def rows(bins: list[dict[str, int | str]], picks: dict[str, int]) -> list[Row]:
    out = []
    for b in bins:
        name = str(b["bin"])
        can = supply({k: int(b[k]) for k in ("quantity", "reserved", "incoming")})
        picked = picks.get(name, 0)
        out.append(Row(name, zone_of(name), can, picked, max(0, picked - can)))
    return sorted(out, key=lambda r: r.bin)


def zone_of(name: str) -> str:
    return "A" if int(name[1:]) <= 6 else "B"
