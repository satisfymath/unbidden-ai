"""Every sentence the chat says by itself (the rules planner, refusals, phases), in one place; English first, the
Spanish table in `text_es.py`. A model's own answer follows the prompt, which names the language."""

from __future__ import annotations

T: dict[str, str] = {
    "tool.added": "added «{title}»",
    "tool.connected": "connected ({kind}: {label})",
    "tool.undone": "undone: {what}",
    "tool.added.nodata": " (no data: {note})",
    "change.title": "title",
    "change.size": "size",
    "change.data": "data",
    "explain.opportunity": "{title}\n\n{summary}\n\nLevel L{level}, status {status}. Decision: {chosen} — {reason}.",
    "explain.noreason": "no reason recorded",
    "explain.verdict": "\nVerdict: {outcome}; {reasons}",
    "explain.improved": "improved",
    "explain.notimproved": "not improved",
    "explain.blocked": "\nBlocked: {why}",
    "explain.history": "\n\nHistory: {items}",
    "explain.block": (
        "Block ({kind}) in «{operation}».\n\nEvidence: {evidence}\n\nThe least that unblocks it: {needs}.\n"
        "Given that, it continues: {continues}."
    ),
    "explain.experiment": (
        "Experiment {id} on «{title}»: {sessions} sessions, {control} control, {confirmation} confirmation; "
        "cost US${usd:.4f}."
    ),
    "explain.experiment.verdict": "\nVerdict: {outcome} (L{level}): {reasons}",
    "rule.undo": "Undoing the last change to the canvas.",
    "rule.select.rename": "Select the card you want to rename.",
    "rule.rename": "Changing the title.",
    "rule.select.resize": "Select the card whose size you want to change.",
    "rule.resize": "Changing the size.",
    "rule.nochart": "There is no chart on the canvas or selected that I could change.",
    "rule.chart.kind": "Changing «{title}» to {kind}.",
    "rule.compare.need": (
        "To compare I need two compatible runs selected (two experiment cards, or finding cards with an "
        "experiment). Right now I have {n}."
    ),
    "rule.compare": "Comparing the sessions of {a} and {b}: medians by arm and position.",
    "rule.compare.title": "Comparison · {a} vs {b}",
    "rule.noexperiment": (
        "There is no experiment with samples in this workspace: nothing to chart. When the engine runs one "
        "(`unbidden try <opportunity>`), I can show its latencies."
    ),
    "rule.latency.title": "Latency before and after · {title}",
    "rule.latency": "Charting the latency samples of experiment {id} by arm.",
    "rule.failed.tests": "Adding a table with the tests that failed in some round.",
    "rule.failed.tests.title": "Tests that failed",
    "rule.noblock": "There is no block recorded in this workspace.",
    "rule.block.map.title": "The block's dependencies",
    "rule.block.map.label": "depends on",
    "rule.explain.block": "Explaining the block{more}",
    "rule.explain.block.map": " and adding its dependencies to the map.",
    "rule.opportunities": "Adding a table with the opportunities.",
    "rule.opportunities.title": "Opportunities",
    "rule.explain.selected": "Explaining the selection.",
    "rule.select.explain": "Select a card (finding, experiment, block) and I explain it with its references.",
    "rule.unknown": (
        "I did not understand the request. I can: chart the latency before and after an experiment, add a table "
        "with the tests that failed, chart the spend per run, explain a block and add its dependencies to the map, "
        "change a chart to bars/lines, compare two selected runs, rename or resize a card, and undo the last card."
    ),
    "status.line": (
        "Record of {name} ({mode}, head {head}): {opportunities} opportunities, {experiments} experiments, "
        "{proposals} proposals, {events} events, {model_runs} model calls, {blocks} blocks."
    ),
    "status.jobs": "Jobs: {jobs}",
    "status.jobs.none": "none",
    "status.block": "Block {kind} in «{operation}»: {evidence}",
    "status.agent": "Agent: {detail}.",
    "status.hint": "For a why or a recommendation ask for an analysis; to see something, a table or a chart.",
    "brain.cancelled": "Cancelled before the planning completed.",
    "brain.noanswer": "(no answer)",
    "brain.rounds": "I applied the tools above.",
    "chat.greeting": (
        "Hi. I am Unbidden, the agent working on {workspace}. Ask me what I found, what I am doing now, why "
        "something is slow, or what a command does; approving, merging and deploying go through /ask, /approve or "
        "the dashboard's buttons, not through here."
    ),
    "agent.refused": "I cannot answer that with a model here: {why}.",
    "agent.noanswer": "The model did not answer ({why}); what the tools read is below.",
    "agent.rounds": "I read what I could; the tool budget is spent. Ask again for the rest.",
    "rule.spend": "Charting the remote spend grouped by {by}.",
    "rule.spend.title": "Spend by {by}",
    "widget.updated": "updated {changes} of «{title}»",
    "widget.view": "view",
    "analyze.nomodel": "I cannot analyze this with a model ({why}). {hint}.",
    "rules.failed": "Could not ({tool}): {why}.{need}",
    "rules.need": " To have it: {need}.",
    "brain.failed": " (the route through the model failed; try again or use the rules planner)",
    "brain.rules": "{reply} (The local model gave no valid answer: {why}. Answered by rules.)",
    "cancel.none": "no turn in progress",
    "cancel.during": "cancellation requested during: {phase}; what already reached the canvas stays",
    "phase.planning": "planning",
    "phase.reading": "reading",
    "phase.building": "building",
    "refuse.action": (
        "Not from the chat: «{action}» is an action, not a query. To do it: {where}. It goes through the project's "
        "effective permissions and lands in the audit. If you want, I show or analyze what is there before you decide."
    ),
    "analyze.refused": "I cannot analyze this with a model: {why}.",
    "analyze.hint": " It would be allowed by: {hint}.",
    "analyze.noanswer": "The model did not answer ({why}); no analysis. What was read is below.",
    "plan.cancelled": " Cancelled before step {step} of {total}; what came before stays applied.",
    "where.deploy": "`unbidden deploy`",
    "where.rollback": "`unbidden deploy --rollback`",
    "where.merge": "a person merges on GitHub; autonomous mode merges L4 work (`unbidden mode`)",
    "where.kill": "the kill switch button, or `unbidden kill`",
    "where.resume": "the resume button, or `unbidden resume`",
    "where.experiment": "`unbidden try <opportunity>` or the agent's own cycle (`unbidden start`)",
    "where.approve": "the approve button, or `unbidden approve <id>`",
    "where.reject": "the reject button, or `unbidden reject <id>`",
    "where.start": "`unbidden start`",
    "where.stop": "`unbidden stop`",
}


def t(key: str, **kwargs: object) -> str:
    from unbidden.i18n import lookup
    from unbidden.web import text_es

    return lookup(T, {"es": text_es.T}, key, **kwargs)
