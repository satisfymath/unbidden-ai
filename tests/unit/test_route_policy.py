from __future__ import annotations

import pytest

from unbidden.brain.route_policy import decide_route
from unbidden.brain.tasks import task_for
from unbidden.contracts.llm import ContentLabel, Message, Tier
from unbidden.guardian.classify import classify

pytestmark = pytest.mark.unit
L = ContentLabel
HEAVY, LIGHT = task_for("lab.fix_candidate"), task_for("world.endpoint_tables")


@pytest.mark.parametrize("profile", ["local", "local-first", "frontier"])
@pytest.mark.parametrize("label", [L.SECRET, L.PRODUCTION_DATA])
def test_secrets_and_production_data_never_leave_in_any_profile(profile: str, label: ContentLabel) -> None:
    decision = decide_route(profile, HEAVY, label, private_code_to_frontier=True)  # type: ignore[arg-type]
    assert decision.tier is Tier.LOCAL and decision.fallback is None and not decision.remote_allowed


@pytest.mark.parametrize(
    ("profile", "label", "allow_private", "tier", "fallback"),
    [
        ("local", L.PUBLIC_CODE, False, Tier.LOCAL, None),
        ("local-first", L.PRIVATE_CODE, False, Tier.LOCAL, None),
        ("local-first", L.PUBLIC_CODE, False, Tier.CODE, Tier.LOCAL),
        ("local-first", L.SYNTHETIC, False, Tier.CODE, Tier.LOCAL),
        ("frontier", L.PRIVATE_CODE, False, Tier.LOCAL, None),
        ("frontier", L.PRIVATE_CODE, True, Tier.CODE, Tier.LOCAL),
        ("frontier", L.PUBLIC_CODE, False, Tier.CODE, Tier.LOCAL),
    ],
)
def test_heavy_tasks(profile: str, label: ContentLabel, allow_private: bool, tier: Tier, fallback: Tier | None) -> None:
    decision = decide_route(profile, HEAVY, label, private_code_to_frontier=allow_private)  # type: ignore[arg-type]
    assert (decision.tier, decision.fallback) == (tier, fallback)


def test_light_tasks_start_local_and_unknown_purposes_never_leave() -> None:
    assert decide_route("local-first", LIGHT, L.PUBLIC_CODE).tier is Tier.LOCAL
    assert decide_route("frontier", task_for("something.new"), L.PUBLIC_CODE).fallback is None


def test_no_remote_model_configured_means_local() -> None:
    assert decide_route("frontier", HEAVY, L.PUBLIC_CODE, remote_available=False).tier is Tier.LOCAL


def m(content: str, source: str | None) -> Message:
    return Message(role="user", content=content, source=source)  # type: ignore[arg-type]


def test_classification_takes_the_strictest_part() -> None:
    assert classify([m("do it", "prompt")], repo_public=False).label is L.INSTRUCTIONS
    assert classify([m("def f(): pass", "repo")], repo_public=True).label is L.PUBLIC_CODE
    assert classify([m("def f(): pass", "repo")], repo_public=False).label is L.PRIVATE_CODE
    assert classify([m("anything", None)], repo_public=True).label is L.PRIVATE_CODE
    assert classify([m("x", "prompt"), m("row", "database")], repo_public=True).label is L.PRODUCTION_DATA


def test_the_text_itself_can_only_make_it_stricter() -> None:
    assert classify([m("DB_PASSWORD=Xk9fT2qLm8", "repo")], repo_public=True).label is L.SECRET
    env = "API_URL=https://x\nDEBUG=1\nREGION=us\n"
    assert classify([m(env, "prompt")], repo_public=True).label is L.SECRET
    assert classify([m("contact maria.perez@acme.cl", "repo")], repo_public=True).label is L.PRODUCTION_DATA
    assert classify([m("client 181.43.2.10 connected", "repo")], repo_public=True).label is L.PRODUCTION_DATA
    assert classify([m("admin@example.com on 127.0.0.1", "repo")], repo_public=True).label is L.PUBLIC_CODE


@pytest.mark.parametrize("purpose", ["forge.api_client", "director.goal_plan"])
def test_planning_and_reading_documentation_go_remote_only_when_their_content_may_leave(purpose: str) -> None:
    from unbidden.brain.route_policy import decide_route
    from unbidden.brain.tasks import task_for
    from unbidden.contracts.llm import ContentLabel, Tier

    lab = decide_route("local-first", task_for(purpose), ContentLabel.SYNTHETIC)
    assert lab.tier is Tier.CODE and lab.fallback is Tier.LOCAL and lab.remote_allowed
    real = decide_route("local-first", task_for(purpose), ContentLabel.PRODUCTION_DATA)
    assert real.tier is Tier.LOCAL and not real.remote_allowed
    assert decide_route("local", task_for(purpose), ContentLabel.SYNTHETIC).tier is Tier.LOCAL
