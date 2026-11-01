"""SAM 3.1 on a screenshot: regions matching a short noun phrase, as boxes with a confidence, in page coordinates.

SAM predicts; it does not measure. Its boxes are an observation like any other: mapped to the page (screenshot
pixels / scale + the step's scroll offset), bound to the rows they fall in, and never the basis of an acceptance.
Each call goes through the mandate's policy and screenshot egress rule, the kill switch and the machine-wide spend
ledger (US$2.50 per 1,000 images, dev.meta.ai pricing), and is recorded as an egress attempt by its digest.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx

from unbidden.brain.spend import SpendLedger, SpendRefused
from unbidden.contracts.events import Event, EventType
from unbidden.contracts.guardian import ActionRequest, EgressAttempt, Mandate
from unbidden.guardian.egress import evaluate_screenshots
from unbidden.guardian.killswitch import Cancelled, before_effect
from unbidden.guardian.policy import PolicyEngine
from unbidden.store import Store

MODEL = "sam-3.1"
USD_PER_IMAGE = 2.50 / 1000


@dataclass(frozen=True)
class Region:
    x: float  # page CSS pixels
    y: float
    w: float
    h: float
    confidence: float | None


class SamRefused(RuntimeError):
    pass


def parse(text: str) -> list[dict[str, float]]:
    """Boxes from SAM's token output: `<|box;x1=..;y1=..;x2=..;y2=..;w=..;h=..[;c=..]|>`."""
    boxes = []
    for token in text.split("<|box;")[1:]:
        fields: dict[str, float] = {}
        for item in token.split("|>")[0].split(";"):
            if "=" in item:
                name, value = item.split("=", 1)
                try:
                    fields[name] = float(value)
                except ValueError:
                    continue
        if {"x1", "y1", "x2", "y2"} <= fields.keys():
            boxes.append(fields)
    return boxes


def to_page(box: dict[str, float], scale: float, scroll_y: float) -> Region:
    return Region(
        x=box["x1"] / scale,
        y=box["y1"] / scale + scroll_y,
        w=(box["x2"] - box["x1"]) / scale,
        h=(box["y2"] - box["y1"]) / scale,
        confidence=box.get("c"),
    )


def segment(
    png: bytes, prompt: str, *, store: Store, mandate: Mandate, key: str, base_url: str = "https://api.meta.ai/v1"
) -> tuple[list[dict[str, float]], dict[str, Any]]:
    """SAM's boxes on one screenshot (in its pixels), and the call's record (latency, cost)."""
    destination = httpx.URL(base_url).host
    verdict = PolicyEngine(mandate).evaluate(
        ActionRequest(capability="model.remote.screenshot", purpose="segment a page", destinations=[destination])
    )
    egress = evaluate_screenshots(mandate, destination, [png], prompt)
    if not verdict.allowed:
        egress = egress.model_copy(update={"allowed": False, "reasons": [*egress.reasons, *verdict.reasons]})
    attempt = EgressAttempt(
        status="allowed_pending" if egress.allowed else "blocked", purpose="lab.ui.segment", destination=destination,
        provider="meta", model=MODEL, verdict=egress, payload=f"sha256:{egress.payload_sha256} ({prompt!r})",
    )  # fmt: skip
    store.put("egress", attempt)
    store.append_event(
        Event(type=EventType.EGRESS_ALLOWED if egress.allowed else EventType.EGRESS_BLOCKED, actor="lab",
              entity_id=attempt.id, payload={"purpose": attempt.purpose, "destination": destination,
                                             "bytes": egress.payload_bytes, "sha256": egress.payload_sha256})
    )  # fmt: skip
    if not egress.allowed:
        raise SamRefused("; ".join(egress.reasons))
    try:
        before_effect(store, "remote segmentation")
    except Cancelled as exc:
        raise SamRefused(str(exc)) from exc
    ledger = SpendLedger()
    try:
        rid = ledger.reserve(est_usd=USD_PER_IMAGE, workspace=mandate.workspace, purpose="lab.ui.segment",
                             provider="meta", model=MODEL, attempt=1)  # fmt: skip
    except SpendRefused as exc:
        raise SamRefused(str(exc)) from exc
    body = {
        "model": MODEL,
        "input": [{"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": prompt},
            {"type": "input_image", "image_url": "data:image/png;base64," + base64.b64encode(png).decode()},
        ]}],
        "metadata": {"include_confidence": "true"},
        "stream": True,
    }  # fmt: skip
    started, text, status = time.monotonic(), "", 0
    try:
        headers = {"Authorization": f"Bearer {key}", "Accept": "text/event-stream"}
        with httpx.stream("POST", f"{base_url}/responses", json=body, timeout=120, headers=headers) as response:
            status = response.status_code
            for line in response.iter_lines():
                if line.startswith("data:"):
                    try:
                        event = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    if event.get("type") == "response.output_text.delta":
                        text += event.get("delta", "")
    except httpx.HTTPError as exc:
        ledger.settle(rid, usd=None, usage_reported=False, status="failed", note=str(exc)[:300])
        attempt.status = "failed"
        store.put("egress", attempt)
        raise SamRefused(f"segmentation failed: {exc}") from exc
    ok = status == 200
    # A refusal (4xx) is not billed; a server error may have been: its worst cost stands.
    usd = USD_PER_IMAGE if ok else (0.0 if 400 <= status < 500 else None)
    ledger.settle(rid, usd=usd, usage_reported=ok, status="settled" if ok else "failed", note=f"segment {prompt!r}")
    attempt.status = "allowed_sent" if ok else "failed"
    store.put("egress", attempt)
    if not ok:
        raise SamRefused(f"segmentation answered {status}")
    record = {"model": MODEL, "prompt": prompt, "seconds": round(time.monotonic() - started, 2),
              "usd": USD_PER_IMAGE, "image_sha256": egress.payload_sha256}  # fmt: skip
    return parse(text), record
