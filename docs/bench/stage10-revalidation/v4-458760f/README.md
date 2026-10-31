# Revalidation attempt at 458760f: did not start

fst: provisioning refused, registry.npmjs.org not in the harness's fixed mandate (the original run allowed it).
mealie: the image build failed: Python 3.14 required, 3.12 chosen (3.14 was not in SUPPORTED). No experiment ran.
Both fixed in the next commits; rerun from a worktree frozen there.

```
    raise ProvisionDenied(f"sandbox.provision: {'; '.join(verdict.reasons)}")
unbidden.sandbox.provision.ProvisionDenied: sandbox.provision: destination registry.npmjs.org is not in the mandate's allowlist
error: The requested interpreter resolved to Python 3.12.15, which is incompatible with the project's Python requirement: `==3.14.*` (from `project.requires-python`)
```
