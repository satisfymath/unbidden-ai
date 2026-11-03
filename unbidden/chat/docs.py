"""What Unbidden is and how it is driven, in the package itself: the chat's `docs` tool reads it so the agent can
answer "what is unbidden?" or "what does /ask do?" without a model inventing it. English only: the model answers in
the person's language."""

from __future__ import annotations

from typing import Literal

Topic = Literal["what", "cycle", "commands", "modes", "levels", "keys", "spend"]

WHAT = """Unbidden is a proactive engineering agent that lives in a repository. It does not wait for instructions:
it maps the system (the code, the compose stack, the database, the endpoints), finds opportunities (a missing index,
a lint error, a crash nobody reported, a slow endpoint), reproduces them, measures a candidate fix in an offline
sandbox against the real workload shape, and proposes the change as a pull request with the evidence. A person
decides what is merged; in autonomous mode it merges proven work, deploys with the team's own steps and rolls back
when health degrades. Secrets and production data never leave the machine; private code leaves only renamed by the
privacy bridge, or when the mandate allows it. Built at the Meta Global AI Developer Hackathon (October to November
2026)."""

CYCLE = """One cycle, over and over: Discovering (the head, the map of the running system, the analyzers, the
project's own checks) → Deciding (which opportunity is worth an experiment, with a utility and a reason) →
Experimenting (reproduce it, measure a candidate in the sandbox, several sessions, p-values) → Proving (the evidence
level, the branch, the pull request) → following the pull request (CI, merge, deploy, the outcome after the
deploy). Every step is an event in the record; the app narrates them under those verbs."""

COMMANDS = """In the app (`unbidden`), / starts a command: /start [--ui] runs the agent in the background; /stop
ends it; /ask [id] answers the agent's oldest question (or the one named) with arrows and Enter; /inbox lists the
open opportunities with their stage; /why <id> explains one; /approve <id> and /reject <id> <reason> decide a proposal;
/activity shows what it did and what waits for a person; /spend the cost on this machine; /doctor what the machine
provides; /ui [--open] the dashboard; /setup [section|--all] the guided configuration; /key pastes a new Meta API key
(proven before it counts); /kill [reason] and /resume the kill switch; /log shows the agent's log; /verbose shows every
model call; /language changes the language; /clear and /quit. Anything else typed is a question for the agent.
From a terminal the same exist as `unbidden <command>`: start, stop, status, ask, inbox, why, approve, reject,
activity, spend, doctor, ui, setup, key, map, connections, scan, try, drill, deploy, hold, mode, models, route, chat."""

MODES = """Three modes, in the mandate (.unbidden/mandate.yaml, `unbidden mode`): supervised prepares everything and
asks before a pull request, never merges or deploys; autopilot opens pull requests on its own for proven work, people
merge; autonomous also merges L4 work, deploys with the team's steps (operations.deploy_steps) and rolls back, and is
available only after a passed rollback drill (`unbidden drill`). The other permissions (observe, run experiments,
write through connections) are granted separately in the mandate."""

LEVELS = """Evidence levels: L1 reasonable suspicion (a finding, a rule); L2 reproduction (the problem reproduced
in the sandbox); L3 lab improvement (a candidate measured better, offline); L4 functional validation (the project's
own checks pass on the candidate and the improvement holds); L5 operational result (observed after a deploy); L6
persistence (the result held over time). A proposal needs the level the mandate asks (L4 by default)."""

KEYS = """A Meta API key (MODEL_API_KEY) lets heavy work go to Meta's API; it is pasted in the setup or with
`unbidden key set` / /key and proven with one short call before it counts; `unbidden key` says its state. A local
model through Ollama serves what never leaves the machine. GitHub access comes from the gh CLI's sign-in or a token
(GITHUB_TOKEN); the setup verifies it can push to the repository."""

SPEND = """Remote model calls are counted in a machine-wide ledger (`unbidden spend`): every call reserves its worst
cost first, the mandate's monthly cap (business_constraints.maximum_monthly_spend_usd) is checked, and a verified
balance a person entered is what the machine may spend. Reading records, the dashboard and the rules planner cost
nothing; an analysis or a question answered by a model is one routed call."""

TOPICS: dict[str, str] = {
    "what": WHAT,
    "cycle": CYCLE,
    "commands": COMMANDS,
    "modes": MODES,
    "levels": LEVELS,
    "keys": KEYS,
    "spend": SPEND,
}


def read(topic: str) -> str:
    return TOPICS.get(topic, "no such topic; one of " + ", ".join(TOPICS))
