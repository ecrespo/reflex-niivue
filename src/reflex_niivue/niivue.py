"""The ``Niivue`` component: NiiVue, the WebGL2 medical image viewer, for Reflex.

The browser side is ``@niivue/niivue`` from npm, wrapped by ``assets/niivue.jsx``. Props carry
URLs and display settings only; NiiVue downloads volumes and meshes itself, so no image data
passes through Reflex state.

Imperative actions (save the drawing, undo, move the crosshair, ...) are functions returning an
event, to be returned or yielded from an event handler or used as an event trigger::

    def save(self):
        yield niivue.save_image("mask.nii.gz")

    rx.button("Undo", on_click=niivue.undo_draw())
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

import reflex as rx
from reflex import constants
from reflex.components.component import NoSSRComponent
from reflex.environment import EnvironmentVariables
from reflex.event import EventSpec
from reflex.vars import Var

NIIVUE_VERSION = "0.69.0"
"""The ``@niivue/niivue`` release the wrapper is pinned to."""

SliceType = Literal["axial", "coronal", "sagittal", "multiplanar", "render"]
MultiplanarLayout = Literal["auto", "column", "grid", "row"]
DragMode = Literal[
    "none",
    "contrast",
    "measurement",
    "pan",
    "slicer3d",
    "callback_only",
    "roi_selection",
    "angle",
    "crosshair",
    "windowing",
]

# These tables are mirrored in assets/niivue.jsx (between the <tables> markers); the tests
# check that both sides agree.
SLICE_TYPES: dict[str, int] = {
    "axial": 0,
    "coronal": 1,
    "sagittal": 2,
    "multiplanar": 3,
    "render": 4,
}
"""``slice_type`` values and NiiVue's ``SLICE_TYPE`` enum."""
MULTIPLANAR_LAYOUTS: dict[str, int] = {"auto": 0, "column": 1, "grid": 2, "row": 3}
"""``multiplanar_layout`` values and NiiVue's ``MULTIPLANAR_TYPE`` enum."""
DRAG_MODES: dict[str, int] = {
    "none": 0,
    "contrast": 1,
    "measurement": 2,
    "pan": 3,
    "slicer3d": 4,
    "callback_only": 5,
    "roi_selection": 6,
    "angle": 7,
    "crosshair": 8,
    "windowing": 9,
}
"""``drag_mode`` values (right-button drag) and NiiVue's ``DRAG_MODE`` enum."""
PROP_OPTIONS: dict[str, str] = {
    "slice_type": "sliceType",
    "multiplanar_layout": "multiplanarLayout",
    "show_3d_crosshair": "show3Dcrosshair",
    "crosshair_color": "crosshairColor",
    "crosshair_width": "crosshairWidth",
    "back_color": "backColor",
    "drag_mode": "dragMode",
    "is_colorbar": "isColorbar",
    "is_orient_cube": "isOrientCube",
    "is_radiological": "isRadiologicalConvention",
    "pen_value": "penValue",
}
"""Props that are also NiiVue constructor options: prop name -> option name."""
VOLUME_KEYS: dict[str, str] = {
    "colormap_label": "colormapLabel",
    "colormap_negative": "colormapNegative",
    "cal_min_neg": "cal_minNeg",
    "cal_max_neg": "cal_maxNeg",
    "frame_4d": "frame4D",
    "limit_frames_4d": "limitFrames4D",
    "ignore_zero_voxels": "ignoreZeroVoxels",
    "trust_cal_min_max": "trustCalMinMax",
    "percentile_frac": "percentileFrac",
    "colorbar_visible": "colorbarVisible",
    "alpha_threshold": "alphaThreshold",
    "use_qform_not_sform": "useQFormNotSForm",
    "url_image_data": "urlImageData",
    "image_type": "imageType",
}
"""snake_case keys accepted in volume descriptors -> NiiVue ``ImageFromUrlOptions`` keys.

Any other key is passed to NiiVue unchanged (``url``, ``name``, ``colormap``, ``opacity``,
``cal_min``, ``cal_max``, ``headers``, ...). ``visible`` is handled by the wrapper.
"""
MESH_KEYS: dict[str, str] = {
    "mesh_shader_index": "meshShaderIndex",
    "colorbar_visible": "colorbarVisible",
}
"""snake_case keys accepted in mesh descriptors -> NiiVue ``LoadFromUrlParams`` keys."""
LAYER_KEYS: dict[str, str] = {
    "colormap_negative": "colormapNegative",
    "use_negative_cmap": "useNegativeCmap",
    "cal_min_neg": "cal_minNeg",
    "cal_max_neg": "cal_maxNeg",
    "colorbar_visible": "colorbarVisible",
    "show_legend": "showLegend",
    "outline_border": "outlineBorder",
}
"""snake_case keys accepted in mesh layer descriptors -> NiiVue ``NVMeshLayer`` keys."""


def _link_assets() -> str:
    """Link the wrapper into the compiling app; return its import path.

    Links are only created inside a Reflex app (``rxconfig.py`` in the working directory).
    Anywhere else (build hooks, tests, scripts) importing the component must not drop
    symlinks into the working directory; the import path is the same either way.
    """
    if not (Path.cwd() / constants.Config.FILE).is_file():
        module = __name__.replace(".", "/")
        return f"$/public/{constants.Dirs.EXTERNAL_APP_ASSETS}/{module}/assets/niivue.jsx"
    if not EnvironmentVariables.REFLEX_BACKEND_ONLY.get():
        # rx.asset creates the module's folder but not the assets/ subfolder.
        external = Path.cwd() / constants.Dirs.APP_ASSETS / constants.Dirs.EXTERNAL_APP_ASSETS
        (external / __name__.replace(".", "/") / "assets").mkdir(parents=True, exist_ok=True)
    return rx.asset("assets/niivue.jsx", shared=True, _stack_level=2).importable_path


# ------------------------------------------------------------------- event specs
def _location_spec(
    mm: Var[list[float]],
    vox: Var[list[int]],
    values: Var[list[dict[str, Any]]],
    frac: Var[list[float]],
) -> tuple[Var[list[float]], Var[list[int]], Var[list[dict[str, Any]]], Var[list[float]]]:
    """``on_location``: crosshair in world mm, background voxel, per-layer values, fraction.

    Each entry of ``values`` is ``{"name", "id", "value", "vox", "mm"}`` for one volume.
    """
    return mm, vox, values, frac


def _image_loaded_spec(name: Var[str], dims: Var[list[int]]) -> tuple[Var[str], Var[list[int]]]:
    """``on_image_loaded``: the volume's name and its NIfTI dimensions (x, y, z[, t])."""
    return name, dims


def _name_spec(name: Var[str]) -> tuple[Var[str]]:
    """``on_mesh_loaded``: the mesh's name."""
    return (name,)


def _frame_time_spec(ms: Var[float]) -> tuple[Var[float]]:
    """``on_frame_time_ms``: mean time of a NiiVue redraw, reported at most once per second."""
    return (ms,)


def _frame_change_spec(name: Var[str], frame: Var[int]) -> tuple[Var[str], Var[int]]:
    """``on_frame_change``: a 4D volume's name and its displayed frame (0-based)."""
    return name, frame


def _intensity_spec(volume: Var[dict[str, Any]]) -> tuple[Var[dict[str, Any]]]:
    """``on_intensity_change``: ``{"name", "id", "index", "cal_min", "cal_max"}``."""
    return (volume,)


def _drawing_spec(action: Var[str]) -> tuple[Var[str]]:
    """``on_drawing_changed``: ``"draw"``, ``"undo"``, ``"load"`` or ``"close"``."""
    return (action,)


def _no_args_spec() -> tuple[()]:
    """``on_volume_updated``: no arguments."""
    return ()


def _message_spec(message: Var[str]) -> tuple[Var[str]]:
    """``on_error``: a human-readable message."""
    return (message,)


# -------------------------------------------------------------------- validation
def _is_literal(value: Any) -> bool:
    return value is not None and not isinstance(value, Var)


def _check_choice(name: str, value: Any, allowed: Iterable[str]) -> None:
    allowed = tuple(allowed)
    if _is_literal(value) and value not in allowed:
        msg = f"{name} must be one of {', '.join(map(repr, allowed))}, got {value!r}"
        raise ValueError(msg)


def _check_numbers(name: str, value: Any, length: int) -> None:
    if not _is_literal(value):
        return
    if isinstance(value, list | tuple) and any(isinstance(v, Var) for v in value):
        return  # e.g. [State.azimuth, State.elevation]
    if (
        isinstance(value, str | bytes)
        or not isinstance(value, Sequence)
        or len(value) != length
        or not all(isinstance(v, int | float) and not isinstance(v, bool) for v in value)
    ):
        msg = f"{name} must be {length} numbers, got {value!r}"
        raise ValueError(msg)


def _check_descriptors(name: str, value: Any) -> None:
    if not isinstance(value, list | tuple):
        return
    for item in value:
        if isinstance(item, Mapping) and not ("url" in item or "name" in item):
            msg = f"each entry of {name} needs a 'url'; got {dict(item)!r}"
            raise ValueError(msg)


def _validate(props: dict[str, Any]) -> None:
    """Reject literal prop values NiiVue would silently ignore."""
    _check_choice("slice_type", props.get("slice_type"), SLICE_TYPES)
    _check_choice("multiplanar_layout", props.get("multiplanar_layout"), MULTIPLANAR_LAYOUTS)
    _check_choice("drag_mode", props.get("drag_mode"), DRAG_MODES)
    _check_numbers("crosshair_color", props.get("crosshair_color"), 4)
    _check_numbers("back_color", props.get("back_color"), 4)
    _check_numbers("clip_plane", props.get("clip_plane"), 3)
    _check_numbers("render_azimuth_elevation", props.get("render_azimuth_elevation"), 2)
    _check_descriptors("volumes", props.get("volumes"))
    _check_descriptors("meshes", props.get("meshes"))
    opacity = props.get("draw_opacity")
    if opacity is not None and not isinstance(opacity, Var) and not 0 <= float(opacity) <= 1:
        msg = f"draw_opacity must be between 0 and 1, got {opacity!r}"
        raise ValueError(msg)
    pen = props.get("pen_value")
    if _is_literal(pen) and (isinstance(pen, bool) or not isinstance(pen, int) or pen < 0):
        msg = f"pen_value must be a non-negative integer, got {pen!r}"
        raise ValueError(msg)


def niivue_options(**props: Any) -> dict[str, Any]:
    """NiiVue constructor options for literal prop values, as the wrapper computes them.

    ``options`` is the base; the dedicated props override it. Useful to check what a
    configuration means for NiiVue (see ``DEFAULT_OPTIONS`` in the NiiVue docs).

    Args:
        **props: Component props (snake_case), e.g. ``slice_type="render"``.

    Returns:
        The options passed to ``new Niivue(...)``.

    """
    _validate(props)
    opts = dict(props.get("options") or {})
    enums = {
        "slice_type": SLICE_TYPES,
        "multiplanar_layout": MULTIPLANAR_LAYOUTS,
        "drag_mode": DRAG_MODES,
    }
    for prop, option in PROP_OPTIONS.items():
        value = props.get(prop)
        if value is None:
            continue
        opts[option] = enums[prop][value] if prop in enums else value
    return opts


# --------------------------------------------------------------------- component
class Niivue(NoSSRComponent):
    """NiiVue viewer: volumes, overlays, label maps, meshes and drawings on a WebGL2 canvas.

    Wraps ``@niivue/niivue`` (BSD-2-Clause). Needs WebGL2 in the browser.
    """

    library = _link_assets()

    tag = "NiivueView"

    lib_dependencies: list[str] = [f"@niivue/niivue@{NIIVUE_VERSION}"]

    # Volume layers, background first. Each is a NiiVue volume descriptor: ``url`` (required),
    # ``name``, ``colormap``, ``opacity``, ``cal_min``, ``cal_max``, ``visible`` and
    # ``colormap_label`` (see ``label_colormap``), plus any other NiiVue ``ImageFromUrlOptions``.
    # Diffed by url (or name): unchanged volumes are updated in place, not downloaded again.
    volumes: rx.Var[list[dict[str, Any]]]

    # Meshes: ``url`` (required), ``name``, ``rgba255``, ``opacity``, ``visible`` and
    # ``layers`` (``[{"url", "colormap", "opacity", "cal_min", "cal_max", ...}]``).
    meshes: rx.Var[list[dict[str, Any]]]

    # "axial", "coronal", "sagittal", "multiplanar" or "render".
    slice_type: rx.Var[str]

    # Arrangement of the multiplanar tiles: "auto", "column", "grid" or "row".
    multiplanar_layout: rx.Var[str]

    # Show the crosshair in the 3D render.
    show_3d_crosshair: rx.Var[bool]

    # Crosshair colour, RGBA 0..1.
    crosshair_color: rx.Var[list[float]]

    # Crosshair width in pixels.
    crosshair_width: rx.Var[float]

    # Background colour, RGBA 0..1.
    back_color: rx.Var[list[float]]

    # Right-button drag: "none", "contrast", "measurement", "pan", "slicer3d", ...
    drag_mode: rx.Var[str]

    # Show the colorbar (of ``selected_volume`` when set).
    is_colorbar: rx.Var[bool]

    # Show the orientation cube in the 3D render.
    is_orient_cube: rx.Var[bool]

    # Radiological convention (patient left on screen right).
    is_radiological: rx.Var[bool]

    # Clip plane of the 3D render: [depth, azimuth, elevation]; depth 2 or more turns it off.
    clip_plane: rx.Var[list[float]]

    # Camera of the 3D render: [azimuth, elevation] in degrees.
    render_azimuth_elevation: rx.Var[list[float]]

    # Index of the layer whose colorbar is shown and that ``set_frame_4d``/``save_image``
    # act on by default.
    selected_volume: rx.Var[int]

    # Left-button drawing on the slices (creates an empty drawing if there is none).
    drawing_enabled: rx.Var[bool]

    # Label value the pen draws (0 erases).
    pen_value: rx.Var[int]

    # Opacity of the drawing layer, 0..1.
    draw_opacity: rx.Var[float]

    # Whether filled-pen strokes overwrite existing drawing labels.
    drawing_fill_overwrites: rx.Var[bool]

    # Extra NiiVue constructor options (``NVConfigOptions``, camelCase), e.g.
    # ``{"isFilledPen": True, "textHeight": 0.04}``. The dedicated props take precedence.
    options: rx.Var[dict[str, Any]]

    # Viewers with the same group share crosshair, pan/zoom and 3D camera (``broadcastTo``).
    sync_group: rx.Var[str]

    # What a sync group shares: NiiVue sync options, default ``{"2d": True, "3d": True}``.
    sync_opts: rx.Var[dict[str, bool]]

    # The crosshair moved (click, drag, arrow keys); throttled to one event per 50 ms.
    on_location: rx.EventHandler[_location_spec]

    # A volume finished loading.
    on_image_loaded: rx.EventHandler[_image_loaded_spec]

    # A mesh finished loading.
    on_mesh_loaded: rx.EventHandler[_name_spec]

    # Mean redraw time in ms, at most once per second while NiiVue draws.
    on_frame_time_ms: rx.EventHandler[_frame_time_spec]

    # A 4D volume shows another frame.
    on_frame_change: rx.EventHandler[_frame_change_spec]

    # The display range of a volume changed (contrast drag).
    on_intensity_change: rx.EventHandler[_intensity_spec]

    # The drawing changed: "draw", "undo", "load" or "close".
    on_drawing_changed: rx.EventHandler[_drawing_spec]

    # NiiVue updated its GPU volumes (layers, colormaps, ranges).
    on_volume_updated: rx.EventHandler[_no_args_spec]

    # WebGL2 is missing or a download/parse failed.
    on_error: rx.EventHandler[_message_spec]

    @classmethod
    def create(cls, *children, **props) -> Niivue:
        """Create the viewer.

        Args:
            *children: Not supported; NiiVue renders into its own canvas.
            **props: The component props; ``width``/``height`` default to ``100%``/``480px``.

        Returns:
            The component.

        Raises:
            ValueError: For children or for invalid literal prop values.

        """
        if children:
            msg = "niivue.view does not take children"
            raise ValueError(msg)
        _validate(props)
        props.setdefault("width", "100%")
        props.setdefault("height", "480px")
        return super().create(**props)  # type: ignore[return-value]


view = Niivue.create


# -------------------------------------------------------------- imperative helpers
def _js(value: Any) -> str:
    """Return a JavaScript expression for ``value``: JSON for literals, an expression for Vars."""
    if isinstance(value, Var):
        # Interpolated into the script's text as JSON, which is a JavaScript literal.
        return f"{value.to_string()}"
    return json.dumps(value)


def _command(name: str, *args: Any, id: str | Var[str] | None = None) -> EventSpec:
    """Return an event running ``window.reflexNiivue.command(name, id, *args)`` in the browser."""
    call = ", ".join(_js(a) for a in (name, id, *args))
    return rx.call_script(f"window.reflexNiivue?.command({call})")


def move_crosshair_to_mm(mm: Sequence[float] | Var, *, id: str | None = None) -> EventSpec:
    """Move the crosshair to world coordinates ``[x, y, z]`` in mm (fires ``on_location``).

    Args:
        mm: The target position.
        id: The viewer's ``id``; default: the most recently mounted viewer.

    Returns:
        The event.

    """
    return _command("moveCrosshairToMm", list(mm) if not isinstance(mm, Var) else mm, id=id)


def set_frame_4d(
    frame: int | Var, volume: int | str | None = None, *, id: str | None = None
) -> EventSpec:
    """Show frame ``frame`` (0-based) of a 4D volume.

    Args:
        frame: The frame.
        volume: Layer index, name or url; default: ``selected_volume`` (else the background).
        id: The viewer's ``id``; default: the most recently mounted viewer.

    Returns:
        The event.

    """
    return _command("setFrame4D", frame, volume, id=id)


def save_image(
    filename: str = "image.nii.gz",
    *,
    drawing: bool | None = None,
    volume: int | str | None = None,
    id: str | None = None,
) -> EventSpec:
    """Download a NIfTI file: the drawing, or a volume layer.

    Args:
        filename: Name of the downloaded file.
        drawing: True saves the drawing, False a volume; default: the drawing if there is one.
        volume: Layer index, name or url to save; default: ``selected_volume`` (else 0).
        id: The viewer's ``id``; default: the most recently mounted viewer.

    Returns:
        The event.

    """
    return _command("saveImage", filename, drawing, volume, id=id)


def save_scene(filename: str = "niivue.png", *, id: str | None = None) -> EventSpec:
    """Download a PNG screenshot of the canvas.

    Args:
        filename: Name of the downloaded file.
        id: The viewer's ``id``; default: the most recently mounted viewer.

    Returns:
        The event.

    """
    return _command("saveScene", filename, id=id)


def set_slice_mm(is_slice_mm: bool = True, *, id: str | None = None) -> EventSpec:
    """Draw 2D slices in world space (True) or voxel space (False).

    Args:
        is_slice_mm: World space if True.
        id: The viewer's ``id``; default: the most recently mounted viewer.

    Returns:
        The event.

    """
    return _command("setSliceMM", is_slice_mm, id=id)


def undo_draw(*, id: str | None = None) -> EventSpec:
    """Undo the last drawing stroke.

    Args:
        id: The viewer's ``id``; default: the most recently mounted viewer.

    Returns:
        The event.

    """
    return _command("undoDraw", id=id)


def clear_drawing(*, id: str | None = None) -> EventSpec:
    """Erase the drawing (a new empty one is created while drawing is enabled).

    Args:
        id: The viewer's ``id``; default: the most recently mounted viewer.

    Returns:
        The event.

    """
    return _command("clearDrawing", id=id)


def load_drawing_from_url(
    url: str | Var, *, binarize: bool = False, id: str | None = None
) -> EventSpec:
    """Load a NIfTI drawing with the background image's dimensions.

    Args:
        url: The drawing's URL.
        binarize: Force the labels to 0/1.
        id: The viewer's ``id``; default: the most recently mounted viewer.

    Returns:
        The event.

    """
    return _command("loadDrawingFromUrl", url, binarize, id=id)


def reset_view(*, id: str | None = None) -> EventSpec:
    """Reset pan/zoom, the crosshair (image centre) and the 3D camera.

    Args:
        id: The viewer's ``id``; default: the most recently mounted viewer.

    Returns:
        The event.

    """
    return _command("resetView", id=id)
