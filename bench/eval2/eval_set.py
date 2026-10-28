"""The evaluation set of evaluation v2: written and committed before it ever ran; never used to debug.

A different project (`ledger`) and different instances of each kind than the development set, so a version tuned
on the development scenarios is measured on cases it was not tuned on. `scenarios.py --set eval` writes it.
"""

from __future__ import annotations

from bench.eval2.scenarios import Scenario

PYPROJECT = """[project]
name = "ledger"
version = "1.4.2"
requires-python = ">=3.12"

[tool.ruff]
line-length = 110

[tool.ruff.lint]
select = ["E", "F", "I"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
"""
CI = """name: tests
on: [push]
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install ruff && ruff check src tests
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install -r requirements.txt && python -m pytest
"""
ACCOUNTS = '''"""Accounts and the entries that move money between them, in cents."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Account:
    name: str
    entries: list[int] = field(default_factory=list)

    def balance(self) -> int:
        return sum(self.entries)


def transfer(source: Account, target: Account, cents: int) -> None:
    if cents <= 0:
        raise ValueError("a transfer moves a positive amount")
    if source.balance() < cents:
        raise ValueError(f"{source.name} cannot cover {cents}")
    source.entries.append(-cents)
    target.entries.append(cents)
'''
POSTING = '''"""Postings read from an import file: one line per posting, `kind amount account`."""

from __future__ import annotations

from ledger.accounts import Account


def post(line: str, accounts: dict[str, Account]) -> int:
    kind, amount, name = line.split()
    cents = int(amount)
    account = accounts.setdefault(name, Account(name))
    if kind == "credit":
        account.entries.append(cents)
    elif kind == "debit":
        account.entries.append(-cents)
    else:
        raise ValueError(f"unknown posting kind {kind!r}")
    return account.balance()
'''
TESTS = """import pytest

from ledger.accounts import Account, transfer
from ledger.posting import post


def test_transfer_moves_money():
    a, b = Account("a", [500]), Account("b")
    transfer(a, b, 200)
    assert (a.balance(), b.balance()) == (300, 200)


def test_transfer_needs_funds():
    with pytest.raises(ValueError):
        transfer(Account("a"), Account("b"), 1)


def test_credit_posting():
    assert post("credit 300 cash", {}) == 300
"""
BASE = {
    "pyproject.toml": PYPROJECT,
    "requirements.txt": "pytest==8.3.3\n",
    ".github/workflows/tests.yml": CI,
    "src/ledger/__init__.py": "",
    "src/ledger/accounts.py": ACCOUNTS,
    "src/ledger/posting.py": POSTING,
    "tests/test_ledger.py": TESTS,
}

# `is` against a string literal: true only when the interpreter happens to share the object. A kind read from a file
# is a new string, so every debit read from an import is refused as unknown.
IS_LITERAL = POSTING.replace('    elif kind == "debit":', '    elif kind is "debit":')
# A mutable default: every call without `seen` shares one list, so a second import of the same file is skipped.
DEFAULT = '''"""Importing a file of postings once, skipping lines already imported."""

from __future__ import annotations

from ledger.accounts import Account
from ledger.posting import post


def import_lines(lines: list[str], accounts: dict[str, Account], seen: list[str] = []) -> int:
    done = 0
    for line in lines:
        if line in seen:
            continue
        post(line, accounts)
        seen.append(line)
        done += 1
    return done
'''
FIXTURE_TESTS = (
    TESTS
    + """

from tests.helpers import funded  # noqa: E402  (a fixture, injected by name)


def test_funded_account_can_pay(funded):
    transfer(funded, Account("shop"), 100)
    assert funded.balance() == 900
"""
)
HELPERS = """import pytest

from ledger.accounts import Account


@pytest.fixture
def funded():
    return Account("funded", [1000])
"""
EXAMPLE = """from ledger.accounts import Account,transfer
a=Account( "a",[10] );b=Account("b")
transfer(a,b,5) ; print(a.balance(),b.balance())
"""


def scenarios() -> list[Scenario]:
    is_line = IS_LITERAL.splitlines().index('    elif kind is "debit":') + 1
    default_line = (
        DEFAULT.splitlines().index(
            "def import_lines(lines: list[str], accounts: dict[str, Account], seen: list[str] = []) -> int:"
        )
        + 1
    )
    return [
        Scenario(
            "debit-identity",
            "planted_defect",
            {"src/ledger/posting.py": IS_LITERAL},
            {
                "truth": [
                    {"path": "src/ledger/posting.py", "line": is_line, "what": "debits read from a file refused"}
                ],
                "acceptable": ["run_experiment"],
                "promotion_valid": True,
            },
            hidden="""from ledger.posting import post


def test_debit_read_from_a_file():
    kind = "".join(["de", "bit"])  # a new string, as a line read from a file is
    assert post(f"{kind} 100 cash", {}) == -100
""",
        ),
        Scenario(
            "shared-default",
            "planted_defect",
            {"src/ledger/importer.py": DEFAULT},
            {
                "truth": [{"path": "src/ledger/importer.py", "line": default_line, "what": "second import skipped"}],
                "acceptable": ["run_experiment"],
                "promotion_valid": True,
            },
            hidden="""from ledger.importer import import_lines


def test_two_ledgers_import_the_same_file():
    assert import_lines(["credit 5 cash"], {}) == 1
    assert import_lines(["credit 5 cash"], {}) == 1
""",
        ),
        Scenario("healthy-ledger", "healthy", {}, {"truth": [], "acceptable": ["wait", "decline"]}),
        Scenario(
            "fixture-injection",
            "environment",
            {"tests/test_ledger.py": FIXTURE_TESTS, "tests/helpers.py": HELPERS, "tests/__init__.py": ""},
            {
                "truth": [],
                "acceptable": ["wait", "decline"],
                "note": "a fixture imported and injected by name reads as a redefinition to pyflakes (F811)",
            },
        ),
        Scenario(
            "example-style",
            "low_value",
            {"docs/examples/transfer.py": EXAMPLE},
            {"truth": [], "acceptable": ["decline", "wait"], "note": "style in examples the CI never lints"},
        ),
    ]
