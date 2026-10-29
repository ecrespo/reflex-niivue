"""Colormap helpers: NiiVue's built-in colormap names and label (segmentation) colormaps."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

COLORMAPS: tuple[str, ...] = (
    "actc",
    "afni_blues_inv",
    "afni_reds_inv",
    "batlow",
    "bcgwhw",
    "bcgwhw_dark",
    "blue",
    "blue2cyan",
    "blue2magenta",
    "blue2red",
    "bluegrn",
    "bone",
    "bronze",
    "cet_l17",
    "cividis",
    "cool",
    "copper",
    "copper2",
    "ct_airways",
    "ct_artery",
    "ct_bones",
    "ct_brain",
    "ct_brain_gray",
    "ct_cardiac",
    "ct_head",
    "ct_kidneys",
    "ct_liver",
    "ct_muscles",
    "ct_scalp",
    "ct_skull",
    "ct_soft",
    "ct_soft_tissue",
    "ct_surface",
    "ct_vessels",
    "ct_w_contrast",
    "cubehelix",
    "electric_blue",
    "freesurfer",
    "ge_color",
    "gold",
    "gray",
    "green",
    "green2cyan",
    "green2orange",
    "hot",
    "hotiron",
    "hsv",
    "inferno",
    "jet",
    "kry",
    "linspecer",
    "lipari",
    "magma",
    "mako",
    "navia",
    "nih",
    "plasma",
    "random",
    "red",
    "redyell",
    "rocket",
    "roi_i256",
    "surface",
    "thermal",
    "turbo",
    "violet",
    "viridis",
    "warm",
    "winter",
    "x_rain",
)
"""The names ``Niivue.colormaps()`` returns in ``@niivue/niivue`` (in NiiVue's order)."""

RGBA = Sequence[int] | str


def colormaps() -> list[str]:
    """NiiVue's built-in colormap names, for ``colormap`` in volume and layer descriptors.

    Returns:
        The names ``Niivue.colormaps()`` lists in the pinned release (``NIIVUE_VERSION``).

    """
    return list(COLORMAPS)


def _rgba(color: RGBA, label: int) -> tuple[int, int, int, int]:
    if isinstance(color, str):
        h = color.removeprefix("#")
        if len(h) not in (6, 8) or any(c not in "0123456789abcdefABCDEF" for c in h):
            msg = f"label {label}: colour {color!r} is not #rrggbb or #rrggbbaa"
            raise ValueError(msg)
        parts = [int(h[i : i + 2], 16) for i in range(0, len(h), 2)]
    else:
        parts = list(color)
    if len(parts) == 3:
        parts.append(255)
    if len(parts) != 4 or not all(
        isinstance(p, int) and not isinstance(p, bool) and 0 <= p <= 255 for p in parts
    ):
        msg = f"label {label}: colour must be 3 or 4 integers 0..255, got {color!r}"
        raise ValueError(msg)
    return parts[0], parts[1], parts[2], parts[3]


def label_colormap(
    labels: Mapping[int, tuple[str, RGBA]], *, background: bool = True
) -> dict[str, Any]:
    """Build the label colormap NiiVue expects for a segmentation (label map) volume.

    Use it as ``colormap_label`` of a volume descriptor::

        {"url": "seg.nii.gz", "colormap_label": label_colormap({
            1: ("liver", (255, 0, 0)),
            2: ("spleen", "#00ff0080"),
        })}

    Args:
        labels: Label value -> (name, colour). The colour is RGB/RGBA integers 0..255 or a
            ``#rrggbb``/``#rrggbbaa`` string; without alpha the label is opaque.
        background: Add a transparent label 0 named "background" unless ``labels`` has one,
            so that voxel value 0 stays see-through and the names in ``on_location`` line up.

    Returns:
        ``{"R": [...], "G": [...], "B": [...], "A": [...], "I": [...], "labels": [...]}``
        sorted by label value, which NiiVue turns into a lookup table (``makeLabelLut``).

    Raises:
        ValueError: For negative or non-integer label values and invalid colours.

    """
    entries: dict[int, tuple[str, tuple[int, int, int, int]]] = {}
    for value, spec in labels.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            msg = f"label values must be non-negative integers, got {value!r}"
            raise ValueError(msg)
        name, color = spec
        entries[value] = (str(name), _rgba(color, value))
    if background and 0 not in entries:
        entries[0] = ("background", (0, 0, 0, 0))
    out: dict[str, Any] = {"R": [], "G": [], "B": [], "A": [], "I": [], "labels": []}
    for value in sorted(entries):
        name, (r, g, b, a) = entries[value]
        out["R"].append(r)
        out["G"].append(g)
        out["B"].append(b)
        out["A"].append(a)
        out["I"].append(value)
        out["labels"].append(name)
    return out
