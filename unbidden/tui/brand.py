"""The mark, the wordmark, the tagline and the four verbs, rendered for a terminal. One accent colour, used sparingly:
the orbiting dot, the active verb, an engaged kill switch, a line that asks the person something."""

from __future__ import annotations

from rich.text import Text

MARK = "○˙"
WORDMARK = "UNBiDDEN"
TAGLINE = "Intelligence that doesn't wait for instructions."
VERBS: tuple[str, ...] = ("Discovering.", "Investigating.", "Experimenting.", "Proving.")
ACCENT = "#F5B700"

# The ring with the dot at the upper right, three lines high; the wordmark and the tagline beside it.
RING = ("     ·", "   ╭───╮", "   ╰───╯")


def banner(width: int, *, version: str | None = None, accent: str | None = ACCENT) -> Text:
    """The mark with the wordmark and tagline, or only the mark and wordmark when the terminal is narrow."""
    out = Text()
    dot = accent or "default"
    beside = [WORDMARK, TAGLINE if width >= 66 else ""]
    if version:
        beside[0] = f"{WORDMARK}  {version}"
    out.append(RING[0], style=f"bold {dot}")
    out.append("\n")
    out.append(RING[1], style="bold")
    out.append(f"   {beside[0]}", style="bold")
    out.append("\n")
    out.append(RING[2], style="bold")
    if beside[1]:
        out.append(f"   {beside[1]}", style="dim")
    return out


def verbs(active: str | None = None, *, accent: str | None = ACCENT) -> Text:
    """The four verbs as the brand writes them, one per line with a leading `>`; `active` is highlighted."""
    out = Text()
    for i, verb in enumerate(VERBS):
        style = f"bold {accent}" if accent and active and verb.startswith(active) else "bold"
        out.append("> ", style="dim")
        out.append(verb, style=style)
        if i < len(VERBS) - 1:
            out.append("\n")
    return out


def compact(width: int, *, version: str) -> str:
    """One line for a header: the mark and wordmark, the tagline when it fits, the version when little fits."""
    if width >= 80:
        return f"{MARK} {WORDMARK} · {TAGLINE}"
    if width >= 70:
        return f"{MARK} {WORDMARK}"
    return f"{MARK} {WORDMARK} {version}"
