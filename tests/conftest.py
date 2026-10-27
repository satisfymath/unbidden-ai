from __future__ import annotations

import pytest

from unbidden.contracts.guardian import (
    Autonomy,
    AutonomyPolicy,
    EgressPolicy,
    GitHubPolicy,
    Mandate,
    RemoteModelPolicy,
)
from unbidden.store import Store


@pytest.fixture
def store() -> Store:
    return Store(None)


@pytest.fixture
def mandate() -> Mandate:
    return Mandate(
        workspace="shop",
        autonomy=AutonomyPolicy(
            observe=Autonomy.ALLOW,
            run_experiments=Autonomy.ALLOW,
            provision_dependencies=Autonomy.ALLOW,
            delegate_synthetic=Autonomy.ALLOW,
            open_pull_requests=Autonomy.REQUIRE_APPROVAL,
        ),
        egress=EgressPolicy(
            package_registries=["registry.npmjs.org", "pypi.org"],
            remote_models=RemoteModelPolicy(destinations=["api.meta.ai"]),
            github=GitHubPolicy(repository="acme/shop"),
        ),
    )
