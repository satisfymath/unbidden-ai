from __future__ import annotations

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
