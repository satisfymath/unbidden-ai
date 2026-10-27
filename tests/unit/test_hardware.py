from __future__ import annotations

import pytest

from unbidden.brain.hardware import Machine, recommend

pytestmark = pytest.mark.unit


def mac(gb: float) -> Machine:
    return Machine(gb, True, 0.0, "Apple")


@pytest.mark.parametrize(
    ("machine", "expected", "hint"),
    [
        (mac(64), "muse-glimmer:30b-mxfp8-dflash", None),
        (mac(36), "muse-glimmer:30b-mlx", None),
        (mac(18), "llama3.1:8b", "frontier"),
        (mac(12), "llama3.1:8b", "frontier"),
        (mac(8), "llama3.2:3b", "frontier"),
        (Machine(128, False, 24, "x86"), "muse-glimmer:30b-q4_K_M", None),
        (Machine(32, False, 8, "x86"), "llama3.1:8b", "frontier"),
    ],
)
def test_the_best_model_that_fits(machine: Machine, expected: str, hint: str | None) -> None:
    rec = recommend(machine, set())
    assert rec.model.tag == expected and rec.fits and rec.profile_hint == hint


def test_an_installed_model_that_fits_beats_a_download() -> None:
    rec = recommend(mac(64), {"muse-glimmer:30b-mlx"})
    assert rec.model.tag == "muse-glimmer:30b-mlx" and rec.installed and "download" in rec.reason


def test_nothing_fits() -> None:
    rec = recommend(mac(4), set())
    assert not rec.fits and rec.profile_hint == "frontier"
