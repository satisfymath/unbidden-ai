"""A request to a person names what it unblocks (stage 8).

Found on Conduit (frozen run 9ef6a60): experiments failed to provision for want of Debian's archive, and the one
thing listed for a person was GitHub access, which nothing needed."""

from __future__ import annotations

import pytest

from unbidden.director.blocks import classify, open_blocks, record
from unbidden.store import Store

pytestmark = pytest.mark.unit
NEEDS_DEBIAN = (
    "dependency image for python failed to build:\nError: pg_config executable not found.\nA package is built from "
    "source and needs a C compiler; system packages come from deb.debian.org, which the mandate's package registries "
    "do not list."
)


@pytest.mark.parametrize(
    ("error", "kind", "needs"),
    [
        (NEEDS_DEBIAN, "pending_person", "add deb.debian.org to egress.package_registries"),
        ("sandbox.provision: destination pypi.org is not in the mandate's allowlist", "pending_person", "pypi.org"),
        ("python dependencies still fail to build with build-essential and libpq-dev installed", "compatibility",
         "nothing a person can grant"),
        ("blocked: conduit-api: no integration could be validated (listArticles ...)", "missing_capability",
         "integration"),
        ("httpx.ConnectError: [Errno 61] Connection refused", "unavailable", "retried"),
    ],
)  # fmt: skip
def test_a_block_says_who_can_unblock_it_and_how(error: str, kind: str, needs: str) -> None:
    block = classify("research.probe opp_1", error, "the experiment on opp_1 runs again")
    assert block.kind == kind and needs in block.needs and block.continues


def test_the_same_block_is_one_request_and_an_unneeded_access_is_optional(store: Store) -> None:
    from unbidden.contracts.connection import Connection, ConnectionState
    from unbidden.director.activity import _ecosystem  # pyright: ignore[reportPrivateUsage]

    first = record(store, classify("research.probe opp_1", NEEDS_DEBIAN, "it runs again"))
    again = record(store, classify("research.probe opp_1", NEEDS_DEBIAN + " (again)", "it runs again"))
    assert first.id == again.id and len(open_blocks(store)) == 1
    from unbidden.connect.registry import record as keep

    keep(store, Connection(id="github:o/r", project="p", kind="github", protocol="https", location="o/r",
                           state=ConnectionState.DISCOVERED), reason="found in the git remote")  # fmt: skip
    seen = _ecosystem(store)
    assert [n["what"].split(" (then")[0] for n in seen["needs_a_person"]] == [first.needs]
    assert [o["connection"] for o in seen["optional_access"]] == ["github:o/r"]  # listed, not asked for
