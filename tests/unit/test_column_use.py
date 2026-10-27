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
