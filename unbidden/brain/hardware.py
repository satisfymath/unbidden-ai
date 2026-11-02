"""Which local Meta model this machine can run well, measured from the machine rather than assumed.

Weights plus the context's cache must fit next to Docker, the sandbox's services and the system. Apple silicon
shares memory between CPU and GPU (MLX builds); elsewhere the GPU's own memory decides (GGUF builds).
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

HEADROOM_GB = 10.0  # Docker, throwaway databases, the sandbox and the system


@dataclass(frozen=True)
class Machine:
    total_gb: float
    apple_silicon: bool
    gpu_gb: float  # dedicated GPU memory (NVIDIA); 0 on Apple silicon, whose memory is unified
    chip: str
    known: bool = True  # False when the memory size could not be read: nothing is sized from a zero

    @property
    def describe(self) -> str:
        if not self.known:
            return f"{self.chip}, memory unknown (could not be read)"
        return f"{self.chip}, {self.total_gb:.0f} GB, {self.model_budget_gb:.0f} GB for a model"

    @property
    def model_budget_gb(self) -> float:
        if not self.apple_silicon:
            return max(self.gpu_gb, 0.0)
        # Unified memory is shared with Docker and the system: keep 30% of it, at most 10 GB, for them.
        return max(0.0, self.total_gb - min(HEADROOM_GB, 0.3 * self.total_gb))


@dataclass(frozen=True)
class LocalModel:
    tag: str
    family: str
    loaded_gb: float  # weights plus a 32k-token cache, as measured or published
    think: str | None  # the reasoning control this model accepts through Ollama
    note: str


# Best first. Glimmer is Meta's open-weight reasoning model; Llama covers machines Glimmer does not fit.
CATALOG_APPLE = (
    LocalModel("muse-glimmer:30b-mxfp8-dflash", "glimmer", 42.0, "low", "8-bit: the best local quality measured"),
    LocalModel("muse-glimmer:30b-mlx", "glimmer", 24.0, "low", "4-bit (nvfp4): 25/25 on the task benchmark"),
    LocalModel("llama3.1:8b", "llama", 6.5, None, "light local work; heavy work goes to Muse Spark when it may leave"),
    LocalModel("llama3.2:3b", "llama", 3.0, None, "only what never leaves: renaming and reviewing"),
)
CATALOG_GGUF = (
    LocalModel("muse-glimmer:30b-q8_0", "glimmer", 38.0, "low", "8-bit"),
    LocalModel("muse-glimmer:30b-q4_K_M", "glimmer", 22.0, "low", "4-bit"),
    LocalModel("llama3.1:8b", "llama", 6.5, None, "light local work; heavy work goes to Muse Spark when it may leave"),
    LocalModel("llama3.2:3b", "llama", 3.0, None, "only what never leaves: renaming and reviewing"),
)


def _run(*argv: str) -> str:
    # `sysctl` lives in /usr/sbin, which a reduced PATH may lack: the absolute path is tried too.
    candidates = [argv] + ([(f"/usr/sbin/{argv[0]}", *argv[1:])] if not argv[0].startswith("/") else [])
    for command in candidates:
        try:
            out = subprocess.run(command, capture_output=True, text=True, check=False, timeout=10).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            continue
        if out:
            return out
    return ""


def detect() -> Machine:
    system = platform.system()
    apple = system == "Darwin" and platform.machine() == "arm64"
    total = 0.0
    known = False
    if system == "Darwin":
        raw = _run("sysctl", "-n", "hw.memsize")
        if raw.isdigit() and int(raw) > 0:
            total, known = int(raw) / 1024**3, True
        chip = _run("sysctl", "-n", "machdep.cpu.brand_string") or "Apple"
    else:
        meminfo = Path("/proc/meminfo")
        if meminfo.exists():
            try:
                first = meminfo.read_text().splitlines()[0].split()
                total, known = int(first[1]) / 1024**2, True
            except (OSError, IndexError, ValueError):
                known = False
        chip = platform.processor() or platform.machine()
    gpu = 0.0
    if not apple and shutil.which("nvidia-smi"):
        values = _run("nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits").splitlines()
        gpu = sum(float(v) for v in values if v.strip().replace(".", "").isdigit()) / 1024
    return Machine(round(total, 1), apple, round(gpu, 1), chip, known)


@dataclass(frozen=True)
class Recommendation:
    model: LocalModel
    installed: bool
    fits: bool
    reason: str
    profile_hint: str | None  # suggest another model profile when local capacity is small


def recommend(machine: Machine, installed: set[str]) -> Recommendation:
    """The best model that fits; an installed one is preferred over a better one that would need a download."""
    catalog = CATALOG_APPLE if machine.apple_silicon else CATALOG_GGUF
    if not machine.known:
        # Nothing is sized from an unknown machine: the smallest model is named only as a floor, not recommended.
        smallest = catalog[-1]
        return Recommendation(
            smallest,
            smallest.tag in installed,
            False,
            "memory unknown: the machine's memory size could not be read, so no local model is sized for it; "
            f"the smallest local model ({smallest.tag}) needs {smallest.loaded_gb:.0f} GB",
            "frontier",
        )
    budget = machine.model_budget_gb
    fitting = [m for m in catalog if m.loaded_gb <= budget]
    if not fitting:
        smallest = catalog[-1]
        return Recommendation(
            smallest,
            smallest.tag in installed,
            False,
            f"{budget:.0f} GB available for a model; even {smallest.tag} needs {smallest.loaded_gb:.0f} GB",
            "frontier",
        )
    best = fitting[0]
    usable_installed = [m for m in fitting if m.tag in installed]
    if usable_installed and usable_installed[0] is not best:
        chosen = usable_installed[0]
        reason = f"installed and fits in {budget:.0f} GB; {best.tag} would fit too ({best.note}) after a download"
    else:
        chosen = best
        reason = f"fits in {budget:.0f} GB: {chosen.note}"
    hint = "frontier" if chosen.family == "llama" else None
    return Recommendation(chosen, chosen.tag in installed, True, reason, hint)
