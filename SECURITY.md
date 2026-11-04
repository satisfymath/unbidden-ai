# Security policy

## Reporting a vulnerability

Please do not open a public issue. Report it privately through
[GitHub's private vulnerability reporting](https://github.com/satisfymath/unbidden-ai/security/advisories/new).

Include what you found, how to reproduce it, the version (`unbidden --version`) and the impact you expect. Leave out
real secrets, tokens and production data.

Unbidden is maintained by one person, so response times are best effort. You will get an answer in the advisory, and
credit when a fix is published if you want it.

## Supported versions

Unbidden is an experimental candidate. Only the [latest release](https://github.com/satisfymath/unbidden-ai/releases/latest)
receives fixes; `unbidden update` installs it.

## What counts as a vulnerability

Reports that matter most are the ones that break a guarantee Unbidden makes:

- A secret, log or production data leaving the machine, or private code leaving without the privacy bridge when the
  mandate does not allow it.
- A way past the egress gate, or an outbound payload that `unbidden egress --payload` does not show.
- A repository's code running outside the sandbox, or the sandbox reaching the network when it must not.
- Content in a repository, issue or log making the agent act (prompt injection) beyond what its mandate grants.
- An action taken past the autonomy mode, a hold or `unbidden kill`.
- A tampered wheel that the installer accepts despite `SHA256SUMS`.

[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) lists what is guaranteed and what is not. Something it already declares as not
guaranteed is better raised as a regular issue.
