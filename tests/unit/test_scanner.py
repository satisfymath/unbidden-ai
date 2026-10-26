from __future__ import annotations

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
    ],
)
def test_ignores_placeholders(text: str) -> None:
    assert not secret_hits(scan(text)), text


def test_redaction_keeps_a_prefix_and_is_idempotent() -> None:
    text = f"push with {FAKE_GH} now"
    once = redact_text(text)
    assert FAKE_GH not in once
    assert "ghp***" in once
    assert redact_text(once) == once


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
