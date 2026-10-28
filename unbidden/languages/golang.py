"""Go modules: dependencies from the module proxy, `go vet` and compile errors as findings, `go test -json` offline.

Provisioning reads only go.mod and go.sum, which are data: `go mod download` fetches modules without running any
of their code, through proxy.golang.org only (no `direct`, so never a VCS host) and with GOTOOLCHAIN=local, so no
other toolchain is fetched either. Compiling, vetting and testing happen in the sandbox, offline (GOPROXY=off), with
the build cache and Go's temporary directory under /work: the sandbox's /tmp is noexec, and `go test` runs the test
binaries it builds from its temporary directory.

Declared capabilities are those its conformance test shows: analyze and test. Not fix: until the lab's edit and
measurement loop is shown on Go, the Director waits on Go findings instead of experimenting.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from unbidden.contracts.finding import AnalyzerReport, Finding
from unbidden.languages import Syntax, register
from unbidden.sandbox.provision import DependencyImage
from unbidden.sandbox.runner import SandboxResult
from unbidden.sandbox.tools import Tool, _report  # pyright: ignore[reportPrivateUsage]

GO_REGISTRIES: tuple[str, ...] = ("proxy.golang.org", "sum.golang.org")
DEFAULT_GO = "1.24"
CACHE = "/work/.unbidden-go"


@dataclass(frozen=True)
class GoStack:
    version: str  # the toolchain's minor version, from go.mod's toolchain or go directive
    module: str
    vendored: bool  # vendor/modules.txt: dependencies are in the repository, nothing to download
    has_tests: bool
    golangci: bool  # the team configures golangci-lint, which Unbidden does not run (said as a blind spot)


_GO_DIRECTIVE = re.compile(r"^go\s+(\d+)\.(\d+)", re.MULTILINE)
_TOOLCHAIN = re.compile(r"^toolchain\s+go(\d+)\.(\d+)", re.MULTILINE)
_MODULE = re.compile(r"^module\s+(\S+)", re.MULTILINE)


def go_version(go_mod: str) -> str:
    found = _TOOLCHAIN.search(go_mod) or _GO_DIRECTIVE.search(go_mod)
    return f"{found.group(1)}.{found.group(2)}" if found else DEFAULT_GO


def _show(repo: Path, rev: str, path: str) -> str:
    import subprocess

    shown = subprocess.run(["git", "-C", str(repo), "show", f"{rev}:{path}"], capture_output=True, text=True)
    return shown.stdout if shown.returncode == 0 else ""


# go vet ------------------------------------------------------------------------------------------------

_COMPILE = re.compile(r"^(?:vet: )?(?:/work/)?(?:\./)?(?P<path>[\w./-]+\.go):(?P<line>\d+)(?::\d+)?: (?P<message>.+)$")


def parse_go_vet(result: SandboxResult, argv: list[str]) -> AnalyzerReport:
    """`go vet -json` writes one JSON object per package (package -> analyzer -> diagnostics) after a `# pkg`
    line; a package that does not compile is reported as plain `file:line:col: message` lines instead. Both become
    findings; a run with neither and a failing exit is a failure of the tool."""
    text = "\n".join(ln for ln in (result.stderr + "\n" + result.stdout).splitlines() if not ln.startswith("#"))
    findings: list[Finding] = []
    decoder = json.JSONDecoder()
    position, parsed_any = 0, False
    while (start := text.find("{", position)) != -1:
        try:
            value, end = decoder.raw_decode(text, start)
        except ValueError:
            position = start + 1
            continue
        position, parsed_any = end, True
        for analyzers in value.values() if isinstance(value, dict) else []:
            for analyzer, diagnostics in analyzers.items() if isinstance(analyzers, dict) else []:
                for d in diagnostics if isinstance(diagnostics, list) else []:
                    where = str(d.get("posn", ""))
                    match = re.match(r"(?:/work/)?(?P<path>[^:]+):(?P<line>\d+)", where)
                    if match is None:
                        continue
                    findings.append(
                        Finding.build(tool="go-vet", rule=str(analyzer), severity="warning", category="bugs",
                                      path=match.group("path"), line=int(match.group("line")),
                                      message=str(d.get("message", "")).splitlines()[0])
                    )  # fmt: skip
    for line in text.splitlines():
        compiled = _COMPILE.match(line.strip())
        if compiled and not line.lstrip().startswith(("{", '"')):
            findings.append(
                Finding.build(tool="go-vet", rule="compile", severity="error", category="types",
                              path=compiled.group("path"), line=int(compiled.group("line")),
                              message=compiled.group("message"))
            )  # fmt: skip
    parsed = result.exit_code == 0 or parsed_any or bool(findings)
    return _report("go-vet", result, argv, findings, parsed=parsed)


GO_VET = Tool("go-vet", "go", "bugs", ("go", "vet", "-json", "./..."), parse_go_vet)


# go test -json -----------------------------------------------------------------------------------------


def go_test_failures(output: str) -> list[str] | None:
    """Failing tests (package/Test) from `go test -json`; a package that fails without a test (it does not build)
    is named by itself. None when the output holds no test events at all: the run said nothing about the code."""
    failed: set[str] = set()
    events = 0
    for line in output.splitlines():
        if not line.startswith("{"):
            continue
        try:
            event: dict[str, Any] = json.loads(line)
        except ValueError:
            continue
        events += 1
        if event.get("Action") == "fail":
            package = str(event.get("Package", "?"))
            test = event.get("Test")
            failed.add(f"{package}/{test}" if test else f"{package} (package)")
    if not events:
        return None
    # A failing test fails its package too: the package is named only when no test of it explains the failure (it
    # did not build, or `go test`'s vet step failed).
    explained = {name.rsplit("/", 1)[0] for name in failed if not name.endswith(" (package)")}
    return sorted(n for n in failed if not (n.endswith(" (package)") and n.removesuffix(" (package)") in explained))


def go_test_count(output: str) -> int:
    """How many tests (top-level and subtests) `go test -json` reports running."""
    count = 0
    for line in output.splitlines():
        if line.startswith("{") and '"Action":"run"' in line.replace(" ", "") and '"Test"' in line:
            count += 1
    return count


class GoAdapter:
    name = "go"
    part_type = GoStack
    syntax = Syntax("Go", "//", "`//nolint`, `//lint:ignore`", (".go",))
    registries: tuple[str, ...] = GO_REGISTRIES
    capabilities = frozenset({"analyze", "test"})
    test_report = "go-test-json"

    def detect(self, repo: Path, rev: str, files: set[str], blind: list[str]) -> GoStack | None:
        if "go.mod" not in files:
            return None
        go_mod = _show(repo, rev, "go.mod")
        module = _MODULE.search(go_mod)
        nested = sorted(f for f in files if f.endswith("/go.mod"))
        if nested or "go.work" in files:
            blind.append(f"Go: {len(nested)} more module(s) below the root; only the root module is analyzed")
        golangci = any(f.startswith(".golangci.") for f in files)
        if golangci:
            blind.append("Go: the team configures golangci-lint; Unbidden runs go vet and the compiler only")
        if "go.sum" not in files and re.search(r"^require\b", go_mod, re.MULTILINE):
            blind.append("Go: go.mod requires modules but go.sum is not tracked; they cannot be verified")
        return GoStack(
            version=go_version(go_mod),
            module=module.group(1) if module else "",
            vendored="vendor/modules.txt" in files,
            has_tests=any(f.endswith("_test.go") for f in files),
            golangci=golangci,
        )

    def manifests(self, repo: Path, rev: str, part: GoStack) -> list[str]:
        from unbidden.observe.stack import tracked_files

        return ["go.mod"] + (["go.sum"] if not part.vendored and "go.sum" in tracked_files(repo, rev) else [])

    def generated(self, part: GoStack) -> dict[str, str]:
        return {}

    def dockerfile(self, part: GoStack, *, system_build_tools: bool, headers: tuple[str, ...]) -> str:
        download = "true" if part.vendored else "go mod download"
        return f"""FROM golang:{part.version}-bookworm
ENV GOTOOLCHAIN=local GOFLAGS=-mod=readonly GOPROXY=https://proxy.golang.org GOPATH=/go
WORKDIR /deps
COPY ctx/ /deps/
RUN {download} && chmod -R a+rX /go
"""

    def image(self, tag: str, part: GoStack, docker: str) -> DependencyImage:
        return DependencyImage(
            tag=tag,
            language="go",
            registries=list(self.registries),
            env={
                "PATH": "/usr/local/go/bin:/go/bin:/usr/local/bin:/usr/bin:/bin",
                "GOPATH": "/go",
                "GOMODCACHE": "/go/pkg/mod",
                "GOFLAGS": "-mod=vendor" if part.vendored else "-mod=readonly",
                "GOPROXY": "off",
                "GOSUMDB": "off",  # the sums were checked when the image downloaded the modules
                "GOTOOLCHAIN": "local",
                "GOCACHE": f"{CACHE}/cache",
                "GOTMPDIR": f"{CACHE}/tmp",
            },
            links={},
            setup=(f"mkdir -p {CACHE}/cache {CACHE}/tmp",),
        )

    def tools(self, part: GoStack) -> list[Tool]:
        return [GO_VET]

    def test_argv(self, part: GoStack) -> list[str] | None:
        return ["go", "test", "-json", "-count=1", "./..."] if part.has_tests else None


ADAPTER = register(GoAdapter())
