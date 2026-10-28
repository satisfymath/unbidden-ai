"""The UI lab: what a page looks like and what the browser saw, now and against a known-good reference.

Two judges answer "is this page healthy, and if not, what is wrong with it":
- `browser_judge`, with no model: console errors, failed requests and images that never loaded, compared with the
  reference capture;
- `visual_judge`: the two screenshots shown to a multimodal Meta model. Screenshots leave only when the workspace's
  mandate allows it (`models.screenshots_to_frontier`) and the egress gate records each send with its digest; the
  images themselves are kept locally under `.unbidden/artifacts/ui/` for audit.

The capture runs in a pinned Playwright container, never on the host, on an internal network that reaches the
project's published page and nothing else. Anomaly captures are kept for the mandate's retention, then removed.
"""

from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from unbidden.brain.spend import SpendLedger, SpendRefused, worst_cost
from unbidden.config import load_config
from unbidden.contracts.events import Event, EventType
from unbidden.contracts.guardian import ActionRequest, EgressAttempt, Mandate
from unbidden.guardian.egress import evaluate_screenshots
from unbidden.guardian.killswitch import SANDBOX_LABEL, Cancelled, before_effect, labels
from unbidden.guardian.policy import PolicyEngine
from unbidden.store import Store

PLAYWRIGHT_BASE = "mcr.microsoft.com/playwright/python:v1.49.1-noble"  # browsers and their libraries, pinned
PLAYWRIGHT_IMAGE = "unbidden-ui:1.49.1"  # the base plus the matching playwright package from PyPI


def ensure_image() -> None:
    """Build the capture image once; it only adds the pinned playwright package to the pinned base."""
    if (
        subprocess.run(["docker", "image", "inspect", PLAYWRIGHT_IMAGE], capture_output=True, check=False).returncode
        == 0
    ):
        return
    dockerfile = f"FROM {PLAYWRIGHT_BASE}\nRUN pip install --no-cache-dir --break-system-packages playwright==1.49.1\n"
    out = subprocess.run(
        ["docker", "build", "-q", "-t", PLAYWRIGHT_IMAGE, "-"],
        input=dockerfile,
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode != 0:
        raise RuntimeError(f"the capture image could not be built: {out.stderr.strip()[-400:]}")


CAPTURE_SCRIPT = Path(__file__).with_name("ui_capture.py")
VISUAL_MODEL = "muse-spark-1.3"


@dataclass(frozen=True)
class Capture:
    url: str
    screenshot: bytes
    page: dict[str, Any]
    kept_at: Path


FORWARD_SCRIPT = Path(__file__).with_name("ui_forward.py")
LOCAL_PAGE = re.compile(r"^http://(?:127\.0\.0\.1|localhost):(?P<port>\d+)(?P<rest>/.*)?$")
APP_ALIAS = "app"


def capture_argv(network: str, port: int, rest: str, work: Path, wait_ms: int) -> list[str]:
    """The browser's container: on an internal network whose only other member is the forwarder, read-only, not
    root, no capabilities. Whatever the page asks of another host fails, as it would offline."""
    return [
        "docker", "run", "--rm", *labels(), "--network", network,
        "--read-only", "--tmpfs", "/tmp:rw,nosuid,size=512m", "-e", "HOME=/tmp", "--user", "1001:1001",
        "--memory", "2g", "--cpus", "2", "--pids-limit", "512", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "-v", f"{CAPTURE_SCRIPT}:/cap/ui_capture.py:ro", "-v", f"{work}:/out",
        PLAYWRIGHT_IMAGE, "python", "/cap/ui_capture.py", f"http://{APP_ALIAS}:{port}{rest}", str(wait_ms), "/out",
    ]  # fmt: skip


def forwarder_argv(name: str, port: int) -> list[str]:
    """The relay: Unbidden's fixed code on the same pinned image, reaching the host's published port only."""
    return [
        "docker", "run", "-d", "--rm", "--name", name, *labels(), "--add-host", "host.docker.internal:host-gateway",
        "--read-only", "--user", "1001:1001", "--memory", "64m", "--pids-limit", "64", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "-v", f"{FORWARD_SCRIPT}:/cap/ui_forward.py:ro",
        PLAYWRIGHT_IMAGE, "python", "/cap/ui_forward.py", str(port),
    ]  # fmt: skip


def capture(url: str, out_dir: Path, *, wait_ms: int = 3000, timeout_s: float = 120) -> Capture:
    """Load `url` (a page the project publishes on this machine, `http://127.0.0.1:<port>`) in a container and keep
    what it showed. The browser reaches that port and nothing else: not the internet, not the host's other ports."""
    local = LOCAL_PAGE.match(url)
    if local is None:
        raise RuntimeError(f"only a page published on this machine is captured, not {url}")
    port, rest = int(local["port"]), local["rest"] or "/"
    ensure_image()
    tag = uuid.uuid4().hex[:12]
    network, relay = f"unbidden-int-ui-{tag}", f"unbidden-ui-relay-{tag}"
    work = Path(tempfile.mkdtemp(prefix="unbidden-ui-"))
    work.chmod(0o777)  # written by the container's unprivileged user
    docker = ["docker"]
    try:
        _docker(*docker, "network", "create", "--internal", "--label", f"{SANDBOX_LABEL}=1", network)
        _docker(*forwarder_argv(relay, port))
        _docker(*docker, "network", "connect", "--alias", APP_ALIAS, network, relay)
        out = subprocess.run(
            capture_argv(network, port, rest, work, wait_ms), capture_output=True, text=True, timeout=timeout_s,
            check=False,
        )  # fmt: skip
        if out.returncode != 0:
            raise RuntimeError(f"capture of {url} failed: {out.stderr.strip()[-400:]}")
        out_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(work / "screenshot.png", out_dir / "screenshot.png")
        shutil.copy(work / "page.json", out_dir / "page.json")
        page = json.loads((work / "page.json").read_text())
        return Capture(url, (work / "screenshot.png").read_bytes(), page, out_dir)
    finally:
        subprocess.run(["docker", "kill", relay], capture_output=True, check=False)
        subprocess.run(["docker", "network", "rm", network], capture_output=True, check=False)
        shutil.rmtree(work, ignore_errors=True)


def _docker(*argv: str) -> None:
    out = subprocess.run(list(argv), capture_output=True, text=True, check=False)
    if out.returncode != 0:
        raise RuntimeError(f"{' '.join(argv[:3])} failed: {out.stderr.strip()[-300:]}")


def prune(artifacts: Path, keep_days: float, *, now: float | None = None) -> list[str]:
    """Remove anomaly captures older than the mandate's retention; the reference is kept (it is replaced instead).
    Returns what was removed."""
    import time

    cutoff = (now if now is not None else time.time()) - keep_days * 86400
    removed = []
    for path in sorted(artifacts.glob("anomaly-*")):
        stamp = path.name.removeprefix("anomaly-")
        if path.is_dir() and stamp.isdigit() and int(stamp) < cutoff:
            shutil.rmtree(path, ignore_errors=True)
            removed.append(path.name)
    return removed


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
    try:
        before_effect(store, "remote visual judgement")
    except Cancelled as exc:
        attempt.status = "failed"
        store.put("egress", attempt)
        return {"degraded": None, "what": f"not sent: {exc}"}

    def image(data: bytes) -> dict[str, Any]:
        return {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(data).decode()}}

    content = [{"type": "text", "text": VISUAL_PROMPT}, image(reference.screenshot), image(now.screenshot)]
    body = {
        "model": VISUAL_MODEL,
        "max_tokens": 3000,
        "messages": [{"role": "user", "content": content}],
    }  # fmt: skip
    # The same machine-wide budget as every other remote call (brain/spend.py).
    price = load_config().prices.models.get(VISUAL_MODEL)
    if price is None:
        return {"degraded": None, "what": f"not sent: no price is known for {VISUAL_MODEL}"}
    ledger = SpendLedger()
    est = worst_cost(len(json.dumps(body)), 3000, price.input_per_mtok, price.output_per_mtok)
    try:
        spend_id = ledger.reserve(
            est_usd=est, workspace=mandate.workspace, purpose="lab.ui.visual", provider="meta", model=VISUAL_MODEL,
            attempt=1,
        )  # fmt: skip
    except SpendRefused as exc:
        attempt.status = "failed"
        store.put("egress", attempt)
        return {"degraded": None, "what": f"not sent: {exc}"}
    try:
        response = httpx.post(
            f"{base_url}/chat/completions", json=body, headers={"Authorization": f"Bearer {key}"}, timeout=180
        )
    except httpx.HTTPError as exc:
        ledger.settle(spend_id, usd=None, usage_reported=False, status="failed", note=str(exc)[:300])
        raise
    attempt.status = "allowed_sent" if response.status_code == 200 else "failed"
    store.put("egress", attempt)
    if response.status_code != 200:
        billed = None if response.status_code >= 500 else 0.0
        ledger.settle(spend_id, usd=billed, usage_reported=False, status="failed", note=f"HTTP {response.status_code}")
        return {"degraded": None, "what": f"model answered {response.status_code}"}
    data = response.json()
    usage = data.get("usage") or {}
    tokens_in, tokens_out = int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
    reported = tokens_in > 0 or tokens_out > 0
    ledger.settle(
        spend_id,
        usd=(tokens_in * price.input_per_mtok + tokens_out * price.output_per_mtok) / 1e6 if reported else None,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        usage_reported=reported,
    )
    text = data["choices"][0]["message"].get("content") or ""
    found = re.search(r"\{.*\}", text, re.DOTALL)
    try:
        answer = json.loads(found.group(0)) if found else {}
    except ValueError:
        answer = {}
    return {"degraded": answer.get("degraded"), "what": str(answer.get("what", text[:200]))}
