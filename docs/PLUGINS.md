# Plugins

An installed Python package can add three things to Unbidden, each by an entry point. Nothing is configured in
Unbidden itself: install the package next to it and `unbidden plugins` lists what it added.

| Group | Adds | The object |
|---|---|---|
| `unbidden.connectors` | a kind of resource a mandate's grant may name (`kind: mqtt`) | a `connect.base.Connector`: `kind`, `validate(grant)`, `check(grant)`; optionally `protocol` |
| `unbidden.ask_kinds` | a class of question for a person | an `unbidden.plugins.AskKind`: `kind`, `apply(ws, store, ask, option, value, who) -> str` |
| `unbidden.skills` | a capability with a card, listed and runnable | an `unbidden.plugins.Skill`: `name`, `card` (a `SkillCard`), `run(inputs) -> dict` |

```toml
# the plugin's pyproject.toml
[project.entry-points."unbidden.connectors"]
mqtt = "my_plugin.connect:MqttConnector"

[project.entry-points."unbidden.ask_kinds"]
meeting = "my_plugin.asks:Meeting"

[project.entry-points."unbidden.skills"]
pillar_fos = "my_plugin.skills:PillarFos"
```

The entry point's name is the name Unbidden uses, and the object must carry the same one (`kind` or `name`). A
class is instantiated once with no arguments; an instance is used as it is.

## What a plugin cannot do

- **Take a shipped name.** `postgres`, `http_api`, `github` and the shipped ask kinds stay Unbidden's. A plugin
  registered under one is left out.
- **Widen permissions.** A plugin's connection is surveyed, checked and used like a shipped one: the grant in the
  mandate says what is allowed, `check` only reports what the credential could do, and every read and write
  passes `connect.base.require` (the grant, the policy, the egress rules). A credential is handed out by the
  broker to its connection only. A connector that can write is still refused when the grant says `read`.
- **Stop the agent.** A plugin that fails to import, raises in its constructor, or is not what its group expects
  is left out, with the reason in `unbidden plugins` and `unbidden doctor`.

What a plugin can do is run code in the agent's process: installing one is trusting it, like any dependency.

## Asks

`director.asks.open_ask` refuses a kind nobody provides. An ask of a plugin's kind is answered like any other
(the app, the dashboard, `unbidden ask`); the chosen option reaches the plugin's `apply`, whose one-line return is
the ask's outcome. Raise `ValueError` to refuse an answer: the ask stays open. `later` never reaches the plugin.
If the plugin is removed while its asks are open, they stay readable; answering one says the plugin is missing.

## Skills

A skill's card answers, before it runs, what a forged capability's card answers: purpose, inputs and outputs with
their units, the permissions it needs, its limits, and the highest evidence level one of its results supports on
its own. This release lists skills and lets a plugin's own code run them; the director does not pick skills yet.

## A grant for a kind with no connector

It is not an error. The connection is reported as `needs_capability` ("no connector for mqtt yet") and nothing
uses it. Installing the plugin and running `unbidden connections --check` connects it.
