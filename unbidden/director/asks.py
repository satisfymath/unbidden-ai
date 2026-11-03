"""Questions for the person: opened where the agent stops, answered from the app, the dashboard or the CLI, and
closed on their own when the matter is settled another way.

Each producer builds one `Ask` with the options a person really has; `answer` applies the chosen one with the same
module the CLI command uses (`operate/decisions`, `operate/holds`, `setup/keycheck`, the mandate editor), so the
record, the audit and the events are the ones they would be. `reconcile` runs every tick of the loop and withdraws
an ask whose subject was resolved elsewhere."""

from __future__ import annotations

import getpass
import re
from datetime import timedelta
from typing import Any

from unbidden.contracts.ask import Ask, AskOption
from unbidden.contracts.events import Event, EventType
from unbidden.contracts.experiment import Proposal, ProposalStatus
from unbidden.contracts.guardian import Hold
from unbidden.store import Store

COLLECTION = "asks"
ACTOR = "director"


# --- the record -----------------------------------------------------------------------------------------------------


def open_asks(store: Store) -> list[Ask]:
    return sorted((a for a in store.list(COLLECTION, Ask) if a.status == "open"), key=lambda a: a.created_at)


def find_open(store: Store, dedup_key: str) -> Ask | None:
    return next((a for a in open_asks(store) if a.dedup_key == dedup_key), None)


def open_ask(store: Store, ask: Ask) -> Ask:
    """Keep one open ask per subject; the first stays (its options are the same), the event is written once."""
    existing = find_open(store, ask.dedup_key)
    if existing is not None:
        return existing
    store.put(COLLECTION, ask)
    store.append_event(
        Event(
            type=EventType.ASK_OPENED,
            actor=ACTOR,
            entity_id=ask.id,
            correlation_id=ask.correlation_id,
            payload={"kind": ask.kind, "title": ask.title, "options": [o.key for o in ask.options], "cli": ask.cli},
        )
    )
    return ask


def withdraw(store: Store, ask: Ask, why: str) -> None:
    ask.status, ask.withdrawn_why = "withdrawn", why
    store.put(COLLECTION, ask)


# --- the producers --------------------------------------------------------------------------------------------------


def for_approval(proposal: Proposal, title: str) -> Ask:
    opp = proposal.opportunity_id
    return Ask(
        kind="approval",
        title=f"Open the pull request for {opp}?",
        why=f"{title}: proven on branch {proposal.branch}; the mandate asks a person before a pull request.",
        options=[
            AskOption(key="approve", label="approve: the pull request opens on the next cycle (24 h)"),
            AskOption(key="reject", label="reject: the opportunity is closed and not proposed again", input="text"),
            AskOption(key="later", label="later: it stays ready; /inbox shows it"),
        ],
        default="approve",
        subject=opp,
        correlation_id=opp,
        dedup_key=f"approval:{opp}",
        cli=f"unbidden approve {opp}",
    )


def for_block(block: Any) -> Ask | None:
    """A `pending_person` block as the question it is: a key, a registry, an approval; None for one with no
    option but a command (said in the feed as a block)."""
    needs = str(block.needs)
    if "unbidden key set" in needs or "invalid_api_key" in needs:
        return Ask(
            kind="credential",
            title="The Meta API key was refused. Paste another?",
            why=f"{block.operation} stopped: {needs}. Work that needs a model waits until a key is accepted.",
            options=[
                AskOption(key="set", label="set: paste a new key; it is proven before it counts", input="secret"),
                AskOption(key="later", label="later: `unbidden key set` from a terminal"),
            ],
            default="set",
            subject=block.id,
            dedup_key="credential:MODEL_API_KEY",
            cli="unbidden key set",
        )
    registries = re.match(r"add ([\w.\-, ]+) to egress\.package_registries", needs)
    if registries is not None:
        hosts = [h.strip() for h in registries.group(1).split(",") if h.strip()]
        return Ask(
            kind="registry",
            title=f"Allow the sandbox to reach {', '.join(hosts)}?",
            why=f"{block.operation} stopped: {needs}. The mandate lists where builds may fetch from.",
            options=[
                AskOption(key="allow", label=f"allow: add {', '.join(hosts)} to egress.package_registries"),
                AskOption(key="later", label="later: the work stays parked"),
            ],
            default="allow",
            subject=block.id,
            dedup_key=f"registry:{','.join(sorted(hosts))}",
            cli=f"edit .unbidden/mandate.yaml: egress.package_registries += {hosts}",
        )
    if re.search(r"approve-writes|forge approve|approval", needs):
        return Ask(
            kind="access",
            title="A person's approval is needed",
            why=f"{block.operation} stopped: {needs}.",
            options=[AskOption(key="later", label="later: the command is in the feed and `unbidden activity`")],
            default="later",
            subject=block.id,
            dedup_key=f"access:{block.id}",
            cli="unbidden approve-writes <grant>  ·  unbidden forge approve <capability>",
        )
    return None


def for_hold(hold: Hold) -> Ask:
    return Ask(
        kind="hold",
        title="A hold stops deploys. Release it?",
        why=f"{hold.reason}. While it stands nothing is merged or deployed; the investigation runs read-only.",
        options=[
            AskOption(key="keep", label="keep: wait for the investigation (default)"),
            AskOption(key="release", label="release: deploys may run again", input="text"),
        ],
        default="keep",
        subject=hold.id,
        dedup_key=f"hold:{hold.id}",
        cli=f"unbidden hold release {hold.id}",
    )


def for_deploy_steps(action: Any) -> Ask:
    return Ask(
        kind="deploy_steps",
        title=f"Deploy with `{action.operation}`?",
        why=f"{action.reason}. Declared in the mandate it becomes the step Unbidden deploys with; the drill then "
        "proves the rollback before anything autonomous runs.",
        options=[
            AskOption(key="adopt", label="adopt: write it to operations.deploy_steps"),
            AskOption(key="skip", label="skip: deploys stay a person's"),
        ],
        default="adopt",
        subject=action.id,
        dedup_key=f"deploy_steps:{action.operation}",
        cli="edit .unbidden/mandate.yaml: operations.deploy_steps",
    )


def for_capability(need: Any) -> Ask:
    return Ask(
        kind="capability",
        title=f"Use the capability built for {need.source}?",
        why=f"{need.why}. It was built and validated; the mandate leaves its use to a person.",
        options=[
            AskOption(key="approve", label="approve: the capability is used"),
            AskOption(key="later", label="later: it waits"),
        ],
        default="approve",
        subject=need.id,
        dedup_key=f"capability:{need.id}",
        cli=f"unbidden forge approve {need.capability_id or need.id}",
    )


def for_spend(spent: float, cap: float) -> Ask:
    return Ask(
        kind="spend",
        title=f"The monthly cap (US${cap:.2f}) is reached. Raise it?",
        why=f"US${spent:.2f} was spent this month; remote calls are refused until the cap is raised or the month "
        "turns. Credits and the cap are different things: the cap is what this machine may spend.",
        options=[
            AskOption(key="raise", label="raise: a new monthly cap in US$", input="text"),
            AskOption(key="later", label="later: local work continues"),
        ],
        default="later",
        dedup_key="spend:cap",
        cli="unbidden setup budget --budget <USD>",
    )


# --- answering -------------------------------------------------------------------------------------------------------


class AskError(ValueError):
    """The answer cannot be applied: no such ask, no such option, a value missing."""


def answer(ws: Any, store: Store, ask_id: str, option: str, *, value: str | None = None, by: str | None = None) -> Ask:
    """Apply one option of an open ask and close it. `value` is the text typed with an option that takes one."""
    ask = store.get(COLLECTION, ask_id, Ask)
    if ask is None or ask.status != "open":
        raise AskError(f"no open ask {ask_id}")
    chosen = ask.option(option)
    if chosen is None:
        raise AskError(f"{option!r} is not one of {', '.join(o.key for o in ask.options)}")
    if chosen.input == "secret" and not value:
        raise AskError("this option needs the value typed with it")
    who = by or getpass.getuser()
    outcome = _apply(ws, store, ask, option, value, who)
    ask.status, ask.answer, ask.answered_by, ask.outcome = "answered", option, who, outcome
    from unbidden.contracts.common import utc_now

    ask.answered_at = utc_now()
    store.put(COLLECTION, ask)
    store.append_event(
        Event(
            type=EventType.ASK_ANSWERED,
            actor=f"person:{who}",
            entity_id=ask.id,
            correlation_id=ask.correlation_id,
            payload={"kind": ask.kind, "title": ask.title, "answer": option, "outcome": outcome},
        )
    )
    return ask


def _apply(ws: Any, store: Store, ask: Ask, option: str, value: str | None, who: str) -> str:
    if (
        option == "later"
        or (ask.kind == "hold" and option == "keep")
        or (ask.kind == "deploy_steps" and option == "skip")
    ):
        return "nothing changed"
    if ask.kind == "approval":
        from unbidden.operate.decisions import approve_by_id, reject_by_id

        assert ask.subject is not None
        if option == "approve":
            done = approve_by_id(store, ask.subject, by=who, hours=24)
            if done.get("error"):
                raise AskError(str(done["error"]))
            return f"approved for 24 h: the pull request for {done.get('branch')} opens on the next cycle"
        done = reject_by_id(store, ask.subject, by=who, reason=value or "rejected from the app")
        if done.get("error"):
            raise AskError(str(done["error"]))
        return "rejected: not proposed again"
    if ask.kind == "hold":
        from unbidden.operate.holds import release

        assert ask.subject is not None
        release(store, ask.subject, f"person:{who}", value or "released from the app")
        return "hold released: deploys may run again"
    if ask.kind == "credential":
        from unbidden.guardian.credentials import broker
        from unbidden.setup import machine
        from unbidden.setup.keycheck import forget, looks_like_key, verify_key

        assert value is not None
        why = looks_like_key(value)
        if why is not None:
            raise AskError({"command": "that looks like a command, not a key", "spaces": "a key has no spaces",
                            "short": "a key is longer than that", "empty": "empty"}[why])  # fmt: skip
        machine.write_env(machine.machine_env(), {"MODEL_API_KEY": value.strip()})
        broker().hold("MODEL_API_KEY", value.strip())
        broker().grant("MODEL_API_KEY", "model.remote")
        forget("MODEL_API_KEY")
        verdict = verify_key(ws, force=True)
        if verdict.rejected:
            raise AskError("Meta refused that key too; nothing changed for the agent")
        if not verdict.ok:
            return f"key saved; not proven now ({(verdict.why or '')[:80]})"
        _release_blocks(store, ask)
        return f"key accepted: {verdict.model} answered; the parked work runs again"
    if ask.kind == "registry":
        from unbidden.guardian.mandate_edit import read_raw, write_mandate

        hosts = [o for o in ask.dedup_key.removeprefix("registry:").split(",") if o]
        raw = read_raw(ws.mandate_path)
        egress = raw["mandate"].setdefault("egress", {})
        listed = list(egress.get("package_registries") or [])
        for host in hosts:
            if host not in listed:
                listed.append(host)
        egress["package_registries"] = listed
        write_mandate(ws.mandate_path, raw, store, {"ask": {"id": ask.id, "package_registries": hosts}})
        _release_blocks(store, ask)
        return f"{', '.join(hosts)} allowed; the parked work runs again"
    if ask.kind == "deploy_steps":
        import shlex

        from unbidden.guardian.mandate_edit import read_raw, write_mandate

        command = ask.title.split("`")[1] if "`" in ask.title else ""
        if not command:
            raise AskError("no command in this ask")
        raw = read_raw(ws.mandate_path)
        operations = raw["mandate"].setdefault("operations", {})
        steps = list(operations.get("deploy_steps") or [])
        argv = shlex.split(command)
        if argv not in steps:
            steps.append(argv)
        operations["deploy_steps"] = steps
        write_mandate(ws.mandate_path, raw, store, {"ask": {"id": ask.id, "deploy_steps": argv}})
        return f"deploy step declared: {command}; `unbidden drill` proves the rollback"
    if ask.kind == "capability":
        raise AskError("approving a capability is `unbidden forge approve <capability>` in this version")
    if ask.kind == "spend":
        # The cap the router checks is the mandate's (`business_constraints.maximum_monthly_spend_usd`); the machine
        # ledger is a person's own record of credits and is never edited from a question (`unbidden spend`).
        from unbidden.guardian.mandate_edit import read_raw, write_mandate

        try:
            amount = float((value or "").replace("$", "").replace("US", "").strip())
        except ValueError as exc:
            raise AskError("the new cap must be a number of US$") from exc
        raw = read_raw(ws.mandate_path)
        constraints = raw["mandate"].setdefault("business_constraints", {})
        before = float(constraints.get("maximum_monthly_spend_usd") or 0)
        if amount <= before:
            raise AskError(f"the new cap must be above the current US${before:.2f}")
        constraints["maximum_monthly_spend_usd"] = amount
        write_mandate(ws.mandate_path, raw, store, {"ask": {"id": ask.id, "monthly_cap_usd": [before, amount]}},
                      actor=who)  # fmt: skip
        _release_blocks(store, ask)
        return f"monthly cap now US${amount:.2f} (was US${before:.2f})"
    raise AskError(f"no effect for {ask.kind}/{option}")


def _release_blocks(store: Store, ask: Ask) -> None:
    """The blocks this ask stood for are resolved and the jobs they held run now."""
    from unbidden.contracts.common import utc_now
    from unbidden.contracts.jobs import JobStatus
    from unbidden.director.blocks import COLLECTION as BLOCKS
    from unbidden.director.blocks import Block, open_blocks

    for block in open_blocks(store):
        same = (
            block.id == ask.subject
            or (ask.kind == "credential" and "unbidden key set" in block.needs)
            or (ask.kind == "spend" and "maximum_monthly_spend_usd" in block.needs)
        )
        if not same:
            continue
        block.resolved, block.resolved_at = True, utc_now()
        store.put(BLOCKS, block)
        for held in store.jobs(status=JobStatus.QUEUED):
            if held.id in block.jobs:
                store.requeue(held)
    _ = Block  # the collection's model, imported for the type


# --- closing on their own ---------------------------------------------------------------------------------------------


def reconcile(store: Store) -> list[Ask]:
    """Withdraw open asks whose matter was settled another way: the proposal published or rejected from the CLI,
    the hold released, the block resolved, the key proven, the capability in use."""
    from unbidden.director.blocks import COLLECTION as BLOCKS
    from unbidden.director.blocks import Block

    gone: list[Ask] = []
    for ask in open_asks(store):
        why: str | None = None
        if ask.kind == "approval" and ask.subject:
            proposal = store.get_by_key("proposals", ask.subject, Proposal)
            if proposal is None or proposal.status is not ProposalStatus.READY:
                why = f"the proposal is {proposal.status.value if proposal else 'gone'}"
            else:
                from unbidden.guardian.approvals import find_valid
                from unbidden.publish.github import CAPABILITY

                if find_valid(store, CAPABILITY, proposal.id) is not None:
                    why = "approved from the CLI"
        elif ask.kind == "hold" and ask.subject:
            hold = store.get("holds", ask.subject, Hold)
            if hold is None or hold.released_at is not None:
                why = "the hold was released"
        elif ask.kind in ("credential", "registry", "access") and ask.subject:
            block = store.get(BLOCKS, ask.subject, Block)
            if block is not None and block.resolved:
                why = "the block was resolved"
            elif ask.kind == "credential":
                from unbidden.setup.keycheck import current_key, recall

                key = current_key()
                known = recall("MODEL_API_KEY", key) if key else None
                if known is not None and known.ok:
                    why = "a key was accepted"
        if why is not None:
            withdraw(store, ask, why)
            gone.append(ask)
    return gone


def summary(store: Store) -> list[dict[str, Any]]:
    return [a.as_summary() for a in open_asks(store)]


def age(ask: Ask) -> timedelta:
    from unbidden.contracts.common import utc_now

    return utc_now() - ask.created_at
