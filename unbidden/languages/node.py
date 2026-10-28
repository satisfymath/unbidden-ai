"""JavaScript and TypeScript: npm, pnpm, bun and yarn classic projects, workspace packages one by one."""

from __future__ import annotations

from pathlib import Path

from unbidden.languages import Syntax, register
from unbidden.observe.stack import NodeStack, _detect_node  # pyright: ignore[reportPrivateUsage]
from unbidden.sandbox.provision import NODE_REGISTRIES, DependencyImage, _manifests, node_dockerfile  # pyright: ignore[reportPrivateUsage]
from unbidden.sandbox.tools import TOOLS, Tool


class NodeAdapter:
    name = "node"
    part_type = NodeStack
    syntax = Syntax("TypeScript/JavaScript", "//", "`@ts-ignore`, `eslint-disable`",
                    (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"))  # fmt: skip
    registries = tuple(NODE_REGISTRIES)
    capabilities = frozenset({"analyze", "test", "fix"})
    test_report = "exit"

    def detect(self, repo: Path, rev: str, files: set[str], blind: list[str]) -> NodeStack | None:
        return _detect_node(repo, rev, files, blind)

    def manifests(self, repo: Path, rev: str, part: NodeStack) -> list[str]:
        return _manifests(repo, rev, part)

    def generated(self, part: NodeStack) -> dict[str, str]:
        return {}

    def dockerfile(self, part: NodeStack, *, system_build_tools: bool, headers: tuple[str, ...]) -> str:
        return node_dockerfile(part)

    def image(self, tag: str, part: NodeStack, docker: str) -> DependencyImage:
        return DependencyImage(
            tag=tag,
            language="node",
            registries=list(self.registries),
            env={
                "PATH": "/deps/node_modules/.bin:/usr/local/bin:/usr/bin:/bin",
                "COREPACK_HOME": "/opt/corepack",
                "COREPACK_ENABLE_DOWNLOAD_PROMPT": "0",
                # node_modules is the image's, linked in: installed and verified when the image was built.
                "npm_config_verify_deps_before_run": "false",
            },
            links={"node_modules": "/deps/node_modules"},
            # A workspace package's node_modules holds relative links into the store and to sibling packages;
            # copied into /work (links only, cheap) they resolve against the snapshot's real sources.
            setup=tuple(
                f"mkdir -p /work/{p.path} && cp -a /deps/{p.path}/node_modules /work/{p.path}/ 2>/dev/null || true"
                for p in part.packages
            ),
        )

    def tools(self, part: NodeStack) -> list[Tool]:
        selected: list[Tool] = []
        if part.typescript:
            selected.append(TOOLS["tsc"])
        if part.eslint:
            selected.append(TOOLS["eslint"])
        if part.biome:
            selected.append(TOOLS["biome"])
        for package in part.packages:
            if package.typescript:
                argv = (*package.typecheck, "--pretty", "false") if package.typecheck else None
                selected.append(TOOLS["tsc"].in_package(package.path, argv))
            if package.eslint:
                selected.append(TOOLS["eslint"].in_package(package.path))
            if package.biome:
                selected.append(TOOLS["biome"].in_package(package.path))
        return selected

    def test_argv(self, part: NodeStack) -> list[str] | None:
        return [part.manager, "run", part.test_script] if part.test_script else None


ADAPTER = register(NodeAdapter())
