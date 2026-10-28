"""Block 3 feasibility: can each Meta medium do the one thing the multimodal objective would ask of it? Small calls,
each through the machine-wide spend ledger, each recorded with model, request, latency, answer and cost.

    uv run python -m bench.multimodal.feasibility <dir with board.png and voice.wav> --out <result.json>

`board.png` is synthetic: six rows, red badges on rows 2, 4 and 6, the sixth partly covered by a footer.
`voice.wav` is a spoken sentence made with the system's speech synthesizer. The key is read from
~/.unbidden/.env (MODEL_API_KEY) and never printed.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

from unbidden.brain.spend import SpendLedger, SpendRefused

BASE = "https://api.meta.ai/v1"
PRICES = {  # dev.meta.ai/docs/pricing-rate-limits, 2026-10-28
    "muse-spark-1.3": (1.25, 4.25),
    "muse-wonder-1.0": (4.00, 20.00),
}
VISION_PROMPT = (
    "This is a screenshot of a table with six rows. Each row ends with a coloured badge. For each row, from top to "
    "bottom, say whether its badge is red, green, or not fully visible. Answer with JSON only: "
    '{"rows": [{"row": 1, "badge": "red|green", "fully_visible": true|false}, ...]}'
)


def _key() -> str:
    for line in (Path.home() / ".unbidden" / ".env").read_text().splitlines():
        if line.startswith("MODEL_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("MODEL_API_KEY not found in ~/.unbidden/.env")


def _spend(model: str, worst: float, purpose: str) -> tuple[SpendLedger, str]:
    ledger = SpendLedger()
    rid = ledger.reserve(
        est_usd=worst, workspace="bench-multimodal", purpose=purpose, provider="meta", model=model, attempt=1
    )
    return ledger, rid


def vision(model: str, image: bytes, key: str) -> dict[str, Any]:
    body = {
        "model": model,
        "max_tokens": 1500,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": VISION_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64," + base64.b64encode(image).decode()},
                    },
                ],
            }
        ],
    }
    price_in, price_out = PRICES[model]
    ledger, rid = _spend(model, 0.05, "feasibility.vision")
    started = time.monotonic()
    response = httpx.post(
        f"{BASE}/chat/completions", json=body, headers={"Authorization": f"Bearer {key}"}, timeout=180
    )
    seconds = time.monotonic() - started
    data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    usage = data.get("usage") or {}
    tin, tout = int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
    usd = (tin * price_in + tout * price_out) / 1e6 if usage else None
    ledger.settle(rid, usd=usd, tokens_in=tin, tokens_out=tout, usage_reported=bool(usage),
                  status="ok" if response.status_code == 200 else "failed", note="feasibility")  # fmt: skip
    answer = ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
    return {"model": model, "status": response.status_code, "seconds": round(seconds, 1), "tokens": [tin, tout],
            "usd": usd, "answer": answer if response.status_code == 200 else response.text[:400]}  # fmt: skip


def sam(prompt: str, image: bytes, key: str) -> dict[str, Any]:
    body = {
        "model": "sam-3.1",
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": "data:image/png;base64," + base64.b64encode(image).decode()},
                ],
            }
        ],
        "metadata": {"include_confidence": "true"},
        "stream": True,
    }
    ledger, rid = _spend("sam-3.1", 0.0025, "feasibility.sam")
    started = time.monotonic()
    text, status, raw = "", 0, ""
    headers = {"Authorization": f"Bearer {key}", "Accept": "text/event-stream"}
    with httpx.stream("POST", f"{BASE}/responses", json=body, timeout=180, headers=headers) as response:
        status = response.status_code
        for line in response.iter_lines():
            raw += line + "\n"
            if line.startswith("data:"):
                try:
                    event = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "response.output_text.delta":
                    text += event.get("delta", "")
    seconds = time.monotonic() - started
    ledger.settle(rid, usd=0.0025 if status == 200 else None, usage_reported=status == 200,
                  status="ok" if status == 200 else "failed", note=f"feasibility sam: {prompt}")  # fmt: skip
    boxes = []
    for token in text.split("<|box;")[1:]:
        fields: dict[str, str] = {}
        for item in token.split("|>")[0].split(";"):
            if "=" in item:
                name, value = item.split("=", 1)
                fields[name] = value
        boxes.append({k: (float(v) if k == "c" else int(v)) for k, v in fields.items()})
    return {"model": "sam-3.1", "prompt": prompt, "status": status, "seconds": round(seconds, 1), "usd": 0.0025,
            "boxes": boxes, "raw": (text or raw)[:300]}  # fmt: skip


def image(key: str) -> dict[str, Any]:
    body = {"model": "muse-image-1.0", "prompt": "a plain table with six rows and a coloured badge on each row",
            "n": 1, "output_format": "png"}  # fmt: skip
    ledger, rid = _spend("muse-image-1.0", 0.01, "feasibility.image")
    started = time.monotonic()
    response = httpx.post(f"{BASE}/images/generations", json=body, headers={"Authorization": f"Bearer {key}"},
                          timeout=180)  # fmt: skip
    seconds = time.monotonic() - started
    ok = response.status_code == 200
    data = response.json() if ok else {}
    n = len(data.get("data") or [])
    ledger.settle(rid, usd=0.01 * n if ok else None, usage_reported=ok, status="ok" if ok else "failed",
                  note="feasibility image")  # fmt: skip
    size = len(base64.b64decode((data.get("data") or [{}])[0].get("b64_json") or "")) if n else 0
    return {"model": "muse-image-1.0", "status": response.status_code, "seconds": round(seconds, 1),
            "usd": 0.01 * n, "images": n, "bytes": size, "error": None if ok else response.text[:300]}  # fmt: skip


def voice(wav: bytes, key: str) -> dict[str, Any]:
    seconds_audio = (len(wav) - 44) / (16000 * 2)
    worst = 0.18 * seconds_audio / 3600 + 0.0001
    ledger, rid = _spend("muse-voice-transcribe-1.0", worst, "feasibility.voice")
    request = json.dumps({"mode": "PUSH_TO_TALK", "model": "muse-voice-transcribe-1.0", "audioEncoding": "WAV"})
    started = time.monotonic()
    response = httpx.post(f"{BASE}/asr/transcribe", headers={"Authorization": f"Bearer {key}"}, timeout=180,
                          files={"request": (None, request, "application/json"),
                                 "audio": ("voice.wav", wav, "audio/wav")})  # fmt: skip
    seconds = time.monotonic() - started
    ok = response.status_code == 200
    usd = 0.18 * seconds_audio / 3600
    ledger.settle(rid, usd=usd if ok else None, usage_reported=ok, status="ok" if ok else "failed",
                  note="feasibility voice")  # fmt: skip
    return {"model": "muse-voice-transcribe-1.0", "status": response.status_code, "seconds": round(seconds, 1),
            "audio_s": round(seconds_audio, 1), "usd": usd,
            "transcript": response.json().get("transcript") if ok else response.text[:300]}  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dir")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    here = Path(os.path.expanduser(args.dir))
    board, wav, key = (here / "board.png").read_bytes(), (here / "voice.wav").read_bytes(), _key()
    results: list[dict[str, Any]] = []
    steps = [
        lambda: vision("muse-spark-1.3", board, key),
        lambda: vision("muse-wonder-1.0", board, key),
        lambda: sam("red rectangle", board, key),
        lambda: sam("rectangle", board, key),
        lambda: image(key),
        lambda: voice(wav, key),
    ]
    for step in steps:
        try:
            results.append(step())
        except (SpendRefused, httpx.HTTPError) as exc:
            results.append({"error": f"{type(exc).__name__}: {exc}"[:300]})
        print(json.dumps(results[-1])[:600])
    Path(args.out).write_text(json.dumps({"truth": {"red_rows": [2, 4, 6], "partly_hidden": [6]}, "results": results},
                                         indent=1))  # fmt: skip


if __name__ == "__main__":
    main()
