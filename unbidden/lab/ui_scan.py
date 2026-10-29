"""Runs inside the pinned Playwright container, never on the host: scan one page top to bottom and report what a
person would see on it, row by row. Written by Unbidden (not by a model, not from the repository).

Usage (in the container): python ui_scan.py <url> <wait_ms> <out_dir> [width height scale]
Writes <out_dir>/scan.json and one screenshot per scroll step (step-NN.png).

For every table row (`tr` or `[role=row]` with cells): its cells' text and page box, and its marks: the elements in
it with text of their own (a badge, a label, a number), with their computed style, page box and, wherever their box
is wholly in the viewport (at each step, and scrolled into view), the share of a 5 x 3 grid of their points where
the topmost element is the mark itself, with what covers the rest. Fixed and sticky elements are listed: they cover
whatever scrolls under them. Boxes are in page CSS pixels; a screenshot pixel is a CSS pixel times `scale`, offset by
the step's `scroll_y`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROWS = """() => {
  const rows = [...document.querySelectorAll('tr, [role=row]')].filter(r => r.querySelector('td, [role=cell]'));
  const box = e => {
    const b = e.getBoundingClientRect();
    return {x: b.x + scrollX, y: b.y + scrollY, w: b.width, h: b.height};
  };
  return rows.map((r, i) => {
    const marks = [...r.querySelectorAll('*')].filter(e => {
      const own = [...e.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim();
      return own.length > 0 && own.length <= 40;
    }).map((e, j) => {
      e.setAttribute('data-unbidden-mark', i + '-' + j);
      const s = getComputedStyle(e);
      return {id: i + '-' + j, tag: e.tagName.toLowerCase(), cls: e.className || '', text: e.innerText.trim(),
              background: s.backgroundColor, color: s.color, font_px: parseFloat(s.fontSize),
              font_weight: s.fontWeight, opacity: parseFloat(s.opacity), visibility: s.visibility,
              display: s.display, box: box(e)};
    });
    return {row: i, cells: [...r.querySelectorAll('td, [role=cell]')].map(c => c.innerText.trim()), box: box(r), marks};
  });
}"""

OVERLAYS = """() => [...document.querySelectorAll('body *')].filter(e => {
  const p = getComputedStyle(e).position; return p === 'fixed' || p === 'sticky';
}).map(e => { const b = e.getBoundingClientRect(), s = getComputedStyle(e);
  return {tag: e.tagName.toLowerCase(), cls: e.className || '', position: s.position, background: s.backgroundColor,
          text: e.innerText.trim().slice(0, 80), viewport_box: {x: b.x, y: b.y, w: b.width, h: b.height}}; })"""

HITS = """(ids) => ids.map(id => {
  const e = document.querySelector(`[data-unbidden-mark="${id}"]`);
  const b = e.getBoundingClientRect();
  if (!(b.top >= 0 && b.left >= 0 && b.bottom <= innerHeight && b.right <= innerWidth && b.width > 0)) return null;
  let own = 0, n = 0; const covers = {};
  for (let ix = 1; ix <= 5; ix++) for (let iy = 1; iy <= 3; iy++) {
    const top = document.elementFromPoint(b.left + b.width * ix / 6, b.top + b.height * iy / 4); n++;
    if (top && (top === e || e.contains(top))) own++;
    else if (top) {
      const k = top.tagName.toLowerCase() + (top.className ? '.' + top.className : '');
      covers[k] = (covers[k] || 0) + 1;
    }
  }
  return {id, visible: own / n, covered_by: covers, scroll_y: scrollY};
})"""


def main() -> None:
    from playwright.sync_api import sync_playwright  # pyright: ignore[reportMissingImports]

    url, wait_ms, out = sys.argv[1], int(sys.argv[2]), Path(sys.argv[3])
    width, height, scale = (int(sys.argv[4]), int(sys.argv[5]), float(sys.argv[6])) if len(sys.argv) > 6 else (
        1280, 800, 1.0)  # fmt: skip
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=scale)
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(wait_ms)
        rows = page.evaluate(ROWS)
        lines = page.evaluate("document.body.innerText.split('\\n').map(l => l.trim()).filter(l => l)")
        overlays = page.evaluate(OVERLAYS)
        ids = [m["id"] for r in rows for m in r["marks"]]
        total = page.evaluate("document.documentElement.scrollHeight")
        seen: dict[str, list[dict[str, Any]]] = {i: [] for i in ids}
        steps, y, n = [], 0, 0
        while True:
            page.evaluate(f"window.scrollTo(0, {y})")
            page.wait_for_timeout(120)
            actual = page.evaluate("scrollY")
            shot = f"step-{n:02d}.png"
            page.screenshot(path=str(out / shot))
            for hit in page.evaluate(HITS, ids):
                if hit:
                    seen[hit["id"]].append({**hit, "where": f"step {n}"})
            steps.append({"step": n, "scroll_y": actual, "screenshot": shot})
            if actual + height >= total or n >= 40:
                break
            y, n = actual + int(height * 0.9), n + 1
        for mark in ids:
            page.evaluate(
                f"document.querySelector('[data-unbidden-mark=\"{mark}\"]').scrollIntoView({{block: 'center'}})"
            )
            page.wait_for_timeout(40)
            (hit,) = page.evaluate(HITS, [mark])
            if hit:
                seen[mark].append({**hit, "where": "scrolled into view"})
        browser.close()
    for row in rows:
        for mark in row["marks"]:
            hits = seen[mark["id"]]
            mark["visible"] = max((h["visible"] for h in hits), default=None)
            worst = min(hits, key=lambda h: h["visible"], default=None)
            mark["covered_by"] = worst["covered_by"] if worst and worst["visible"] < 1 else {}
    (out / "scan.json").write_text(
        json.dumps(
            {
                "url": url,
                "viewport": [width, height],
                "scale": scale,
                "height": total,
                "steps": steps,
                "rows": rows,
                "overlays": overlays,
                "lines": lines,
            }
        )
    )


if __name__ == "__main__":
    main()
