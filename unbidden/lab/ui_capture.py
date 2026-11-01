"""Runs inside a pinned Playwright container, never on the host: load one page, wait, and report what a person would
see and what the browser saw. Written by Unbidden (not by a model, not from the repository).

Usage (in the container): python ui_capture.py <url> <wait_ms> <out_dir>
Writes <out_dir>/screenshot.png and <out_dir>/page.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    from playwright.sync_api import sync_playwright  # pyright: ignore[reportMissingImports]

    url, wait_ms, out = sys.argv[1], int(sys.argv[2]), Path(sys.argv[3])
    console_errors: list[str] = []
    failed: list[dict[str, object]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 1600})
        page.on("console", lambda m: console_errors.append(m.text[:300]) if m.type == "error" else None)
        page.on("requestfailed", lambda r: failed.append({"url": r.url[:200], "failure": str(r.failure)[:120]}))
        page.on(
            "response",
            lambda r: failed.append({"url": r.url[:200], "status": r.status}) if r.status >= 400 else None,
        )
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(wait_ms)
        dom = page.evaluate(
            """() => {
              const imgs = [...document.images];
              return {
                title: document.title,
                images: imgs.length,
                images_not_loaded: imgs.filter(i => !i.complete || i.naturalWidth === 0).length,
                text_length: document.body ? document.body.innerText.length : 0,
              };
            }"""
        )
        page.screenshot(path=str(out / "screenshot.png"), full_page=False)
        browser.close()
    (out / "page.json").write_text(
        json.dumps({"url": url, "dom": dom, "console_errors": console_errors, "failed": failed})
    )


if __name__ == "__main__":
    main()
