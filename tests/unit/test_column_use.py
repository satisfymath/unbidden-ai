from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from unbidden.contracts.common import EpistemicStatus, EvidenceRef
from unbidden.contracts.world import Resource, WorldModel
from unbidden.world.column_use import column_users

pytestmark = pytest.mark.unit

FILES = {
    "app/db/models.py": (
        "class ShoppingListItem(Base):\n"
        '    __tablename__ = "shopping_list_items"\n'
        "    food_id: Mapped[GUID] = mapped_column(GUID)\n"
        "    unit_id: Mapped[GUID] = mapped_column(GUID)\n"
    ),
    "app/repos/repository_foods.py": (
        "class RepositoryFood:\n"
        "    def get_empty(self):\n"
        "        return select(ShoppingListItem.id).where(ShoppingListItem.food_id == Food.id)\n\n"
        "    def merge(self, a, b):\n"
        "        return a\n"
    ),
    "app/repos/repository_units.py": (
        "class RepositoryUnit:\n"
        "    def merge(self, a, b):\n"
        "        update(ShoppingListItem).where(ShoppingListItem.unit_id == a)\n"
    ),
    "app/services/unit_utils.py": "def merge(a, b):\n    return a\n",
    "app/routes/units.py": (
        "class Units:\n"
        '    @router.get("")\n'
        "    def get_all(self):\n"
        "        return self.repo.page_all()\n\n"
        '    @router.put("/merge")\n'
        "    def merge_one(self, data):\n"
        "        self.repo.merge(data.a, data.b)\n"
    ),
    "app/routes/foods.py": (
        "class Foods:\n"
        '    @router.get("")\n'
        "    def get_all(self):\n"
        "        return self.repo.page_all()\n\n"
        '    @router.get("/empty")\n'
        "    def get_empty(self):\n"
        "        return self.repo.get_empty()\n\n"
        '    @router.put("/merge")\n'
        "    def merge_one(self, data):\n"
        "        self.repo.merge(data.a, data.b)\n"
    ),
}
ENDPOINTS = {
    "GET /api/units": ("app/routes/units.py", 2),
    "PUT /api/units/merge": ("app/routes/units.py", 6),
    "GET /api/foods": ("app/routes/foods.py", 2),
    "GET /api/foods/empty": ("app/routes/foods.py", 6),
    "PUT /api/foods/merge": ("app/routes/foods.py", 10),
}


@pytest.fixture
def setup(tmp_path: Path) -> tuple[Path, WorldModel]:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    world = WorldModel(rev="HEAD")
    for name, (file, line) in ENDPOINTS.items():
        world.add(
            Resource(
                id=f"endpoint:{name}",
                kind="endpoint",
                name=name,
                attributes={"file": file, "line": line},
                status=EpistemicStatus.OBSERVED,
                confidence=1.0,
                evidence=[EvidenceRef(kind="config", locator="openapi")],
            )
        )
    return tmp_path, world


def test_only_handlers_that_reach_a_filter_on_the_column_are_affected(setup: tuple[Path, WorldModel]) -> None:
    repo, world = setup
    food = column_users(repo, "HEAD", world, "shopping_list_items", "food_id")
    assert [(e, u.function) for e, u in food] == [("GET /api/foods/empty", "get_empty")]  # foods' merge does not filter


def test_a_call_reaches_the_definition_named_like_its_handler_and_receiver(setup: tuple[Path, WorldModel]) -> None:
    repo, world = setup
    unit = column_users(repo, "HEAD", world, "shopping_list_items", "unit_id")
    # units.py's `self.repo.merge` is repository_units' merge, not unit_utils' nor repository_foods'.
    assert [(e, u.file) for e, u in unit] == [("PUT /api/units/merge", "app/repos/repository_units.py")]


def test_a_flask_sqlalchemy_model_without_tablename_maps_to_its_snake_case_name() -> None:
    from unbidden.world.column_use import default_table_name, mapped_classes

    sources = {
        "app/models.py": (
            "class Project(db.Model):\n    id = db.Column(db.String(64), primary_key=True)\n\n"
            "class Bill(db.Model):\n    payer_id = db.Column(db.Integer, db.ForeignKey('person.id'))\n\n"
            "class ShoppingList(db.Model):\n    pass\n\n"
            "class Renamed(db.Model):\n    __tablename__ = 'other_name'\n\n"
            "class BillType(Enum):\n    EXPENSE = 'Expense'\n"
        )
    }
    assert default_table_name("ShoppingList") == "shopping_list" and default_table_name("Bill") == "bill"
    assert mapped_classes(sources, "bill") == ["Bill"]
    assert mapped_classes(sources, "shopping_list") == ["ShoppingList"]
    assert mapped_classes(sources, "other_name") == ["Renamed"] and mapped_classes(sources, "renamed") == []
    assert mapped_classes(sources, "bill_type") == [], "an Enum is not a model"


def _repo_with(tmp_path: Path, files: dict[str, str]) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for path, text in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    return tmp_path


def _endpoint(name: str, file: str, line: int) -> Resource:
    return Resource(
        id=f"endpoint:{name}",
        kind="endpoint",
        name=name,
        attributes={"file": file, "line": line},
        status=EpistemicStatus.INFERRED,
        confidence=0.7,
        evidence=[EvidenceRef(kind="file", locator=file)],
    )


def test_a_view_that_filters_inline_and_a_call_to_the_only_definition_both_count(tmp_path: Path) -> None:
    """ihatemoney's shapes: `list_bills` filters `Bill.payer_id` in its own body, and
    `g.project.get_bills_unordered()` reaches the one `get_bills_unordered` the repository defines, though
    `models.py` and `web.py` share no word."""
    repo = _repo_with(tmp_path, {
        "ihatemoney/models.py": (
            "class Bill(db.Model):\n    payer_id = db.Column(db.Integer)\n\n"
            "class Project(db.Model):\n"
            "    def get_bills_unordered(self):\n"
            "        return Bill.query.join(Person).filter(Bill.payer_id == Person.id)\n"
        ),
        "ihatemoney/web.py": (
            '@main.route("/<project_id>/")\n'
            "def list_bills():\n"
            "    bills = g.project.get_bills_unordered()\n"
            "    return render(bills)\n\n"
            '@main.route("/<project_id>/statistics")\n'
            "def statistics():\n"
            "    rows = Bill.query.filter(Bill.payer_id == g.member.id)\n"
            "    return render(rows)\n\n"
            '@main.route("/healthcheck")\n'
            "def health():\n    return 'OK'\n"
        ),
    })  # fmt: skip
    world = WorldModel(rev="HEAD")
    world.add(_endpoint("GET /{project_id}/", "ihatemoney/web.py", 2))
    world.add(_endpoint("GET /{project_id}/statistics", "ihatemoney/web.py", 7))
    world.add(_endpoint("GET /healthcheck", "ihatemoney/web.py", 12))
    found = column_users(repo, "HEAD", world, "bill", "payer_id")
    assert {name: (u.file, u.function) for name, u in found} == {
        "GET /{project_id}/": ("ihatemoney/models.py", "get_bills_unordered"),
        "GET /{project_id}/statistics": ("ihatemoney/web.py", "statistics"),
    }
