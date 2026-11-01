from __future__ import annotations

from pathlib import Path

import pytest

from unbidden.guardian.scanner import SensitiveTermIndex, redact_json, redact_text, scan, secret_hits

pytestmark = pytest.mark.unit

FAKE_GH = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"


@pytest.mark.parametrize(
    "text",
    [
        "AKIAABCDEFGHIJKLMNOP",
        f"token: {FAKE_GH}",
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz012345",
        "postgres://app:s3cr3tpass@db:5432/shop",
        "PAYMENT_API_KEY=pk_9f8e7d6c5b4a",
        "-----BEGIN OPENSSH PRIVATE KEY-----",
        'password: "hunter2hunter2"',
        "sk-" + "x" * 30,
        'password = "supersecretpassword"',
        "DB_PASSWORD=Xk9fT2qLm8",
    ],
)
def test_detects_secrets(text: str) -> None:
    assert secret_hits(scan(text)), text


@pytest.mark.parametrize(
    "text",
    [
        "API_KEY=${API_KEY}",
        "token: <your-token>",
        "password = os.environ.get('PASSWORD')",
        "secret_key: changeme",
        "MODEL_API_KEY=",
        "the token budget is spent per call",
        "api_key: str",
        "password = random_lower_string()",
        'auth_token = response["access_token"]',
        "tokens = r.json()",
        "user_in = UserCreate(email=email, password=password)",
        "def ask(prompt: str, password: bool=False, choices: list=None)",
    ],
)
def test_ignores_placeholders(text: str) -> None:
    assert not secret_hits(scan(text)), text


def test_redaction_keeps_a_prefix_and_is_idempotent() -> None:
    text = f"push with {FAKE_GH} now"
    once = redact_text(text)
    assert FAKE_GH not in once
    assert "gh***" in once
    assert redact_text(once) == once and not secret_hits(scan(once))
    assigned = redact_text('login(password="password")')  # the scan of a masked text finds nothing, too
    assert assigned == 'login(password="pa***")' and not secret_hits(scan(assigned))


def test_redact_json_walks_nested_values() -> None:
    value = {"a": [f"x {FAKE_GH}"], "b": {"c": "DB_PASSWORD=abcdefgh123"}}
    out = redact_json(value)
    assert FAKE_GH not in str(out)
    assert "abcdefgh123" not in str(out)


def test_identifiers_match_whole_words_case_insensitive() -> None:
    index = SensitiveTermIndex(["order_items", "api"])
    assert len(index) == 1  # short terms are ignored
    kinds = [h.kind for h in scan("SELECT * FROM Order_Items", index)]
    assert kinds == ["identifier:order_items"]
    assert not scan("reorder_items_total", index)


# Stage 10 diagnosis (docs/bench/stage10-diagnosis.md): the records' two Guardian refusals.
@pytest.mark.parametrize(
    "text",
    [
        "SPOOLMAN_DB_URL=postgresql+asyncpg://postgres:abc@db:5432/spoolman",  # a test configuration's URL
        "postgres://app:s3cr3tpass@db:5432/shop",
        "redis://user:longerpassword@cache:6379/0",
    ],
)
def test_masking_a_url_password_is_idempotent(text: str) -> None:
    once = redact_text(text)
    assert not secret_hits(scan(once)), once  # the masked prompt passes the scan it is sent through
    assert redact_text(once) == once


@pytest.mark.parametrize(
    "text",
    [
        "mysql://root:${MYSQL_PASSWORD}@db:3306/app",  # an environment reference, not a value
        "reservation_token=reservation.reservation_token,",  # Prefect's code: a dotted attribute path
        '"reservation_token": frame.payload.reservation_token,',
        "ORMCsrfToken = CsrfToken",  # an alias of a class
    ],
)
def test_code_and_references_are_not_secrets(text: str) -> None:
    assert not secret_hits(scan(text)), text


@pytest.mark.parametrize(
    "text",
    [
        "API_TOKEN=Ab9xQ2mZ7rT4",  # an unquoted value that is not a name in the key
        'reservation_token = "res.abc.Def123"',  # quoted: always judged as a possible secret
        "JWT_SECRET=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcDEF123",  # a token with dots, mixed case
        "postgres://app:Xk9fT2qLm8@db/shop",
    ],
)
def test_real_secrets_are_still_refused(text: str) -> None:
    assert secret_hits(scan(text)), text


def test_the_router_masks_repository_text_and_still_refuses_other_secrets(tmp_path: Path) -> None:
    """Stage 10: repository text is masked before Guardian's scan; a secret from any other source is still refused."""
    from unbidden.brain.router import Brain, SecretInPrompt
    from unbidden.contracts.llm import LLMRequest, Message, Tier
    from unbidden.store import Store

    store = Store(tmp_path / "state.db")
    brain = Brain.__new__(Brain)
    brain.store = store
    repo = LLMRequest(
        purpose="t",
        tier=Tier.LOCAL,
        max_tokens=10,
        messages=[Message(role="user", source="repo", content="URL=postgresql://u:abcdef@db/x")],
    )
    masked = brain._mask_repository(repo)  # pyright: ignore[reportPrivateUsage]
    assert "abcdef" not in masked.messages[0].content
    brain._guard_prompt(masked)  # pyright: ignore[reportPrivateUsage]  # passes: nothing secret is left
    other = LLMRequest(
        purpose="t",
        tier=Tier.LOCAL,
        max_tokens=10,
        messages=[Message(role="user", source="runtime", content="DB_PASSWORD=Xk9fT2qLm8")],
    )
    with pytest.raises(SecretInPrompt):
        brain._guard_prompt(brain._mask_repository(other))  # pyright: ignore[reportPrivateUsage]
