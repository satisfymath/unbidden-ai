"""Which of `doctor`'s checks are required for the option a mandate chose, and which are optional. A missing optional
dependency never makes the installation look unusable."""

from __future__ import annotations

from typing import Literal

from unbidden.contracts.guardian import Autonomy, Mandate

Need = Literal["required", "optional"]

LOCAL_CHECKS = ("ollama", "local model")


def doctor_requirements(mandate: Mandate | None) -> dict[str, Need]:
    """Without a mandate nothing has been chosen, so only the machine itself is required."""
    needs: dict[str, Need] = {
        "ollama": "optional",
        "local model": "optional",
        "docker": "optional",
        "meta api": "optional",
        "github": "optional",
        "mandate": "optional",
    }
    if mandate is None:
        return needs
    needs["mandate"] = "required"
    models = mandate.models
    if models.local_inference == "allow" and models.profile != "frontier":
        needs["ollama"] = needs["local model"] = "required"
    if models.profile == "frontier":
        needs["meta api"] = "required"
    autonomy = mandate.autonomy
    if autonomy.run_experiments is not Autonomy.DENY or autonomy.observe is not Autonomy.DENY:
        needs["docker"] = "required"  # the project's checks and every experiment run in the sandbox
    return needs


def explain(needs: dict[str, Need], mandate: Mandate | None) -> str:
    if mandate is None:
        return "no mandate yet: nothing is required until `unbidden setup` chooses an option"
    profile = mandate.models.profile
    if profile == "frontier" and mandate.models.local_inference == "deny":
        return "option api: Ollama and a local model are optional; the Meta API key is required"
    if profile == "local":
        return "option local: Ollama and a local model are required; the Meta API is not used"
    return "option mixed: Ollama and a local model are required; the Meta API key is optional (heavy work goes local)"
