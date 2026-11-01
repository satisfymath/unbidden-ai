"""When a green CI may decline Unbidden's findings as its own environment, and when it may not.

The false declines below were reproduced on the earlier rule (`tool in ci_commands` as a substring, and any green):
each must now be decided on its own. The correct decline must stay one. A CI that covers the same files with the
same tool but a different version or configuration is a discrepancy: the Director waits, it does not decline.
"""

from __future__ import annotations

import pytest

from unbidden.contracts.common import EvidenceRef
from unbidden.contracts.guardian import Mandate
from unbidden.contracts.opportunity import ActionKind, Opportunity
from unbidden.director.decide import Context, decide
from unbidden.observe.ci import DIFFERS, SAME, UNRELATED, environment_equivalence, runs_tool

pytestmark = pytest.mark.unit


def finding(tool: str, path: str, category: str = "bugs") -> Opportunity:
    return Opportunity(
        source=tool, category=category, title="t", summary="s", dedup_key=f"{tool}:{path}",
        evidence=[EvidenceRef(kind="file", locator=path)], details={"tool": tool, "paths": [path]},
    )  # fmt: skip


def decided(opp: Opportunity, mandate: Mandate, commands: str, tool_status: dict[str, str]) -> ActionKind:
    ctx = Context(open_pull_requests=0, attempts=0, ci_commands=commands, ci_status="green", tool_status=tool_status)
    return decide(opp, mandate, ctx).chosen


FALSE_DECLINES = [
    # a: the CI checks src/ only; the finding is in scripts/.
    ("ruff", "scripts/x.py", "ruff check src/", {"ruff": "green"}),
    # b: another config, rules and directory.
    ("eslint", "web/a.ts", "npx eslint -c .eslintrc.ci.json --rule no-unused-vars:off app/", {"eslint": "green"}),
    # c: tox runs pytest only; [tool.mypy] in pyproject configures mypy, nothing runs it.
    ("mypy", "a.py", "uv run tox -e py312\n[testenv]\ncommands = pytest\n[tool.mypy]\nstrict = true", {}),
    # d: "tsc" inside "tsconfig".
    ("tsc", "a.ts", "cp tsconfig.json dist/\nnpm test", {}),
    # e: the CI formats with ruff, it does not lint.
    ("ruff", "a.py", "ruff format --check .", {"ruff": "green"}),
    # f: the mypy job was cancelled: its verdict is unknown, not green.
    ("mypy", "a.py", "mypy .", {"mypy": "unknown"}),
    # g: only an unrelated job has finished; the one that runs mypy has not.
    ("mypy", "a.py", "mypy .", {"mypy": "pending"}),
]


@pytest.mark.parametrize(("tool", "path", "commands", "status"), FALSE_DECLINES)
def test_a_green_ci_that_does_not_speak_to_the_finding_does_not_decline_it(
    tool: str, path: str, commands: str, status: dict[str, str], mandate: Mandate
) -> None:
    assert decided(finding(tool, path), mandate, commands, status) is not ActionKind.DECLINE


def test_the_same_tool_run_the_same_way_on_the_same_files_does_decline(mandate: Mandate) -> None:
    assert decided(finding("mypy", "a.py", "types"), mandate, "mypy .", {"mypy": "green"}) is ActionKind.DECLINE
    assert environment_equivalence("mypy .", "mypy", ["a.py"], source="project", own_rules=False)[0] == SAME


def test_unbiddens_own_rules_are_never_the_teams_environment(mandate: Mandate) -> None:
    # taskuary's real crash came from these rules: a green ruff with the team's rules says nothing about them.
    relation, _ = environment_equivalence("ruff check .", "ruff", ["a.py"], source="unbidden", own_rules=True)
    assert relation == UNRELATED
    assert (
        decided(finding("ruff-baseline", "a.py"), mandate, "ruff check .", {"ruff": "green"}) is not ActionKind.DECLINE
    )


@pytest.mark.parametrize(
    ("tool", "commands", "source"),
    [
        ("pyright", "pyright", "unbidden"),  # Unbidden's pinned pyright, not the project's
        ("tsc", "tsc -p tsconfig.build.json", "project"),  # the same files, another configuration
    ],
)
def test_the_same_files_checked_differently_wait_to_be_investigated(
    tool: str, commands: str, source: str, mandate: Mandate
) -> None:
    path = "a.ts" if tool == "tsc" else "a.py"
    assert environment_equivalence(commands, tool, [path], source=source, own_rules=False)[0] == DIFFERS
    opp = finding(tool, path, "types")
    ctx = Context(
        open_pull_requests=0, attempts=0, ci_commands=commands, ci_status="green", tool_status={tool: "green"}
    )
    chosen = decide(opp, mandate, ctx)
    assert chosen.chosen is ActionKind.WAIT and "investigated first" in chosen.reason


def test_invocations_are_read_as_argv() -> None:
    assert runs_tool("python -m mypy --strict pkg", "mypy")
    assert runs_tool("cd web && npx tsc -p tsconfig.build.json", "tsc")
    assert runs_tool("[testenv:types]\ncommands = mypy src", "mypy")
    assert not runs_tool("tox -e mypy", "mypy")
    assert not runs_tool("[tool.mypy]", "mypy")
    assert not runs_tool("ruff format --check .", "ruff")


def test_a_tool_run_by_its_package_name_and_pinned_version_is_recognized_and_differs() -> None:
    # Found on dev (compass-calendar, v5): `bunx typescript@7.0.2` is tsc, at a version the step pins itself.
    commands = "bunx typescript@7.0.2 -b tsconfig.typecheck.json --noemit"
    assert runs_tool(commands, "tsc")
    relation, why = environment_equivalence(commands, "tsc", ["src/a.ts"], source="project", own_rules=False)
    assert relation == DIFFERS and "7.0.2" in why
    assert runs_tool("pnpm dlx @biomejs/biome@1.9.4 check .", "biome")
    assert (
        environment_equivalence("uvx ruff==0.6.0 check .", "ruff", ["a.py"], source="project", own_rules=False)[0]
        == DIFFERS
    )
    assert not runs_tool("npm install typescript@5", "tsc")  # installing it is not running it
