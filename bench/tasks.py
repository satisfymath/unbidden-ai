"""Benchmark tasks shaped like the product's real calls. Each has a strict contract and a semantic check."""

from __future__ import annotations

import ast
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from unbidden.brain.codeblocks import CodeBlockError, parse_files
from unbidden.brain.router import parse_json
from unbidden.contracts.llm import LLMRequest, LLMResponse, Message, Tier, ToolSpec
from unbidden.guardian.scanner import SensitiveTermIndex, scan

Check = Callable[[LLMResponse], str | None]


@dataclass
class Task:
    name: str
    kind: str  # schema | tool | code
    system: str
    user: str
    check: Check
    schema: dict[str, Any] | None = None
    tools: list[ToolSpec] = field(default_factory=list[ToolSpec])
    max_tokens: int = 800
    local_only: bool = False  # holds private names: it may only ever run on the local tier

    def request(self, tier: Tier) -> LLMRequest:
        return LLMRequest(
            purpose=f"bench.{self.name}",
            tier=tier,
            messages=[Message(role="system", content=self.system), Message(role="user", content=self.user)],
            response_schema=self.schema,
            tools=self.tools,
            tool_choice="required" if self.tools else "auto",
            max_tokens=self.max_tokens,
        )


def _json_check(predicate: Callable[[Any], str | None]) -> Check:
    def check(response: LLMResponse) -> str | None:
        return predicate(parse_json(response.content))

    return check


# 1. Classify an analyzer finding --------------------------------------------------------------------------

CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": ["types", "lint", "format", "security", "tests"]},
        "fixable_without_behavior_change": {"type": "boolean"},
        "reason": {"type": "string", "maxLength": 400},
    },
    "required": ["category", "fixable_without_behavior_change", "reason"],
    "additionalProperties": False,
}

classify = Task(
    name="classify_finding",
    kind="schema",
    system="You triage findings from developer tools. Answer with JSON only, matching the schema below.\n"
    "category: types = type checker errors; lint = linter rules; format = whitespace/formatting; "
    "security = vulnerable dependencies or unsafe code; tests = failing tests.\n"
    f"Schema: {CLASSIFY_SCHEMA}",
    user="Tool: tsc\nRule: TS2345\nFile: src/cart/total.ts:14\n"
    "Message: Argument of type 'string | undefined' is not assignable to parameter of type 'string'.",
    schema=CLASSIFY_SCHEMA,
    check=_json_check(lambda v: None if v["category"] == "types" else f"category {v['category']}, expected types"),
)

# 2. Decide an action from evidence -------------------------------------------------------------------------

DECIDE_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["propose_change", "run_experiment", "wait", "decline"]},
        "reason": {"type": "string", "maxLength": 400},
    },
    "required": ["action", "reason"],
    "additionalProperties": False,
}

decide = Task(
    name="decide_action",
    kind="schema",
    system="You choose the next action for an improvement opportunity. Answer with JSON only.\n"
    "propose_change: evidence level is 4 or more and no test regressed. run_experiment: nothing measured yet. "
    "wait: blocked by something outside your control. decline: the change is not worth it or would be unsafe.\n"
    f"Schema: {DECIDE_SCHEMA}",
    user="Opportunity: 3 type errors in src/cart/total.ts. Experiment done: the candidate removes all 3 errors, "
    "introduces none, and the test suite passed 3 of 3 rounds on both sides. Evidence level: 4.",
    schema=DECIDE_SCHEMA,
    check=_json_check(lambda v: None if v["action"] == "propose_change" else f"action {v['action']}"),
)

# 3. Rewrite a private problem as a synthetic task (the privacy bridge) -----------------------------------

PRIVATE_IDS = ["acme_orders", "order_line_items", "fetchCustomerLedger", "billing-gateway", "ledger_entries"]

SYNTH_SCHEMA = {
    "type": "object",
    "properties": {
        "synthetic_task": {"type": "string", "minLength": 80, "maxLength": 3000},
        "renames": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"real": {"type": "string"}, "synthetic": {"type": "string"}},
                "required": ["real", "synthetic"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["synthetic_task", "renames"],
    "additionalProperties": False,
}


def _synth_check(response: LLMResponse) -> str | None:
    value = parse_json(response.content)
    leaks = scan(value["synthetic_task"], SensitiveTermIndex(PRIVATE_IDS))
    if leaks:
        return f"synthetic task still names {sorted({h.kind for h in leaks})}"
    if "N+1" not in value["synthetic_task"] and "per" not in value["synthetic_task"].lower():
        return "the synthetic task lost the problem (one query per row)"
    return None


synthesize = Task(
    name="synthesize_task",
    kind="schema",
    system="You protect private code. Rewrite the problem below as a self-contained synthetic programming task "
    "that keeps the technical problem exactly but replaces every real name (tables, functions, services, "
    "paths) with neutral invented ones. List every rename. Answer with JSON only.\n"
    f"Schema: {SYNTH_SCHEMA}",
    user="In billing-gateway, fetchCustomerLedger(customerId) loads acme_orders for the customer, then for each "
    "order runs a separate query on order_line_items, and then another on ledger_entries. A customer with 300 "
    "orders triggers 601 queries (an N+1 pattern). Write a version that loads the same data with a constant "
    "number of queries.",
    schema=SYNTH_SCHEMA,
    max_tokens=1200,
    local_only=True,
    check=_synth_check,
)

# 4. Call a tool ------------------------------------------------------------------------------------------

READ = ToolSpec(
    name="read_file",
    description="Read a file of the repository.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string"}, "start_line": {"type": "integer", "minimum": 1}},
        "required": ["path"],
        "additionalProperties": False,
    },
)
FINISH = ToolSpec(
    name="finish",
    description="Stop when you know the answer.",
    parameters={
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
        "additionalProperties": False,
    },
)


def _tool_check(response: LLMResponse) -> str | None:
    call = response.tool_calls[0]
    if call.name != "read_file" or "total.ts" not in str(call.arguments.get("path", "")):
        return f"expected read_file on src/cart/total.ts, got {call.name}({call.arguments})"
    return None


tool_call = Task(
    name="tool_call",
    kind="tool",
    system="You investigate a type error in a repository using the tools. Call exactly one tool.",
    user="tsc reports TS2345 at src/cart/total.ts:14. You have not read any file yet. What do you do first?",
    tools=[READ, FINISH],
    check=_tool_check,
)

# 5. Write a fix as a fenced file -------------------------------------------------------------------------

BROKEN_PY = """def median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle]
"""


_MEDIAN_TESTS = """
cases = [([3.0, 1.0, 2.0], 2.0), ([4.0, 1.0, 3.0, 2.0], 2.5), ([5.0], 5.0)]
for values, expected in cases:
    got = median(list(values))
    assert got == expected, f"median({values}) = {got}, expected {expected}"
"""


def _fix_check(response: LLMResponse) -> str | None:
    try:
        files = parse_files(response.content)
    except CodeBlockError as exc:
        return str(exc)
    source = files.get("stats/median.py")
    if source is None:
        return f"expected stats/median.py, got {sorted(files)}"
    try:
        ast.parse(source)
    except SyntaxError as exc:
        return f"syntax error: {exc}"
    # Model-written code never runs on the host: an offline, throwaway container judges it.
    run = subprocess.run(
        ["docker", "run", "--rm", "-i", "--network", "none", "--memory", "256m", "python:3.12-slim", "python", "-"],
        input=source + _MEDIAN_TESTS,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if run.returncode != 0:
        return (run.stderr.strip().splitlines() or ["tests failed"])[-1][:300]
    return None


fix_code = Task(
    name="fix_code",
    kind="code",
    system="You fix bugs with the smallest change. Reply with the complete corrected file in one fenced block "
    "whose first line is a comment '# file: <path>'. No explanation.",
    user="The test `assert median([4.0, 1.0, 3.0, 2.0]) == 2.5` fails. File stats/median.py:\n\n"
    f"```python\n{BROKEN_PY}```",
    max_tokens=600,
    check=_fix_check,
)

TASKS = [classify, decide, synthesize, tool_call, fix_code]
