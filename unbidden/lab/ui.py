"""The UI lab: what a page looks like and what the browser saw, now and against a known-good reference.

Two judges answer "is this page healthy, and if not, what is wrong with it":
- `browser_judge`, with no model: console errors, failed requests and images that never loaded, compared with the
  reference capture;
- `visual_judge`: the two screenshots shown to a multimodal Meta model. Screenshots leave only when the workspace's
  mandate allows it (`models.screenshots_to_frontier`) and the egress gate records each send with its digest; the
  images themselves are kept locally under `.unbidden/artifacts/ui/` for audit.

The capture runs in a pinned Playwright container, never on the host.
"""

from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from unbidden.contracts.events import Event, EventType
from unbidden.contracts.guardian import ActionRequest, EgressAttempt, Mandate
from unbidden.guardian.egress import evaluate_screenshots
from unbidden.guardian.policy import PolicyEngine
from unbidden.store import Store

PLAYWRIGHT_IMAGE = "mcr.microsoft.com/playwright/python:v1.49.1-noble"
CAPTURE_SCRIPT = Path(__file__).with_name("ui_capture.py")
VISUAL_MODEL = "muse-spark-1.3"


@dataclass(frozen=True)
class Capture:
    url: str
    screenshot: bytes
    page: dict[str, Any]
    kept_at: Path


def capture(url: str, out_dir: Path, *, wait_ms: int = 3000, timeout_s: float = 120) -> Capture:
    """Load `url` (a page the project publishes on this machine) in a container and keep what it showed.
    `http://127.0.0.1:<port>` is reached from the container as the host's published port."""
    target = re.sub(r"^http://(127\.0\.0\.1|localhost)", "http://host.docker.internal", url)
    work = Path(tempfile.mkdtemp(prefix="unbidden-ui-"))
    try:
        argv = [
            "docker", "run", "--rm", "--add-host", "host.docker.internal:host-gateway",
            "--memory", "2g", "--cpus", "2", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "-v", f"{CAPTURE_SCRIPT}:/cap/ui_capture.py:ro", "-v", f"{work}:/out",
            PLAYWRIGHT_IMAGE, "python", "/cap/ui_capture.py", target, str(wait_ms), "/out",
        ]  # fmt: skip
        out = subprocess.run(argv, capture_output=True, text=True, timeout=timeout_s, check=False)
        if out.returncode != 0:
            raise RuntimeError(f"capture of {url} failed: {out.stderr.strip()[-400:]}")
        out_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(work / "screenshot.png", out_dir / "screenshot.png")
        shutil.copy(work / "page.json", out_dir / "page.json")
        page = json.loads((work / "page.json").read_text())
        return Capture(url, (work / "screenshot.png").read_bytes(), page, out_dir)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _failed_paths(page: dict[str, Any]) -> set[str]:
    return {re.sub(r"^https?://[^/]+", "", str(f["url"])).split("?")[0] for f in page.get("failed", [])}


def browser_judge(now: dict[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
    """No model: what the browser reports that the reference did not."""
    new_failures = sorted(_failed_paths(now) - _failed_paths(reference))
    new_errors = [e for e in now.get("console_errors", []) if e not in reference.get("console_errors", [])]
    missing_images = now["dom"]["images_not_loaded"] - reference["dom"]["images_not_loaded"]
    signs = [
        *(f"request failed: {p}" for p in new_failures[:5]),
        *(f"console error: {e[:80]}" for e in new_errors[:3]),
        *([f"{missing_images} more image(s) not loaded"] if missing_images > 0 else []),
    ]
    return {"degraded": bool(signs), "what": "; ".join(signs) or "nothing differs"}


VISUAL_PROMPT = (
    "Two screenshots of the same web page. The first was taken when the page was known to be healthy; the second "
    "is now. Product listings, prices and recommendations may legitimately differ between loads. Is something "
    "broken, missing or wrong in the second one that was fine in the first: a section gone, images missing, an error "
    "shown, a layout broken? Answer with one line of JSON only: "
    '{"degraded": true or false, "what": "the part of the page that is wrong, in a few words, or empty"}'
)


def visual_judge(
    now: Capture,
    reference: Capture,
    *,
    store: Store,
    mandate: Mandate,
    key: str,
    base_url: str = "https://api.meta.ai/v1",
) -> dict[str, Any]:
    """The screenshots, judged by a multimodal Meta model, under the mandate's explicit permission."""
    destination = httpx.URL(base_url).host
    verdict = PolicyEngine(mandate).evaluate(
        ActionRequest(capability="model.remote.screenshot", purpose="judge a page visually", destinations=[destination])
    )
    egress = evaluate_screenshots(mandate, destination, [reference.screenshot, now.screenshot], VISUAL_PROMPT)
    if not verdict.allowed:
        egress = egress.model_copy(update={"allowed": False, "reasons": [*egress.reasons, *verdict.reasons]})
    attempt = EgressAttempt(
        status="allowed_pending" if egress.allowed else "blocked",
        purpose="lab.ui.visual",
        destination=destination,
        provider="meta",
        model=VISUAL_MODEL,
        verdict=egress,
        payload=f"sha256:{egress.payload_sha256} (2 screenshots kept at {now.kept_at} and {reference.kept_at})",
    )
    store.put("egress", attempt)
    store.append_event(
        Event(
            type=EventType.EGRESS_ALLOWED if egress.allowed else EventType.EGRESS_BLOCKED,
            actor="lab",
            entity_id=attempt.id,
            payload={"purpose": attempt.purpose, "destination": destination, "bytes": egress.payload_bytes,
                     "sha256": egress.payload_sha256, "reasons": egress.reasons},
        )
    )  # fmt: skip
    if not egress.allowed:
        return {"degraded": None, "what": "not sent: " + "; ".join(egress.reasons)}

    def image(data: bytes) -> dict[str, Any]:
        return {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(data).decode()}}

    content = [{"type": "text", "text": VISUAL_PROMPT}, image(reference.screenshot), image(now.screenshot)]
    body = {
        "model": VISUAL_MODEL,
        "max_tokens": 3000,
        "messages": [{"role": "user", "content": content}],
    }  # fmt: skip
    response = httpx.post(
        f"{base_url}/chat/completions", json=body, headers={"Authorization": f"Bearer {key}"}, timeout=180
    )
    attempt.status = "allowed_sent" if response.status_code == 200 else "failed"
    store.put("egress", attempt)
    if response.status_code != 200:
        return {"degraded": None, "what": f"model answered {response.status_code}"}
    text = response.json()["choices"][0]["message"].get("content") or ""
    found = re.search(r"\{.*\}", text, re.DOTALL)
    try:
        answer = json.loads(found.group(0)) if found else {}
    except ValueError:
        answer = {}
    return {"degraded": answer.get("degraded"), "what": str(answer.get("what", text[:200]))}
