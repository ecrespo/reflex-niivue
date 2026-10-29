"""Every feature of ``reflex_niivue`` on NiiVue's public demo images (or offline data).

The viewers only need static files: NiiVue's demo images on https://niivue.com/demos/images/,
or, offline, a synthetic phantom that ``synthetic.py`` writes into ``assets/``. The demo
switches to the offline data by itself when a download fails (or with NIIVUE_DEMO_OFFLINE=1).
"""

from __future__ import annotations

import os
import re
from typing import Any

import reflex as rx

from reflex_niivue import colormaps, label_colormap, niivue

from . import synthetic

synthetic.write_all()

REMOTE = "https://niivue.com/demos/images/"
SOURCES: dict[str, dict[str, Any]] = {
    "remote": {
        "t1": REMOTE + "mni152.nii.gz",
        "labels": REMOTE + "hippo.nii.gz",
        "label_names": {9: ("hippocampus", (255, 70, 70, 255))},
        "series": REMOTE + "pcasl.nii.gz",
        "mesh": REMOTE + "BrainMesh_ICBM152.lh.mz3",
        "mesh_layer": REMOTE + "BrainMesh_ICBM152.lh.motor.mz3",
        "layer_range": (2.0, 5.0),
        "drawing": "/generated/mni152_drawing.nii.gz",
    },
    "offline": {
        "t1": "/synthetic/head.nii.gz",
        "labels": "/synthetic/labels.nii.gz",
        "label_names": {
            1: (synthetic.LABELS[1], (255, 70, 70, 255)),
            2: (synthetic.LABELS[2], (70, 160, 255, 255)),
            3: (synthetic.LABELS[3], (255, 220, 60, 255)),
        },
        "series": "/synthetic/series4d.nii.gz",
        "mesh": "/synthetic/sphere.mz3",
        "mesh_layer": "/synthetic/sphere_layer.mz3",
        "layer_range": (1.0, 5.0),
        "drawing": "/synthetic/drawing.nii.gz",
    },
}
COLORMAPS = colormaps()
# Download failures (as opposed to e.g. a bad file), after which the offline data is used.
_NETWORK_ERROR = re.compile(r"failed to fetch|networkerror|load failed|not found|http \d{3}", re.I)
PENS = {"0 eraser": 0, "1 red": 1, "2 green": 2, "3 blue": 3, "6 yellow": 6}
CROSSHAIRS = {"red": [1, 0, 0, 1], "green": [0, 1, 0, 1], "cyan": [0, 0.9, 1, 1]}


def _hex_to_rgba255(color: str, alpha: int = 255) -> list[int]:
    h = color.removeprefix("#")
    return [int(h[i : i + 2], 16) for i in (0, 2, 4)] + [alpha]


class DemoState(rx.State):
    """What the page controls and what the viewers report back."""

    offline: bool = os.environ.get("NIIVUE_DEMO_OFFLINE") == "1"
    notice: str = ""

    # (a) volume + overlay
    bg_colormap: str = "gray"
    overlay_mode: str = "labels"
    overlay_colormap: str = "warm"
    overlay_opacity: float = 0.8
    overlay_visible: bool = True
    colorbar: bool = True
    radiological: bool = False
    drag_mode: str = "contrast"
    crosshair: str = "red"
    # (b) multiplanar / render
    slice_type: str = "render"
    layout: str = "auto"
    azimuth: float = 110.0
    elevation: float = 15.0
    clip_on: bool = False
    clip_depth: float = 0.0
    clip_azimuth: float = 270.0
    clip_elevation: float = 0.0
    crosshair_3d: bool = True
    orient_cube: bool = True
    # (c) drawing
    drawing: bool = True
    pen: str = "1 red"
    draw_opacity: float = 0.8
    fill_overwrites: bool = True
    # (d) meshes
    mesh_color: str = "#d9d9d9"
    mesh_opacity: float = 1.0
    mesh_visible: bool = True
    layer_opacity: float = 0.8
    mesh_over_volume: bool = True
    # (e) sync
    synced: bool = True
    # (g) 4D and tools
    frame: int = 0
    frames: int = 1
    target_mm: str = "0, -20, 10"

    # (f) what the viewers report
    location: dict[str, Any] = {}
    frame_ms: float = 0.0
    events: list[str] = []
    intensity: str = ""
    volume_updates: int = 0

    # ------------------------------------------------------------ sources
    @rx.var
    def source(self) -> dict[str, Any]:
        """URLs of the images in use."""
        return SOURCES["offline" if self.offline else "remote"]

    @rx.var
    def overlay_volumes(self) -> list[dict[str, Any]]:
        """(a) The background plus a label map or a heat-map overlay."""
        src = self.source
        overlay: dict[str, Any] = {
            "url": src["labels"],
            "name": "overlay",
            "opacity": self.overlay_opacity,
            "visible": self.overlay_visible,
        }
        if self.overlay_mode == "labels":
            overlay["colormap_label"] = label_colormap(src["label_names"])
        else:
            top = max(src["label_names"])
            overlay |= {"colormap": self.overlay_colormap, "cal_min": 0.5, "cal_max": top}
        return [{"url": src["t1"], "name": "t1", "colormap": self.bg_colormap}, overlay]

    @rx.var
    def t1_volume(self) -> list[dict[str, Any]]:
        """The background alone."""
        return [{"url": self.source["t1"], "name": "t1"}]

    @rx.var
    def series_volume(self) -> list[dict[str, Any]]:
        """(g) The 4D series."""
        return [{"url": self.source["series"], "name": "series", "colormap": "inferno"}]

    @rx.var
    def mesh_list(self) -> list[dict[str, Any]]:
        """(d) A surface with a scalar layer."""
        src = self.source
        lo, hi = src["layer_range"]
        return [
            {
                "url": src["mesh"],
                "name": "surface",
                "rgba255": _hex_to_rgba255(self.mesh_color),
                "opacity": self.mesh_opacity,
                "visible": self.mesh_visible,
                "layers": [
                    {
                        "url": src["mesh_layer"],
                        "colormap": "warm",
                        "cal_min": lo,
                        "cal_max": hi,
                        "opacity": self.layer_opacity,
                    }
                ],
            }
        ]

    @rx.var
    def mesh_background(self) -> list[dict[str, Any]]:
        """(d) The volume behind the mesh, if wanted."""
        return self.t1_volume if self.mesh_over_volume else []

    @rx.var
    def clip_plane(self) -> list[float]:
        """[depth, azimuth, elevation]; depth 2 turns the clip plane off."""
        depth = self.clip_depth if self.clip_on else 2.0
        return [depth, self.clip_azimuth, self.clip_elevation]

    @rx.var
    def pen_value(self) -> int:
        """The pen's label value."""
        return PENS[self.pen]

    @rx.var
    def crosshair_rgba(self) -> list[float]:
        """The crosshair colour."""
        return CROSSHAIRS[self.crosshair]

    @rx.var
    def sync_group(self) -> str:
        """The two viewers' sync group ("" = not synced)."""
        return "pair" if self.synced else ""

    @rx.var
    def location_json(self) -> str:
        """The last ``on_location`` payload, for the panel and the browser test."""
        import json

        return json.dumps(self.location)

    # ------------------------------------------------------------ events
    def _log(self, text: str) -> None:
        self.events = [text, *self.events][:10]

    @rx.event
    def on_location(
        self, mm: list[float], vox: list[int], values: list[dict[str, Any]], frac: list[float]
    ):
        self.location = {
            "mm": [round(v, 2) for v in mm],
            "vox": vox,
            "values": [
                {"name": v.get("name"), "value": round(float(v.get("value") or 0), 3)}
                for v in values
            ],
            "frac": [round(v, 4) for v in frac],
        }

    @rx.event
    def on_image_loaded(self, name: str, dims: list[int]):
        self._log(f"image loaded: {name} {dims}")
        if name == "series" or (len(dims) > 3 and dims[3] > 1):
            self.frames = dims[3] if len(dims) > 3 else 1

    @rx.event
    def on_mesh_loaded(self, name: str):
        self._log(f"mesh loaded: {name}")

    @rx.event
    def on_frame_time(self, ms: float):
        self.frame_ms = ms

    @rx.event
    def on_frame_change(self, name: str, frame: int):
        self._log(f"frame: {name} -> {frame}")

    @rx.event
    def on_intensity(self, volume: dict[str, Any]):
        lo, hi = volume.get("cal_min"), volume.get("cal_max")
        self.intensity = f"{volume.get('name')}: {lo:.2f} .. {hi:.2f}"

    @rx.event
    def on_drawing(self, action: str):
        self._log(f"drawing: {action}")

    @rx.event
    def on_volume_updated(self):
        self.volume_updates += 1

    @rx.event
    def on_error(self, message: str):
        self._log(f"error: {message}")
        if not self.offline and _NETWORK_ERROR.search(message):
            self.offline = True
            self.notice = "The demo images could not be downloaded; using the offline phantom."

    # ------------------------------------------------------------ controls
    @rx.event
    def set_field(self, name: str, value: Any):
        """Set a control's field; sliders send ``[value]``."""
        if name not in _CONTROLS:
            raise ValueError(name)
        if isinstance(value, list) and len(value) == 1:
            value = value[0]
        setattr(self, name, value)

    @rx.event
    def set_frame(self, value: list[float]):
        self.frame = int(value[0])
        return niivue.set_frame_4d(self.frame, id="series")

    @rx.event
    def save_drawing(self):
        """Download the drawing (how a consumer calls an imperative helper)."""
        self._log("saving mask.nii.gz")
        yield niivue.save_image("mask.nii.gz", id="draw")

    @rx.event
    def go_to_target(self):
        try:
            mm = [float(v) for v in self.target_mm.replace(",", " ").split()]
        except ValueError:
            mm = []
        if len(mm) != 3:
            self._log("target must be three numbers (mm)")
            return
        return niivue.move_crosshair_to_mm(mm, id="tools")


# ------------------------------------------------------------------ UI pieces
_CONTROLS = {
    name
    for name in DemoState.get_fields()
    if name
    not in {
        "location",
        "frame_ms",
        "events",
        "intensity",
        "notice",
        "frames",
        "frame",
        "volume_updates",
    }
}


def _set(name: str):
    """An ``on_change`` handler setting ``DemoState.<name>``."""
    return lambda value: DemoState.set_field(name, value)


def _row(label: str, *controls: rx.Component) -> rx.Component:
    return rx.hstack(
        rx.text(label, size="2", color_scheme="gray", width="130px", flex_shrink="0"),
        *controls,
        align="center",
        width="100%",
        spacing="3",
    )


def _slider(label: str, value, on_change, lo: float, hi: float, step: float) -> rx.Component:
    return _row(
        label,
        rx.slider(
            value=[value], min=lo, max=hi, step=step, on_change=on_change, flex="1", size="1"
        ),
        rx.text(value, size="1", width="44px", text_align="right"),
    )


def _switch(label: str, checked, on_change) -> rx.Component:
    return _row(label, rx.switch(checked=checked, on_change=on_change, size="1"))


def _select(label: str, items, value, on_change) -> rx.Component:
    return _row(label, rx.select(items, value=value, on_change=on_change, size="1"))


def _events() -> dict[str, Any]:
    """The event handlers every viewer reports to."""
    return {
        "on_location": DemoState.on_location,
        "on_image_loaded": DemoState.on_image_loaded,
        "on_mesh_loaded": DemoState.on_mesh_loaded,
        "on_frame_time_ms": DemoState.on_frame_time,
        "on_frame_change": DemoState.on_frame_change,
        "on_intensity_change": DemoState.on_intensity,
        "on_drawing_changed": DemoState.on_drawing,
        "on_volume_updated": DemoState.on_volume_updated,
        "on_error": DemoState.on_error,
    }


def _layout(viewer: rx.Component, *controls: rx.Component) -> rx.Component:
    return rx.vstack(
        viewer,
        rx.grid(*controls, columns=rx.breakpoints(initial="1", md="2"), spacing="2", width="100%"),
        width="100%",
        spacing="3",
    )


def tab_volumes() -> rx.Component:
    return _layout(
        niivue.view(
            id="volumes",
            volumes=DemoState.overlay_volumes,
            slice_type="multiplanar",
            is_colorbar=DemoState.colorbar,
            is_radiological=DemoState.radiological,
            drag_mode=DemoState.drag_mode,
            crosshair_color=DemoState.crosshair_rgba,
            selected_volume=0,
            height="460px",
            **_events(),
        ),
        _select("Background", COLORMAPS, DemoState.bg_colormap, _set("bg_colormap")),
        _select("Overlay", ["labels", "heat"], DemoState.overlay_mode, _set("overlay_mode")),
        _select(
            "Overlay colormap",
            COLORMAPS,
            DemoState.overlay_colormap,
            _set("overlay_colormap"),
        ),
        _slider("Overlay opacity", DemoState.overlay_opacity, _set("overlay_opacity"), 0, 1, 0.05),
        _switch("Overlay visible", DemoState.overlay_visible, _set("overlay_visible")),
        _switch("Colorbar", DemoState.colorbar, _set("colorbar")),
        _switch("Radiological", DemoState.radiological, _set("radiological")),
        _select(
            "Right drag",
            ["contrast", "measurement", "pan", "none"],
            DemoState.drag_mode,
            _set("drag_mode"),
        ),
        _select("Crosshair", list(CROSSHAIRS), DemoState.crosshair, _set("crosshair")),
    )


def tab_render() -> rx.Component:
    return _layout(
        niivue.view(
            id="render",
            volumes=DemoState.t1_volume,
            slice_type=DemoState.slice_type,
            multiplanar_layout=DemoState.layout,
            render_azimuth_elevation=[DemoState.azimuth, DemoState.elevation],
            clip_plane=DemoState.clip_plane,
            show_3d_crosshair=DemoState.crosshair_3d,
            is_orient_cube=DemoState.orient_cube,
            options={"multiplanarShowRender": 1},
            height="460px",
            **_events(),
        ),
        _select(
            "View",
            ["render", "multiplanar", "axial", "coronal", "sagittal"],
            DemoState.slice_type,
            _set("slice_type"),
        ),
        _select(
            "Multiplanar layout",
            ["auto", "column", "grid", "row"],
            DemoState.layout,
            _set("layout"),
        ),
        _slider("Azimuth", DemoState.azimuth, _set("azimuth"), 0, 360, 1),
        _slider("Elevation", DemoState.elevation, _set("elevation"), -90, 90, 1),
        _switch("Clip plane", DemoState.clip_on, _set("clip_on")),
        _slider("Clip depth", DemoState.clip_depth, _set("clip_depth"), -1, 1, 0.05),
        _slider("Clip azimuth", DemoState.clip_azimuth, _set("clip_azimuth"), 0, 360, 5),
        _slider("Clip elevation", DemoState.clip_elevation, _set("clip_elevation"), -90, 90, 5),
        _switch("3D crosshair", DemoState.crosshair_3d, _set("crosshair_3d")),
        _switch("Orientation cube", DemoState.orient_cube, _set("orient_cube")),
    )


def tab_drawing() -> rx.Component:
    return _layout(
        niivue.view(
            id="draw",
            volumes=DemoState.t1_volume,
            slice_type="multiplanar",
            drawing_enabled=DemoState.drawing,
            pen_value=DemoState.pen_value,
            draw_opacity=DemoState.draw_opacity,
            drawing_fill_overwrites=DemoState.fill_overwrites,
            height="460px",
            **_events(),
        ),
        _switch("Drawing", DemoState.drawing, _set("drawing")),
        _select("Pen", list(PENS), DemoState.pen, _set("pen")),
        _slider("Opacity", DemoState.draw_opacity, _set("draw_opacity"), 0, 1, 0.05),
        _switch("Fill overwrites", DemoState.fill_overwrites, _set("fill_overwrites")),
        rx.hstack(
            rx.button("Undo", on_click=niivue.undo_draw(id="draw"), size="1"),
            rx.button("Clear", on_click=niivue.clear_drawing(id="draw"), size="1"),
            rx.button("Save mask.nii.gz", on_click=DemoState.save_drawing, size="1"),
            rx.button(
                "Load drawing",
                on_click=niivue.load_drawing_from_url(DemoState.source["drawing"], id="draw"),
                size="1",
                variant="soft",
            ),
            wrap="wrap",
        ),
    )


def tab_meshes() -> rx.Component:
    return _layout(
        niivue.view(
            id="mesh",
            volumes=DemoState.mesh_background,
            meshes=DemoState.mesh_list,
            slice_type="render",
            height="460px",
            **_events(),
        ),
        _row(
            "Mesh colour",
            rx.input(
                type="color",
                value=DemoState.mesh_color,
                on_change=_set("mesh_color"),
                width="60px",
                size="1",
            ),
        ),
        _slider("Mesh opacity", DemoState.mesh_opacity, _set("mesh_opacity"), 0, 1, 0.05),
        _switch("Mesh visible", DemoState.mesh_visible, _set("mesh_visible")),
        _slider("Layer opacity", DemoState.layer_opacity, _set("layer_opacity"), 0, 1, 0.05),
        _switch("Volume behind", DemoState.mesh_over_volume, _set("mesh_over_volume")),
    )


def tab_sync() -> rx.Component:
    viewer = {"volumes": DemoState.t1_volume, "sync_group": DemoState.sync_group, **_events()}
    return _layout(
        rx.grid(
            niivue.view(id="left", slice_type="multiplanar", height="420px", **viewer),
            niivue.view(
                id="right",
                slice_type="render",
                show_3d_crosshair=True,
                height="420px",
                **viewer,
            ),
            columns="2",
            spacing="2",
            width="100%",
        ),
        _switch("Synced", DemoState.synced, _set("synced")),
        rx.text(
            "Click or drag in one viewer: the crosshair, pan/zoom and 3D camera follow in the "
            "other (NiiVue's broadcastTo).",
            size="2",
            color_scheme="gray",
        ),
    )


def tab_tools() -> rx.Component:
    return rx.vstack(
        rx.grid(
            niivue.view(
                id="series",
                volumes=DemoState.series_volume,
                slice_type="multiplanar",
                is_colorbar=True,
                height="340px",
                **_events(),
            ),
            niivue.view(
                id="tools",
                volumes=DemoState.t1_volume,
                slice_type="multiplanar",
                height="340px",
                **_events(),
            ),
            columns=rx.breakpoints(initial="1", md="2"),
            spacing="2",
            width="100%",
        ),
        rx.grid(
            _slider("4D frame", DemoState.frame, DemoState.set_frame, 0, DemoState.frames - 1, 1),
            rx.hstack(
                rx.input(value=DemoState.target_mm, on_change=_set("target_mm"), size="1"),
                rx.button("Move crosshair (mm)", on_click=DemoState.go_to_target, size="1"),
                rx.button("Reset view", on_click=niivue.reset_view(id="tools"), size="1"),
                wrap="wrap",
            ),
            rx.box(),
            rx.hstack(
                rx.button("World space", on_click=niivue.set_slice_mm(True, id="tools"), size="1"),
                rx.button("Voxel space", on_click=niivue.set_slice_mm(False, id="tools"), size="1"),
                rx.button(
                    "Screenshot",
                    on_click=niivue.save_scene("niivue.png", id="tools"),
                    size="1",
                    variant="soft",
                ),
                rx.button(
                    "Save volume",
                    on_click=niivue.save_image("t1.nii.gz", drawing=False, id="tools"),
                    size="1",
                    variant="soft",
                ),
                wrap="wrap",
            ),
            columns=rx.breakpoints(initial="1", md="2"),
            spacing="2",
            width="100%",
        ),
        width="100%",
        spacing="3",
    )


def location_panel() -> rx.Component:
    loc = DemoState.location
    return rx.card(
        rx.vstack(
            rx.heading("on_location", size="3"),
            rx.cond(
                loc.contains("mm"),
                rx.vstack(
                    rx.text("mm: ", rx.code(loc["mm"].to_string()), size="2"),
                    rx.text("voxel: ", rx.code(loc["vox"].to_string()), size="2"),
                    rx.text("frac: ", rx.code(loc["frac"].to_string()), size="2"),
                    rx.foreach(
                        loc["values"].to(list[dict[str, Any]]),
                        lambda v: rx.text(
                            v["name"].to(str), ": ", rx.code(v["value"].to_string()), size="2"
                        ),
                    ),
                    spacing="1",
                ),
                rx.text("Click in a viewer.", size="2", color_scheme="gray"),
            ),
            rx.el.pre(DemoState.location_json, id="location", display="none"),
            rx.divider(),
            rx.text("frame time: ", rx.code(DemoState.frame_ms, " ms"), size="2"),
            rx.text("intensity: ", rx.code(DemoState.intensity), size="2"),
            rx.text("volume updates: ", rx.code(DemoState.volume_updates), size="2"),
            rx.heading("events", size="3"),
            rx.foreach(DemoState.events, lambda e: rx.text(e, size="1", font_family="monospace")),
            spacing="2",
            align="start",
        ),
        width=rx.breakpoints(initial="100%", lg="340px"),
        flex_shrink="0",
    )


def index() -> rx.Component:
    tabs = [
        ("volumes", "Volume + labels", tab_volumes),
        ("render", "Multiplanar / 3D", tab_render),
        ("drawing", "Drawing", tab_drawing),
        ("meshes", "Meshes", tab_meshes),
        ("sync", "Synced viewers", tab_sync),
        ("tools", "4D + tools", tab_tools),
    ]
    return rx.container(
        rx.vstack(
            rx.hstack(
                rx.heading("reflex-niivue", size="6"),
                rx.badge(f"NiiVue {niivue.NIIVUE_VERSION}"),
                rx.spacer(),
                rx.text("offline data", size="2"),
                rx.switch(checked=DemoState.offline, on_change=_set("offline")),
                width="100%",
                align="center",
            ),
            rx.cond(DemoState.notice != "", rx.callout(DemoState.notice, icon="info", size="1")),
            rx.flex(
                rx.tabs.root(
                    rx.tabs.list(*[rx.tabs.trigger(label, value=key) for key, label, _ in tabs]),
                    *[
                        rx.tabs.content(make(), value=key, padding_top="12px")
                        for key, _, make in tabs
                    ],
                    default_value="volumes",
                    flex="1",
                    min_width="0",
                ),
                location_panel(),
                direction=rx.breakpoints(initial="column", lg="row"),
                spacing="4",
                width="100%",
            ),
            spacing="3",
            width="100%",
        ),
        size="4",
    )


app = rx.App()
app.add_page(index, title="reflex-niivue demo")
