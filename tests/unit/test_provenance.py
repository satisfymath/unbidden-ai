from __future__ import annotations

import pytest

from tests.unit.test_router import make_brain
from unbidden.contracts.guardian import Mandate
from unbidden.provenance import code_version, provenance
from unbidden.sandbox.provision import DependencyImage
from unbidden.store import Store

pytestmark = pytest.mark.unit


def test_an_experiment_records_the_code_models_and_environment_that_produced_it(store: Store, mandate: Mandate) -> None:
    brain, _, _ = make_brain(store, mandate)
    image = DependencyImage(tag="unbidden-deps-python:abc", language="python", registries=[], env={}, links={})
    record = provenance(brain, [image, image], seed=3, workload=None)
    assert record["unbidden"] == code_version()
    assert len(record["unbidden"]["commit"]) == 40 and isinstance(record["unbidden"]["dirty"], bool)
    assert record["routes"]["code"].startswith("remote:muse-spark-1.3")
    assert record["models"]["local_fallback"] == "allow"
    assert record["images"] == ["unbidden-deps-python:abc"] and record["seed"] == 3 and "workload" not in record
