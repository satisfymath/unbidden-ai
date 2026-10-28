"""Wiring: build the brain, the dependency images and the lab for a workspace."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from unbidden.brain.hardware import Recommendation, detect, recommend
from unbidden.brain.providers import LLMProvider
from unbidden.brain.providers.ollama import OllamaProvider
from unbidden.brain.providers.openai_compat import OpenAICompatProvider
from unbidden.brain.router import Brain
from unbidden.bridge.service import PrivacyBridge
from unbidden.config import Config
from unbidden.contracts.llm import Tier
from unbidden.observe.stack import Stack, detect_stack
from unbidden.sandbox.provision import DependencyImage, provision
from unbidden.store import Store
from unbidden.workspace import Workspace


def installed_models(base_url: str) -> set[str]:
    try:
        return {m["name"] for m in httpx.get(f"{base_url}/api/tags", timeout=3).json().get("models", [])}
    except (httpx.HTTPError, ValueError):
        return set()


def resolve_local_model(config: Config) -> Recommendation | None:
    """Replace `model: auto` with the best installed Meta model that fits this machine."""
    route = config.routing.get(Tier.LOCAL)
    if route is None or route.model != "auto":
        return None
    provider = config.providers.get(route.provider)
    installed = installed_models(provider.base_url) if provider else set()
    rec = recommend(detect(), installed)
    route.model = rec.model.tag
    route.think = route.think_schema_only = rec.model.think
    if rec.model.think is None:
        route.think_budget = 0
    return rec


def build_providers(config: Config) -> dict[str, LLMProvider]:
    providers: dict[str, LLMProvider] = {}
    for name, spec in config.providers.items():
        if spec.kind == "ollama":
            providers[name] = OllamaProvider(spec.base_url)
        else:
            providers[name] = OpenAICompatProvider(
                name, spec.base_url, spec.key_env or "MODEL_API_KEY", required_tool_choice=spec.required_tool_choice
            )
    return providers


def _grant_model_keys(config: Config, store: Store) -> None:
    """Each remote model's key may be used to call that model, nothing else (granted again here for runtimes opened
    without load_env); every use is audited, never the value."""
    from unbidden.contracts.events import AuditEntry
    from unbidden.guardian.credentials import broker

    held = broker()
    for provider in config.providers.values():
        if provider.key_env:
            held.grant(provider.key_env, "model.remote")
    held.audit = lambda name, purpose, given: store.append_audit(
        AuditEntry(
            actor="guardian", kind="credential.use", summary=f"{name} for {purpose}: {'given' if given else 'refused'}"
        )
    )


@dataclass
class Runtime:
    workspace: Workspace
    config: Config
    store: Store
    brain: Brain

    @classmethod
    def open(cls, workspace: Workspace) -> Runtime:
        workspace.require()
        workspace.load_env()
        config = workspace.config()
        resolve_local_model(config)
        store = workspace.store()
        _grant_model_keys(config, store)
        brain = Brain(config, build_providers(config), store, workspace.mandate(), killswitch=workspace.killswitch())
        brain.repo_public = workspace.repo_public(store)
        return cls(workspace, config, store, brain)

    def bridge(self) -> PrivacyBridge | None:
        """The bridge exists only when the mandate may delegate and a key for the remote model is present."""
        from unbidden.contracts.guardian import Autonomy

        if self.workspace.mandate().autonomy.delegate_synthetic is Autonomy.DENY:
            return None
        route = self.config.routing.get(Tier.CODE)
        provider = self.brain.providers.get(route.provider) if route else None
        has_key = getattr(provider, "has_key", lambda: False)
        if provider is None or not has_key():
            return None
        return PrivacyBridge(self.brain, repo_name=self.workspace.repo.name)

    def stack_and_images(self, rev: str) -> tuple[Stack, dict[str, DependencyImage]]:
        from unbidden.guardian.policy import PolicyEngine

        stack = detect_stack(self.workspace.repo, rev)
        policy = PolicyEngine(self.workspace.mandate())
        images = {
            lang: provision(self.workspace.repo, rev, stack.part(lang), policy=policy) for lang in stack.languages
        }
        return stack, images
