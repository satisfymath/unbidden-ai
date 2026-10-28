"""The harness's page check, run inside a Playwright container (written for the harness; never the agent's code).

    python board_check_page.py <url> <out_dir>

Scrolls the whole page in viewport steps (10 % overlap) and writes <out_dir>/check.json and one screenshot per
step. For each table row (`tr` or `[role=row]`): its cells' text and page box; for each element in it whose own
text says SHORT or OK (a state): its text, computed style, page box, and at every step where its box is wholly in
the viewport, and once scrolled into view (centred), the share of a 5 x 3 grid of its points where the topmost
element is it or inside it, plus the median colour of its pixels in that screenshot. Pixels are read with Pillow.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

WIDTH, HEIGHT = 1280, 800

ROWS = """() => {
  const rows = [...document.querySelectorAll('tr, [role=row]')].filter(r => r.querySelector('td, [role=cell]'));
  return rows.map((r, i) => {
    r.setAttribute('data-check-row', String(i));
    const box = r.getBoundingClientRect();
    const cells = [...r.querySelectorAll('td, [role=cell]')].map(c => c.innerText.trim());
    const states = [...r.querySelectorAll('*')].filter(e => {
      const own = [...e.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim();
      return /\\b(SHORT|OK)\\b/.test(own);
    }).map((e, j) => {
      e.setAttribute('data-check-state', i + '-' + j);
      const s = getComputedStyle(e), b = e.getBoundingClientRect();
      return {id: i + '-' + j, text: e.innerText.trim(), background: s.backgroundColor, color: s.color,
              font_px: parseFloat(s.fontSize), opacity: parseFloat(s.opacity), visibility: s.visibility,
              display: s.display, box: {x: b.x + scrollX, y: b.y + scrollY, w: b.width, h: b.height}};
    });
    return {index: i, cells, box: {x: box.x + scrollX, y: box.y + scrollY, w: box.width, h: box.height}, states};
  });
}"""

HITS = """(ids) => ids.map(id => {
  const e = document.querySelector(`[data-check-state="${id}"]`);
  const b = e.getBoundingClientRect();
  const inside = b.top >= 0 && b.left >= 0 && b.bottom <= innerHeight && b.right <= innerWidth && b.width > 0;
  if (!inside) return {id, inside: false};
  let hit = 0, n = 0;
  for (let ix = 1; ix <= 5; ix++) for (let iy = 1; iy <= 3; iy++) {
    const top = document.elementFromPoint(b.left + b.width * ix / 6, b.top + b.height * iy / 4);
    n++; if (top && (top === e || e.contains(top))) hit++;
  }
  return {id, inside: true, visible: hit / n, box: {x: b.left, y: b.top, w: b.width, h: b.height}};
})"""


def median_rgb(png: Path, box: dict[str, float], scale: float) -> list[int] | None:
    from PIL import Image  # pyright: ignore[reportMissingImports]

    image = Image.open(png).convert("RGB")
    left, top = int(box["x"] * scale) + 2, int(box["y"] * scale) + 2
    right, bottom = int((box["x"] + box["w"]) * scale) - 2, int((box["y"] + box["h"]) * scale) - 2
    if right <= left or bottom <= top:
        return None
    pixels = list(image.crop((left, top, right, bottom)).getdata())
    return [int(statistics.median(p[c] for p in pixels)) for c in range(3)]


def main() -> None:
    from playwright.sync_api import sync_playwright  # pyright: ignore[reportMissingImports]

    url, out = sys.argv[1], Path(sys.argv[2])
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1)
        page.goto(url, wait_until="networkidle", timeout=30000)
        rows = page.evaluate(ROWS)
        ids = [s["id"] for r in rows for s in r["states"]]
        total = page.evaluate("document.documentElement.scrollHeight")
        scale = page.evaluate("devicePixelRatio")
        seen: dict[str, list[dict[str, object]]] = {i: [] for i in ids}
        steps, y, n = [], 0, 0
        while True:
            page.evaluate(f"window.scrollTo(0, {y})")
            page.wait_for_timeout(150)
            actual = page.evaluate("scrollY")
            shot = out / f"step-{n:02d}.png"
            page.screenshot(path=str(shot))
            for hit in page.evaluate(HITS, ids):
                if hit["inside"]:
                    hit["rgb"] = median_rgb(shot, hit["box"], scale)
                    hit["scroll_y"], hit["step"] = actual, n
                    seen[hit["id"]].append(hit)
            steps.append({"step": n, "scroll_y": actual, "screenshot": shot.name})
            if actual + HEIGHT >= total or n > 60:
                break
            y, n = actual + int(HEIGHT * 0.9), n + 1
        # Then each state scrolled into view (centred), as a person would scroll to the row they look for.
        for k, sid in enumerate(ids):
            page.evaluate(f"document.querySelector('[data-check-state=\"{sid}\"]').scrollIntoView({{block: 'center'}})")
            page.wait_for_timeout(60)
            actual = page.evaluate("scrollY")
            shot = out / f"centred-{k:02d}.png"
            page.screenshot(path=str(shot))
            (hit,) = page.evaluate(HITS, [sid])
            if hit["inside"]:
                hit["rgb"] = median_rgb(shot, hit["box"], scale)
                hit["scroll_y"], hit["step"] = actual, f"centred-{k:02d}"
                seen[sid].append(hit)
            shot.unlink()  # the step screenshots are kept; these only feed the pixel check
        browser.close()
    (out / "check.json").write_text(
        json.dumps(
            {
                "url": url,
                "viewport": [WIDTH, HEIGHT],
                "scale": scale,
                "height": total,
                "steps": steps,
                "rows": rows,
                "seen": seen,
            }
        )
    )


if __name__ == "__main__":
    main()
