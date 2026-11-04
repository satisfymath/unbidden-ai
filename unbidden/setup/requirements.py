"""Which of `doctor`'s checks are required for the option a mandate chose, and which are optional. A missing optional
dependency never makes the installation look unusable."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from unbidden.contracts.guardian import Autonomy, Mandate

Need = Literal["required", "optional"]

LOCAL_CHECKS = ("ollama", "local model")


def doctor_requirements(mandate: Mandate | None) -> dict[str, Need]:
    """Without a mandate nothing has been chosen, so only the machine itself is required."""
    needs: dict[str, Need] = {
        "ollama": "optional",
        "local model": "optional",
        "docker": "optional",
        "docker buildx": "optional",
        "docker compose": "optional",
        "act": "optional",  # the team's CI job prepares the environment (sandbox/ci_env.py)
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
        # The project's checks and every experiment run in the sandbox, whose images BuildKit builds; the map of the
        # running system reads compose. Without them the first cycle records a compatibility block instead of work.
        needs["docker"] = needs["docker buildx"] = needs["docker compose"] = "required"
    return needs


def option_of(models: Any) -> str:
    """The option a models policy amounts to: `api` for a frontier profile (local inference allowed or not: Ollama
    is optional either way), `local`, `mixed` for local-first, else `custom` (a mandate written by hand)."""
    profile = getattr(models, "profile", None) if not isinstance(models, dict) else models.get("profile")
    profile = profile or "local-first"
    if profile == "frontier":
        return "api"
    return {"local": "local", "local-first": "mixed"}.get(profile, "custom")


def explain(needs: dict[str, Need], mandate: Mandate | None) -> str:
    if mandate is None:
        return "no mandate yet: nothing is required until `unbidden setup` chooses an option"
    option = option_of(mandate.models)
    if option == "api":
        return "option api: Ollama and a local model are optional; the Meta API key is required"
    if option == "local":
        return "option local: Ollama and a local model are required; the Meta API is not used"
    return "option mixed: Ollama and a local model are required; the Meta API key is optional (heavy work goes local)"


# --- the start guard --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class StartCheck:
    name: str
    ok: bool
    detail: str
    fix: str  # the one command that changes it
    blocks: bool  # a failure refuses the start (no model for the option); otherwise it only warns


@dataclass
class StartVerdict:
    refused: list[StartCheck] = field(default_factory=list)
    warnings: list[StartCheck] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.refused

    def as_dict(self) -> dict[str, Any]:
        row = lambda c: {"check": c.name, "detail": c.detail, "fix": c.fix}  # noqa: E731
        return {"refused": [row(c) for c in self.refused], "warnings": [row(c) for c in self.warnings]}


def start_checks(ws: Any, *, docker_timeout_s: float = 5.0) -> StartVerdict:
    """What `start` looks at before running the agent (no GitHub, no repository diagnosis): the agent must not run
    on a configuration under which every cycle fails. Refuses: the option's model is missing (Ollama unreachable or
    the recommended model not pulled; no API key for the frontier profile, or one the service refused: each key is
    proven once with a short call). Warns and starts: Docker or its plugins absent (experiments and the map stay
    blocked until it runs), no GitHub token while the mandate lets proposals become pull requests."""
    import shutil
    import subprocess

    from unbidden.brain.hardware import detect, recommend
    from unbidden.guardian.credentials import broker
    from unbidden.runtime import installed_models

    verdict = StartVerdict()
    ws.load_env()
    try:
        mandate = ws.mandate()
    except Exception as exc:
        verdict.refused.append(StartCheck("mandate", False, f"invalid: {exc}", "unbidden setup", True))
        return verdict
    needs = doctor_requirements(mandate)
    config = ws.config()
    if needs["ollama"] == "required":
        provider = config.providers.get("ollama")
        url = provider.base_url if provider else "http://localhost:11434"
        installed = installed_models(url)
        if not installed:
            verdict.refused.append(
                StartCheck("ollama", False, f"not reachable at {url}", "unbidden setup models", True)
            )
        else:
            rec = recommend(detect(), installed)
            if not (rec.installed and rec.fits):
                verdict.refused.append(
                    StartCheck("local model", False, f"{rec.model.tag} not installed", "unbidden doctor --fix", True)
                )
    key_env = next((p.key_env for p in config.providers.values() if p.key_env), "MODEL_API_KEY")
    if needs["meta api"] == "required" and not broker().has(key_env):
        verdict.refused.append(StartCheck("meta api", False, f"no {key_env}", "unbidden key set", True))
    elif broker().has(key_env) and option_of(mandate.models) in ("api", "mixed"):
        # A key the service refuses fails every remote call: proven once per key (one short call, in the ledger);
        # a key that cannot be proven now (no network) is not what would fail, so it only warns.
        from unbidden.setup.keycheck import verify_key

        key = verify_key(ws, name=key_env)
        if key.rejected:
            check = StartCheck("meta api", False, f"{key_env} refused by the service", "unbidden key set", True)
            (verdict.refused if needs["meta api"] == "required" else verdict.warnings).append(check)
        elif not key.ok:
            verdict.warnings.append(
                StartCheck("meta api", False, f"{key_env} not proven ({(key.why or '')[:80]})", "unbidden key", False)
            )
    if needs["docker"] == "required":
        up = False
        if shutil.which("docker"):
            try:
                up = (
                    subprocess.run(
                        ["docker", "info"], capture_output=True, check=False, timeout=docker_timeout_s
                    ).returncode
                    == 0
                )
            except (OSError, subprocess.SubprocessError):
                up = False
        if not up:
            detail = "not running: experiments and the map stay blocked"
            verdict.warnings.append(StartCheck("docker", False, detail, "unbidden doctor", False))
        else:
            from unbidden.cli import docker_plugins

            for name, ok, detail in docker_plugins(True):
                if not ok:
                    verdict.warnings.append(StartCheck(name, False, detail, "unbidden doctor", False))
    from unbidden.setup.recon import incomplete_why, status

    recon = status(ws.store())
    if recon is None:
        verdict.warnings.append(
            StartCheck(
                "recon",
                False,
                "never ran: the stack, the database and GitHub are not confirmed",
                "unbidden setup recon",
                False,
            )
        )
    elif not recon.get("complete"):
        # Only a deploy needs the running stack and its database; a merge on the team's green CI does not (a library
        # with a compose file for its tests: sqlmodel, campaign 13), so there an incomplete recon is a warning.
        deploys = mandate.autonomy.deploy is Autonomy.ALLOW
        check = StartCheck("recon", False, f"incomplete: {incomplete_why(recon)}", "unbidden setup recon", deploys)
        (verdict.refused if deploys else verdict.warnings).append(check)
    github = mandate.autonomy.open_pull_requests is not Autonomy.DENY
    if github and not broker().has(mandate.egress.github.token_env):
        verdict.warnings.append(
            StartCheck("github", False, "no token: proposals stay local branches", "unbidden setup credentials", False)
        )
    return verdict
