"""Colormap helpers."""

import re
from pathlib import Path

import pytest

from reflex_niivue import COLORMAPS, colormaps, label_colormap


def test_colormaps_are_niivues_names():
    names = colormaps()
    assert names == list(COLORMAPS)
    assert len(names) == len(set(names)) == 70
    for name in ("gray", "hot", "warm", "winter", "viridis", "ct_bones", "freesurfer", "x_rain"):
        assert name in names
    # NiiVue hides the "$"-prefixed label lookup tables from colormaps().
    assert not any(n.startswith("$") for n in names)
    assert all(re.fullmatch(r"[a-z0-9_]+", n) for n in names)


def test_colormaps_returns_a_copy():
    colormaps().append("x")
    assert "x" not in colormaps()


def test_label_colormap_shape():
    cm = label_colormap({2: ("spleen", "#00ff0080"), 1: ("liver", (255, 0, 0))})
    assert cm == {
        "R": [0, 255, 0],
        "G": [0, 0, 255],
        "B": [0, 0, 0],
        "A": [0, 255, 128],
        "I": [0, 1, 2],
        "labels": ["background", "liver", "spleen"],
    }


def test_label_colormap_without_background_and_explicit_zero():
    assert label_colormap({5: ("x", (1, 2, 3, 4))}, background=False) == {
        "R": [1],
        "G": [2],
        "B": [3],
        "A": [4],
        "I": [5],
        "labels": ["x"],
    }
    cm = label_colormap({0: ("air", (9, 9, 9, 9)), 1: ("a", (1, 1, 1))})
    assert cm["labels"] == ["air", "a"] and cm["A"] == [9, 255]


@pytest.mark.parametrize(
    "labels",
    [
        {-1: ("x", (0, 0, 0))},
        {1.5: ("x", (0, 0, 0))},
        {True: ("x", (0, 0, 0))},
        {1: ("x", (0, 0))},
        {1: ("x", (0, 0, 256))},
        {1: ("x", "#12345")},
        {1: ("x", "red")},
    ],
)
def test_label_colormap_rejects_bad_input(labels):
    with pytest.raises(ValueError):
        label_colormap(labels)


def test_colormap_list_matches_an_installed_niivue_if_any():
    """Cross-check against @niivue/niivue in a compiled demo (.web/node_modules), if present."""
    root = Path(__file__).resolve().parents[1]
    js = root / "niivue_demo/.web/node_modules/@niivue/niivue/build/niivue/index.js"
    if not js.is_file():
        pytest.skip("no compiled demo with @niivue/niivue installed")
    text = js.read_text()
    block = re.search(r"__export\(cmaps_exports, \{(.*?)\n\}\);", text, re.S)
    assert block
    names = sorted(n for n in re.findall(r"^\s+(\$?\w+):", block.group(1), re.M) if n[0] != "$")
    assert sorted(COLORMAPS) == names
