"""`Brain.complete` is the only path to a model.

For every attempt: refuse if the kill switch is on; refuse a prompt that holds a secret; for a remote tier,
ask the policy engine and the egress gate, and record the attempt with its exact payload; call the provider;
validate the answer against the request; on a problem, explain it to the model and retry; account for
tokens, time and money whatever happens.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from jsonschema import Draft202012Validator

from unbidden.brain.providers import LLMProvider
from unbidden.config import Config, Route
from unbidden.contracts.common import Cost, utc_now
from unbidden.contracts.events import Event, EventType
from unbidden.contracts.guardian import ActionRequest, EgressAttempt, EgressVerdict, Mandate
from unbidden.contracts.llm import LLMRequest, LLMResponse, Message, ModelRun, Tier, Usage
from unbidden.guardian.egress import evaluate_synthetic
from unbidden.guardian.killswitch import KillSwitch
from unbidden.guardian.policy import PolicyEngine
from unbidden.guardian.scanner import SensitiveTermIndex, scan_many, secret_hits
from unbidden.store import Store

ACTOR = "brain"


class BrainError(RuntimeError):
    pass


class KillSwitchEngaged(BrainError):
    pass


class SecretInPrompt(BrainError):
    pass


class PolicyDenied(BrainError):
    pass


class EgressBlocked(BrainError):
    def __init__(self, verdict: EgressVerdict) -> None:
        super().__init__("; ".join(verdict.reasons))
        self.verdict = verdict


class SpendLimitReached(BrainError):
    pass


class ModelFailed(BrainError):
    def __init__(self, purpose: str, problem: str) -> None:
        super().__init__(f"{purpose}: {problem}")
        self.problem = problem


_FENCED_JSON = re.compile(r"^\s*```(?:json)?\s*(?P<body>.*?)\s*```\s*$", re.DOTALL)


def parse_json(content: str) -> Any:
    match = _FENCED_JSON.match(content)
    return json.loads(match.group("body") if match else content)


def check_output(request: LLMRequest, response: LLMResponse) -> str | None:
    """Why an answer cannot be used, or None. The message is written for the model to fix it."""
    if response.truncated:
        return "your answer was cut off at the token limit; answer again, more briefly"
    tools = {t.name: t for t in request.tools}
    if request.tool_choice == "required" and not response.tool_calls:
        return f"you must call exactly one of the tools: {', '.join(sorted(tools))}"
    for call in response.tool_calls:
        tool = tools.get(call.name)
        if tool is None:
            return f"there is no tool named {call.name!r}; the tools are: {', '.join(sorted(tools))}"
        errors = sorted(Draft202012Validator(tool.parameters).iter_errors(call.arguments), key=str)
        if errors:
            return f"the arguments of {call.name} do not match its schema: {errors[0].message}"
    if request.response_schema is not None and not response.tool_calls:
        try:
            value = parse_json(response.content)
        except json.JSONDecodeError as exc:
            return f"your answer is not valid JSON ({exc.msg}); answer with JSON only"
        errors = sorted(Draft202012Validator(request.response_schema).iter_errors(value), key=str)
        if errors:
            where = "/".join(str(p) for p in errors[0].absolute_path) or "the root"
            return f"your JSON does not match the schema at {where}: {errors[0].message}"
    return None


def _payload(request: LLMRequest) -> str:
    """What would leave the machine, serialized exactly as it is judged and recorded."""
    return json.dumps(
        {
            "messages": [m.model_dump(mode="json", exclude_defaults=True) for m in request.messages],
            "tools": [t.model_dump(mode="json") for t in request.tools],
            "response_schema": request.response_schema,
        },
        sort_keys=True,
        ensure_ascii=False,
    )


class Brain:
    def __init__(
        self,
        config: Config,
        providers: dict[str, LLMProvider],
        store: Store,
        mandate: Mandate,
        *,
        identifiers: SensitiveTermIndex | None = None,
        killswitch: KillSwitch | None = None,
    ) -> None:
        self.config = config
        self.providers = providers
        self.store = store
        self.mandate = mandate
        self.policy = PolicyEngine(mandate)
        self.identifiers = identifiers or SensitiveTermIndex()
        self.killswitch = killswitch

    def route(self, tier: Tier) -> tuple[Route, LLMProvider]:
        route = self.config.routing.get(tier)
        if route is None:
            raise BrainError(f"no route configured for tier {tier}")
        provider = self.providers.get(route.provider)
        if provider is None:
            raise BrainError(f"provider {route.provider!r} for tier {tier} is not available")
        return route, provider

    async def complete(self, request: LLMRequest) -> LLMResponse:
        route, provider = self.route(request.tier)
        self._guard_prompt(request)
        think = route.think_schema_only if request.schema_only else route.think
        budget = route.think_budget if think not in (None, "off") else 0
        max_tokens = min(request.max_tokens + budget, route.max_tokens_cap)
        current = request
        problem = "no attempt was made"
        for attempt in range(1, self.config.brain.max_repairs + 2):
            if self.killswitch is not None and self.killswitch.engaged:
                raise KillSwitchEngaged("the kill switch is engaged")
            sized = current.model_copy(update={"max_tokens": max_tokens})
            egress_id = self._gate(sized, route, provider) if request.tier.remote else None
            self._check_local(request)
            try:
                response = await provider.chat(sized, model=route.model, think=think)
            except Exception as exc:
                self._record(sized, route, provider, attempt, None, f"provider error: {exc}", egress_id, sent=False)
                raise
            problem_or_none = check_output(request, response)
            self._record(sized, route, provider, attempt, response, problem_or_none, egress_id, sent=True)
            if problem_or_none is None:
                return response
            problem = problem_or_none
            if response.truncated:
                max_tokens = min(max_tokens * 2, route.max_tokens_cap)
            current = current.model_copy(
                update={
                    "messages": [
                        *current.messages,
                        Message(role="assistant", content=response.content or "(no answer)"),
                        Message(role="user", content=f"Your previous answer was rejected: {problem}."),
                    ]
                }
            )
        raise ModelFailed(request.purpose, problem)

    async def complete_json(self, request: LLMRequest) -> tuple[Any, LLMResponse]:
        if request.response_schema is None:
            raise BrainError("complete_json needs a response_schema")
        response = await self.complete(request)
        return parse_json(response.content), response

    # Guards -----------------------------------------------------------------------------------------------

    def _guard_prompt(self, request: LLMRequest) -> None:
        texts = [m.content for m in request.messages]
        texts += [json.dumps(c.arguments) for m in request.messages for c in m.tool_calls]
        texts += [json.dumps(t.parameters) + t.description for t in request.tools]
        if request.response_schema is not None:
            texts.append(json.dumps(request.response_schema))
        hits = secret_hits(scan_many(texts))
        if hits:
            kinds = sorted({h.kind for h in hits})
            self.store.append_event(
                Event(
                    type=EventType.POLICY_DENIED,
                    actor=ACTOR,
                    correlation_id=request.correlation_id,
                    payload={"rule": "secret_in_prompt", "purpose": request.purpose, "kinds": kinds},
                )
            )
            raise SecretInPrompt(f"{request.purpose}: prompt contains {', '.join(kinds)}")

    def _check_local(self, request: LLMRequest) -> None:
        if request.tier.remote:
            return
        verdict = self.policy.evaluate(ActionRequest(capability="model.local", purpose=request.purpose))
        if not verdict.allowed:
            raise PolicyDenied("; ".join(verdict.reasons))

    def _gate(self, request: LLMRequest, route: Route, provider: LLMProvider) -> str:
        host = getattr(provider, "host", provider.name)
        verdict = self.policy.evaluate(
            ActionRequest(capability="model.remote.synthetic", purpose=request.purpose, destinations=[host])
        )
        if not verdict.allowed:
            self.store.append_event(
                Event(
                    type=EventType.POLICY_DENIED,
                    actor=ACTOR,
                    correlation_id=request.correlation_id,
                    payload={"rule": verdict.rule, "reasons": verdict.reasons, "purpose": request.purpose},
                )
            )
            raise PolicyDenied("; ".join(verdict.reasons))
        spent = self.month_remote_spend()
        cap = self.mandate.business_constraints.maximum_monthly_spend_usd
        if spent >= cap:
            raise SpendLimitReached(f"remote spend this month is US${spent:.2f}, at the US${cap:.2f} cap")
        payload = _payload(request)
        egress = evaluate_synthetic(self.mandate, host, payload, self.identifiers)
        attempt = EgressAttempt(
            status="allowed_pending" if egress.allowed else "blocked",
            purpose=request.purpose,
            destination=host,
            provider=provider.name,
            model=route.model,
            verdict=egress,
            # A blocked payload is kept only by its fingerprint: it may hold what must not be copied around.
            payload=payload if egress.allowed else f"sha256:{egress.payload_sha256}",
        )
        self.store.put("egress", attempt)
        self.store.append_event(
            Event(
                type=EventType.EGRESS_ALLOWED if egress.allowed else EventType.EGRESS_BLOCKED,
                actor=ACTOR,
                entity_id=attempt.id,
                correlation_id=request.correlation_id,
                payload={
                    "purpose": request.purpose,
                    "destination": host,
                    "bytes": egress.payload_bytes,
                    "sha256": egress.payload_sha256,
                    "reasons": egress.reasons,
                    "matched": egress.matched,
                },
            )
        )
        if not egress.allowed:
            raise EgressBlocked(egress)
        return attempt.id

    # Accounting -------------------------------------------------------------------------------------------

    def _cost(self, route: Route, response: LLMResponse | None, remote: bool) -> Cost:
        if response is None:
            return Cost()
        usage = response.usage
        if remote:
            price = self.config.prices.models.get(route.model)
            usd = 0.0
            if price is not None:
                usd = (
                    usage.prompt_tokens * price.input_per_mtok + usage.completion_tokens * price.output_per_mtok
                ) / 1e6
            return Cost(tokens_in=usage.prompt_tokens, tokens_out=usage.completion_tokens, usd_remote=usd)
        return Cost(
            tokens_in=usage.prompt_tokens,
            tokens_out=usage.completion_tokens,
            compute_seconds=usage.duration_s,
            usd_local=usage.duration_s / 3600 * self.config.prices.usd_per_local_compute_hour,
        )

    def _record(
        self,
        request: LLMRequest,
        route: Route,
        provider: LLMProvider,
        attempt: int,
        response: LLMResponse | None,
        problem: str | None,
        egress_id: str | None,
        *,
        sent: bool,
    ) -> None:
        run = ModelRun(
            purpose=request.purpose,
            tier=request.tier,
            provider=provider.name,
            model=route.model,
            attempt=attempt,
            ok=response is not None and problem is None,
            problem=problem,
            prompt_sha256=request.prompt_sha256,
            egress_attempt_id=egress_id,
            usage=response.usage if response is not None else Usage(),
            cost=self._cost(route, response, request.tier.remote),
            correlation_id=request.correlation_id,
        )
        self.store.put("model_runs", run)
        if egress_id is not None:
            attempt_doc = self.store.get("egress", egress_id, EgressAttempt)
            if attempt_doc is not None:
                attempt_doc.status = "allowed_sent" if sent else "failed"
                self.store.put("egress", attempt_doc)
        self.store.append_event(
            Event(
                type=EventType.MODEL_CALLED,
                actor=ACTOR,
                entity_id=run.id,
                correlation_id=request.correlation_id,
                payload={
                    "purpose": run.purpose,
                    "tier": run.tier.value,
                    "model": run.model,
                    "attempt": attempt,
                    "ok": run.ok,
                    "problem": problem,
                    "tokens_in": run.cost.tokens_in,
                    "tokens_out": run.cost.tokens_out,
                    "usd": round(run.cost.usd, 6),
                },
            )
        )

    def month_remote_spend(self, *, now: datetime | None = None) -> float:
        moment = (now or utc_now()).astimezone(UTC)
        return sum(
            run.cost.usd_remote
            for run in self.store.list("model_runs", ModelRun)
            if run.created_at.year == moment.year and run.created_at.month == moment.month
        )
