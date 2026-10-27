from __future__ import annotations

from pathlib import Path

import pytest

from unbidden.lab.perf import index_candidate

pytestmark = pytest.mark.unit

MODELS = """from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column


class ItemModel(Base):
    __tablename__ = "shopping_list_items"
    label_id: Mapped[GUID | None] = mapped_column(GUID, ForeignKey("labels.id"))
    name: Mapped[str] = mapped_column(String)


class LabelSettings(Base):
    __tablename__ = "shopping_lists_multi_purpose_labels"
    label_id: Mapped[GUID] = mapped_column(GUID, ForeignKey("labels.id"), primary_key=True)
"""
HEAD = ("app/alembic/versions", "a9f823e9e441", "app/alembic/versions/x_a9f823e9e441.py")


def test_the_index_goes_on_the_column_of_the_mapped_class_and_a_migration_follows_the_head() -> None:
    files = index_candidate(lambda _: MODELS, "shopping_list_items", "label_id", "app/models.py", HEAD)
    assert files is not None
    model = files["app/models.py"]
    assert 'mapped_column(GUID, ForeignKey("labels.id"), index=True)' in model
    assert 'ForeignKey("labels.id"), primary_key=True)' in model  # the other class's label_id is untouched
    (migration,) = (text for path, text in files.items() if path.startswith("app/alembic/versions/"))
    assert 'down_revision: str | None = "a9f823e9e441"' in migration
    assert 'create_index(batch_op.f("ix_shopping_list_items_label_id"), ["label_id"]' in migration
    compile(migration, "migration.py", "exec")


def test_no_candidate_when_the_column_spans_lines_or_is_already_indexed() -> None:
    multi = MODELS.replace(
        'mapped_column(GUID, ForeignKey("labels.id"))',
        'mapped_column(\n        GUID, ForeignKey("labels.id")\n    )',
        1,
    )
    assert index_candidate(lambda _: multi, "shopping_list_items", "label_id", "m.py", HEAD) is None
    indexed = MODELS.replace('ForeignKey("labels.id"))', 'ForeignKey("labels.id"), index=True)', 1)
    assert index_candidate(lambda _: indexed, "shopping_list_items", "label_id", "m.py", HEAD) is None
    assert index_candidate(lambda _: MODELS, "nope", "label_id", "m.py", HEAD) is None


def test_the_lab_times_one_test_without_parallel_workers() -> None:
    from unbidden.lab.perf import serial

    script = "set -e\ncd /work\npytest -n auto --dist loadfile -x\necho -n done"
    assert serial(("bash", "-c", script)) == ("bash", "-c", "set -e\ncd /work\npytest -x\necho -n done")
    assert serial(("pytest", "--numprocesses=4", "tests")) == (
        "pytest",
        "--numprocesses=4",
        "tests",
    )  # argv items alone


def test_the_workload_sees_a_test_calling_the_endpoint_and_the_real_fixtures(tmp_path: Path) -> None:
    import subprocess

    from unbidden.lab.perf import PerfLab

    files = {
        "tests/utils/routes.py": 'foods_merge = "/api/foods/merge"\n',
        "tests/conftest.py": "@fixture(scope='session')\ndef api_client():\n    ...\n",
        "tests/fixtures/fixture_users.py": "@fixture(scope='module')\ndef unique_user(session, api_client):\n    ...\n",
        "tests/test_foods_merge.py": (
            "from tests.utils import routes\n\ndef test_merge(api_client):\n    api_client.put(routes.foods_merge)\n"
        ),
        "tests/test_other.py": "def test_x():\n    pass\n",
    }
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for path, text in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    lab = PerfLab.__new__(PerfLab)
    lab.repo = tmp_path
    text = lab._test_examples("HEAD", "PUT /api/foods/merge", "shopping_list_items")  # pyright: ignore[reportPrivateUsage]
    assert "`tests/test_foods_merge.py`" in text and "test_other" not in text
    assert "- `unique_user(session, api_client)` in `tests/fixtures/fixture_users.py`" in text
