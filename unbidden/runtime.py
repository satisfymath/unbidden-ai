"""Wiring: build the brain, the dependency images and the lab for a workspace."""

from __future__ import annotations

from dataclasses import dataclass

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
        store = workspace.store()
        brain = Brain(config, build_providers(config), store, workspace.mandate(), killswitch=workspace.killswitch())
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
        stack = detect_stack(self.workspace.repo, rev)
        images = {lang: provision(self.workspace.repo, rev, getattr(stack, lang)) for lang in stack.languages}
        return stack, images
