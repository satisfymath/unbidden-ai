"""`Brain.complete` is the only path to a model.

For every attempt: refuse if the kill switch is on; refuse a prompt that holds a secret; for a remote tier,
ask the policy engine and the egress gate, and record the attempt with its exact payload; call the provider;
validate the answer against the request; on a problem, explain it to the model and retry; account for
tokens, time and money whatever happens.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, NoReturn

from jsonschema import Draft202012Validator

from unbidden.brain.codeblocks import CodeBlockError, parse_files
from unbidden.brain.providers import LLMProvider, ProviderError, ProviderRejected, ProviderThrottled
from unbidden.brain.route_policy import NEVER_REMOTE, RouteDecision, decide_route
from unbidden.brain.spend import SpendLedger, SpendRefused, worst_cost
from unbidden.brain.tasks import task_for
from unbidden.config import Config, Route
from unbidden.contracts.common import Cost, utc_now
from unbidden.contracts.events import Event, EventType
from unbidden.contracts.guardian import ActionRequest, EgressAttempt, EgressVerdict, Mandate
from unbidden.contracts.llm import ContentLabel, LLMRequest, LLMResponse, Message, ModelRun, Tier, Usage
from unbidden.guardian.classify import Classification, classify
from unbidden.guardian.egress import evaluate_screenshots, evaluate_synthetic
from unbidden.guardian.killswitch import KillSwitch, checkpoint
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
    if request.expect_files:
        try:
            parse_files(response.content)
        except CodeBlockError as exc:
            return f"{exc}; answer with each file in a fenced block whose first line is `# file: <path>`"
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


# What one picture may cost at worst, in input tokens. Measured on Meta: a 800 x 480 screenshot and its prompt, 559
# tokens (docs/bench/multimodal/feasibility-1.json); a full viewport stays well under this.
IMAGE_TOKENS_WORST = 4000


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
        spend: SpendLedger | None = None,
    ) -> None:
        self.config = config
        self.providers = providers
        self.store = store
        self.mandate = mandate
        self.policy = PolicyEngine(mandate)
        self.identifiers = identifiers or SensitiveTermIndex()
        self.killswitch = killswitch
        self.spend = spend or SpendLedger()  # never optional: every remote call passes the machine's budget
        self.repo_public = False  # set by the runtime only when GitHub confirms it; unknown means private
        self.served_by: dict[str, ModelRun] = {}  # purpose -> the last run that answered it, for honest attribution

    def route(self, tier: Tier) -> tuple[Route, LLMProvider]:
        route = self.config.routing.get(tier)
        if route is None:
            raise BrainError(f"no route configured for tier {tier}")
        provider = self.providers.get(route.provider)
        if provider is None:
            raise BrainError(f"provider {route.provider!r} for tier {tier} is not available")
        return route, provider

    def decide(self, request: LLMRequest) -> tuple[RouteDecision, Classification]:
        """Which model serves this request, from the profile, the task and what the request holds."""
        classification = classify(request.messages, repo_public=self.repo_public)
        models = self.mandate.models
        route = self.config.routing.get(Tier.CODE)
        provider = self.providers.get(route.provider) if route else None
        remote_available = provider is not None and bool(getattr(provider, "has_key", lambda: True)())
        decision = decide_route(
            models.profile,
            task_for(request.purpose),
            classification.label,
            private_code_to_frontier=models.private_code_to_frontier == "allow",
            remote_available=remote_available,
        )
        return decision, classification

    async def complete(self, request: LLMRequest, *, identifiers: SensitiveTermIndex | None = None) -> LLMResponse:
        """`identifiers` adds names that must not leave the machine on this call, on top of the workspace's."""
        self._guard_prompt(request)
        decision, classification = self.decide(request)
        if self.mandate.models.local_inference == "deny":
            if not decision.tier.remote:
                why = f"the mandate denies local inference, and this call may not go remote: {decision.reason}"
                self.store.append_event(
                    Event(type=EventType.POLICY_DENIED, actor=ACTOR, correlation_id=request.correlation_id,
                          payload={"rule": "local_inference", "purpose": request.purpose, "why": why})
                )  # fmt: skip
                raise PolicyDenied(why)
            decision = replace(decision, fallback=None if decision.fallback is Tier.LOCAL else decision.fallback)
        tiers = [decision.tier, *([decision.fallback] if decision.fallback else [])]
        last: Exception | None = None
        for i, tier in enumerate(tiers):
            if i > 0:
                assert last is not None
                to_local = not tier.remote and tiers[0].remote
                allowed = not to_local or self.mandate.models.local_fallback == "allow"
                self.store.append_event(
                    Event(
                        type=EventType.MODEL_FALLBACK,
                        actor=ACTOR,
                        correlation_id=request.correlation_id,
                        payload={"purpose": request.purpose, "from": tiers[0].value, "to": tier.value,
                                 "cause": f"{type(last).__name__}: {str(last)[:300]}", "taken": allowed},
                    )
                )  # fmt: skip
                if not allowed:
                    break
            try:
                return await self._complete_on(tier, request, identifiers, decision, classification)
            except (ModelFailed, ProviderError, EgressBlocked, SpendLimitReached, PolicyDenied) as exc:
                last = exc
        assert last is not None
        raise last

    async def _complete_on(
        self,
        tier: Tier,
        request: LLMRequest,
        identifiers: SensitiveTermIndex | None,
        decision: RouteDecision,
        classification: Classification,
    ) -> LLMResponse:
        route, provider = self.route(tier)
        think = route.think_schema_only if request.schema_only else route.think
        budget = route.think_budget if think not in (None, "off") else 0
        max_tokens = min(request.max_tokens + budget, route.max_tokens_cap)
        routed = request.model_copy(update={"tier": tier})
        current = routed
        problem = "no attempt was made"
        why = f"{decision.reason}; label {classification.label.value}"
        for attempt in range(1, self.config.brain.max_repairs + 2):
            if self.killswitch is not None and self.killswitch.engaged:
                raise KillSwitchEngaged("the kill switch is engaged")
            checkpoint("model call")
            sized = current.model_copy(update={"max_tokens": max_tokens})
            egress_id, spend_id = (
                self._gate(sized, route, provider, identifiers, classification, attempt)
                if tier.remote
                else (None, None)
            )
            self._check_local(routed)
            try:
                response = await provider.chat(sized, model=route.model, think=think)
            except Exception as exc:
                self._record(
                    sized, route, provider, attempt, None, f"provider error: {exc}", egress_id, sent=False, why=why
                )
                self._settle(spend_id, route, None, exc)
                raise
            problem_or_none = check_output(request, response)
            self._record(sized, route, provider, attempt, response, problem_or_none, egress_id, sent=True, why=why)
            self._settle(spend_id, route, response, None)
            if problem_or_none is None:
                return response
            problem = problem_or_none
            if response.truncated:
                max_tokens = min(max_tokens * 2, route.max_tokens_cap)
            answer_source = "synthetic" if classification.label is ContentLabel.SYNTHETIC else None
            current = current.model_copy(
                update={
                    "messages": [
                        *current.messages,
                        Message(role="assistant", content=response.content or "(no answer)", source=answer_source),
                        Message(role="user", content=f"Your previous answer was rejected: {problem}.", source="prompt"),
                    ]
                }
            )
        raise ModelFailed(request.purpose, problem)

    def author(self, purpose: str) -> str:
        """Who wrote the last accepted answer for a purpose: 'frontier' when a remote model did, else 'model'."""
        run = self.served_by.get(purpose)
        return "frontier" if run is not None and run.tier.remote else "model"

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
        if any(m.images for m in request.messages):
            raise ModelFailed(request.purpose, "the local route reads no images")
        verdict = self.policy.evaluate(ActionRequest(capability="model.local", purpose=request.purpose))
        if not verdict.allowed:
            raise PolicyDenied("; ".join(verdict.reasons))

    def _gate(
        self,
        request: LLMRequest,
        route: Route,
        provider: LLMProvider,
        extra: SensitiveTermIndex | None,
        classification: Classification | None = None,
        try_number: int = 1,
    ) -> tuple[str, str]:
        """Policy, the contributor rule, both spend limits, then the egress gate; returns the egress attempt and the
        spend reservation of a call allowed to leave."""
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
        if route.model.endswith("-contributor") and self.config.brain.contributor_models != "allow":
            # Contributor variants are cheaper because the provider may train on what they receive: other terms,
            # chosen by a person in the config, never by a fallback.
            self._deny(request, "contributor_model", f"{route.model} has contributor data terms; not allowed here")
        spent = self.month_remote_spend()
        cap = self.mandate.business_constraints.maximum_monthly_spend_usd
        if spent >= cap:
            raise SpendLimitReached(f"remote spend this month is US${spent:.2f}, at the US${cap:.2f} cap")
        payload = _payload(request)
        price = self.config.prices.models.get(route.model)
        if price is None:
            self._deny(request, "spend", f"no price is known for {route.model}, so its cost cannot be bounded")
        images = [i for m in request.messages for i in m.images]
        est = worst_cost(
            len(payload.encode()) + IMAGE_TOKENS_WORST * len(images),
            request.max_tokens,
            price.input_per_mtok,
            price.output_per_mtok,
        )
        try:
            spend_id = self.spend.reserve(
                est_usd=est,
                workspace=self.mandate.workspace,
                purpose=request.purpose,
                provider=provider.name,
                model=route.model,
                attempt=try_number,
                correlation_id=request.correlation_id,
            )
        except SpendRefused as exc:
            self._deny(request, "spend", str(exc), raise_as=SpendLimitReached)
        index = self.identifiers
        if extra is not None and len(extra):
            index = SensitiveTermIndex([*self.identifiers.terms, *extra.terms])
        label = classification.label if classification else ContentLabel.SYNTHETIC
        # Real names are expected in public code (and in private code a person allowed out); everything else must
        # carry none. Secrets and production data are refused here again, whatever the route decided.
        names = index if label in (ContentLabel.SYNTHETIC, ContentLabel.INSTRUCTIONS) else SensitiveTermIndex()
        egress = evaluate_synthetic(self.mandate, host, payload, names)
        if images:
            # Pictures leave only where a person let screenshots leave, under the policy's own rule for them.
            shots = evaluate_screenshots(self.mandate, host, [i.data() for i in images], payload)
            rule = self.policy.evaluate(
                ActionRequest(capability="model.remote.screenshot", purpose=request.purpose, destinations=[host])
            )
            reasons = [*egress.reasons, *shots.reasons, *([] if rule.allowed else rule.reasons)]
            egress = egress.model_copy(
                update={"allowed": not reasons, "reasons": reasons, "kind": "screenshots",
                        "payload_bytes": egress.payload_bytes + sum(len(i.data()) for i in images)}
            )  # fmt: skip
        if label in NEVER_REMOTE:
            reasons = [*egress.reasons, f"{label.value} never leaves this machine"]
            egress = egress.model_copy(update={"allowed": False, "reasons": reasons})
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
            self.spend.release(spend_id, "blocked by the egress gate")
            raise EgressBlocked(egress)
        return attempt.id, spend_id

    def _deny(
        self, request: LLMRequest, rule: str, reason: str, *, raise_as: type[BrainError] = PolicyDenied
    ) -> NoReturn:
        self.store.append_event(
            Event(
                type=EventType.POLICY_DENIED,
                actor=ACTOR,
                correlation_id=request.correlation_id,
                payload={"rule": rule, "reasons": [reason], "purpose": request.purpose},
            )
        )
        raise raise_as(reason)

    def _settle(self, spend_id: str | None, route: Route, response: LLMResponse | None, exc: Exception | None) -> None:
        if spend_id is None:
            return
        if response is not None:
            usage = response.usage
            reported = usage.prompt_tokens > 0 or usage.completion_tokens > 0
            self.spend.settle(
                spend_id,
                # Without reported usage the worst cost stands: an answer was generated and billed somehow.
                usd=self._cost(route, response, True).usd_remote if reported else None,
                tokens_in=usage.prompt_tokens,
                tokens_out=usage.completion_tokens,
                usage_reported=reported,
            )
        elif isinstance(exc, ProviderThrottled | ProviderRejected):
            # Refused before any generation (429, 400): not billed.
            self.spend.settle(spend_id, usd=0.0, usage_reported=False, status="failed", note=str(exc)[:300])
        else:
            # A timeout or a 5xx may have been billed; keep the worst cost.
            self.spend.settle(spend_id, usd=None, usage_reported=False, status="failed", note=str(exc)[:300])

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
        why: str | None = None,
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
            route_reason=why,
        )
        self.store.put("model_runs", run)
        if run.ok:
            self.served_by[run.purpose] = run
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
