"""The component: imports, props -> NiiVue option mapping, validation, event specs, helpers."""

import inspect
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import reflex as rx
from reflex.utils.format import to_camel_case

from reflex_niivue import Niivue, niivue, niivue_options
from reflex_niivue import niivue as nv_module

ASSETS = Path(__file__).resolve().parents[1] / "src" / "reflex_niivue" / "assets"
JSX = (ASSETS / "niivue.jsx").read_text()


def rendered(component) -> str:
    return str(component).replace(" ", "")


class LocState(rx.State):
    location: dict = {}
    loaded: list[str] = []
    messages: list[str] = []
    target: list[float] = [0.0, 0.0, 0.0]

    @rx.event
    def set_location(self, mm: list[float], vox: list[int], values: list[dict], frac: list[float]):
        self.location = {"mm": mm, "vox": vox, "values": values, "frac": frac}

    @rx.event
    def image_loaded(self, name: str, dims: list[int]):
        self.loaded.append(name)

    @rx.event
    def log(self, message: str):
        self.messages.append(message)

    @rx.event
    def save(self):
        yield niivue.save_image("mask.nii.gz")


# ----------------------------------------------------------------------- imports
def test_library_is_the_shared_wrapper_asset():
    c = niivue.view()
    assert c.library == "$/public/external/reflex_niivue/niivue/assets/niivue.jsx"
    assert c.tag == "NiivueView"
    assert not c.is_default
    assert isinstance(c, rx.NoSSRComponent)
    assert f"import('{c.library}')" in c._get_dynamic_imports()
    assert ".then((mod) => mod.NiivueView)" in c._get_dynamic_imports()


def test_niivue_is_pinned_from_npm_not_vendored():
    c = niivue.view()
    assert c.lib_dependencies == [f"@niivue/niivue@{nv_module.NIIVUE_VERSION}"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", nv_module.NIIVUE_VERSION)
    assert re.findall(r'from "([^"]+)"', JSX) == ["react", "@niivue/niivue"]
    assert sorted(p.name for p in ASSETS.iterdir()) == ["niivue.jsx"]


def test_wrapper_exports_the_tag():
    assert "export function NiivueView(" in JSX


def _import_in(cwd: Path) -> str:
    code = "from reflex_niivue import Niivue; print(Niivue.library)"
    out = subprocess.run([sys.executable, "-c", code], cwd=cwd, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip().splitlines()[-1]


def test_inside_an_app_the_wrapper_is_linked(tmp_path):
    (tmp_path / "rxconfig.py").write_text("import reflex as rx\nconfig = rx.Config(app_name='x')\n")
    library = _import_in(tmp_path)
    linked = tmp_path / "assets/external/reflex_niivue/niivue/assets/niivue.jsx"
    assert linked.resolve() == (ASSETS / "niivue.jsx").resolve()
    assert library == Niivue.library


def test_outside_an_app_importing_leaves_the_directory_untouched(tmp_path):
    _import_in(tmp_path)
    assert list(tmp_path.iterdir()) == []


# ------------------------------------------------------- tables shared with the JSX
def _js_table(name: str) -> dict:
    """Parse ``export const NAME = {...};`` from the wrapper (a JSON-like object literal)."""
    match = re.search(rf"export const {name} = (\{{.*?\}});", JSX, re.S)
    assert match, name
    body = re.sub(r"//[^\n]*", "", match.group(1))
    body = re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:", r'\1"\2":', body)
    body = re.sub(r",\s*}", "}", body)
    return json.loads(body)


@pytest.mark.parametrize(
    ("js", "py"),
    [
        ("SLICE_TYPES", nv_module.SLICE_TYPES),
        ("MULTIPLANAR_LAYOUTS", nv_module.MULTIPLANAR_LAYOUTS),
        ("DRAG_MODES", nv_module.DRAG_MODES),
        ("VOLUME_KEYS", nv_module.VOLUME_KEYS),
        ("MESH_KEYS", nv_module.MESH_KEYS),
        ("LAYER_KEYS", nv_module.LAYER_KEYS),
    ],
)
def test_jsx_and_python_tables_agree(js, py):
    assert _js_table(js) == py


def test_prop_option_table_is_keyed_by_the_rendered_prop_names():
    # The JSX table is keyed by the camelCase names Reflex renders for the Python props.
    js = _js_table("PROP_OPTIONS")
    expected = {to_camel_case(k): v for k, v in nv_module.PROP_OPTIONS.items()}
    assert js == expected
    for prop in nv_module.PROP_OPTIONS:
        assert prop in Niivue.get_props()


def test_enums_match_niivue():
    # SLICE_TYPE, MULTIPLANAR_TYPE and DRAG_MODE of @niivue/niivue 0.69.
    assert nv_module.SLICE_TYPES == {
        "axial": 0,
        "coronal": 1,
        "sagittal": 2,
        "multiplanar": 3,
        "render": 4,
    }
    assert nv_module.MULTIPLANAR_LAYOUTS == {"auto": 0, "column": 1, "grid": 2, "row": 3}
    assert nv_module.DRAG_MODES["slicer3d"] == 4
    assert nv_module.DRAG_MODES["measurement"] == 2


# ---------------------------------------------------------------- option mapping
def test_props_map_to_niivue_constructor_options():
    opts = niivue_options(
        slice_type="render",
        multiplanar_layout="grid",
        show_3d_crosshair=True,
        crosshair_color=[1, 0, 0, 1],
        crosshair_width=2,
        back_color=[0, 0, 0, 1],
        drag_mode="pan",
        is_colorbar=True,
        is_orient_cube=False,
        is_radiological=True,
        pen_value=3,
    )
    assert opts == {
        "sliceType": 4,
        "multiplanarLayout": 2,
        "show3Dcrosshair": True,
        "crosshairColor": [1, 0, 0, 1],
        "crosshairWidth": 2,
        "backColor": [0, 0, 0, 1],
        "dragMode": 3,
        "isColorbar": True,
        "isOrientCube": False,
        "isRadiologicalConvention": True,
        "penValue": 3,
    }


def test_options_is_merged_and_dedicated_props_win():
    opts = niivue_options(options={"isColorbar": False, "textHeight": 0.04}, is_colorbar=True)
    assert opts == {"isColorbar": True, "textHeight": 0.04}
    assert niivue_options() == {}


def test_props_render_camel_case():
    out = rendered(
        niivue.view(
            slice_type="multiplanar",
            show_3d_crosshair=True,
            is_radiological=False,
            render_azimuth_elevation=[110, 15],
            clip_plane=[0.2, 0, 90],
            drawing_enabled=True,
            drawing_fill_overwrites=False,
            pen_value=1,
            draw_opacity=0.5,
            selected_volume=1,
            sync_group="pair",
            options={"isFilledPen": True},
        )
    )
    for snippet in (
        'sliceType:"multiplanar"',
        "show3dCrosshair:true",
        "isRadiological:false",
        "renderAzimuthElevation:[110,15]",
        "clipPlane:[0.2,0,90]",
        "drawingEnabled:true",
        "drawingFillOverwrites:false",
        "penValue:1",
        "drawOpacity:0.5",
        "selectedVolume:1",
        'syncGroup:"pair"',
        '["isFilledPen"]:true',
    ):
        assert snippet in out
    # Every prop the JSX destructures is a Python prop (or a base prop).
    pattern = r"export function NiivueView\(props\) \{\s*const \{(.*?)\} = props;"
    destructured = re.search(pattern, JSX, re.S)
    assert destructured
    names = re.findall(r"^\s*(\w+)(?:\s*=|,|:)", destructured.group(1), re.M)
    props = {to_camel_case(p) for p in Niivue.get_props()}
    props |= {"id", "className", "style", "ref"}
    assert set(names) - props == set()


def test_descriptors_render_as_given():
    vol = {"url": "a.nii.gz", "colormap": "hot", "cal_min": 1, "colormap_label": None}
    mesh = {"url": "m.mz3", "rgba255": [255, 0, 0, 255]}
    out = rendered(niivue.view(volumes=[vol], meshes=[mesh]))
    assert '["url"]:"a.nii.gz"' in out
    assert '["cal_min"]:1' in out
    assert '["rgba255"]:[255,0,0,255]' in out


def test_default_size_and_overrides():
    assert '["height"]:"480px"' in rendered(niivue.view())
    out = rendered(niivue.view(height="300px", width="50%", id="left"))
    assert '["height"]:"300px"' in out and '["width"]:"50%"' in out and 'id:"left"' in out


def test_state_vars_are_accepted():
    class VolState(rx.State):
        volumes: list[dict] = [{"url": "a.nii.gz"}]
        slice_type: str = "render"

    out = rendered(niivue.view(volumes=VolState.volumes, slice_type=VolState.slice_type))
    assert "volumes:" in out and "sliceType:" in out


# -------------------------------------------------------------------- validation
@pytest.mark.parametrize(
    ("props", "match"),
    [
        ({"slice_type": "3d"}, "slice_type"),
        ({"multiplanar_layout": "tiles"}, "multiplanar_layout"),
        ({"drag_mode": "zoom"}, "drag_mode"),
        ({"crosshair_color": [1, 0, 0]}, "crosshair_color"),
        ({"back_color": "black"}, "back_color"),
        ({"clip_plane": [0, 0]}, "clip_plane"),
        ({"render_azimuth_elevation": [1, 2, 3]}, "render_azimuth_elevation"),
        ({"volumes": [{"colormap": "hot"}]}, "volumes"),
        ({"meshes": [{"opacity": 1}]}, "meshes"),
        ({"draw_opacity": 2}, "draw_opacity"),
        ({"pen_value": -1}, "pen_value"),
        ({"pen_value": True}, "pen_value"),
    ],
)
def test_invalid_literal_props_are_rejected(props, match):
    with pytest.raises(ValueError, match=match):
        niivue.view(**props)


def test_children_are_rejected():
    with pytest.raises(ValueError, match="children"):
        niivue.view(rx.text("x"))


def test_state_vars_skip_literal_validation():
    class S(rx.State):
        st: str = "nonsense"

    niivue.view(slice_type=S.st)


# ------------------------------------------------------------------- event specs
EVENTS = {
    "on_location": ["mm", "vox", "values", "frac"],
    "on_image_loaded": ["name", "dims"],
    "on_mesh_loaded": ["name"],
    "on_frame_time_ms": ["ms"],
    "on_frame_change": ["name", "frame"],
    "on_intensity_change": ["volume"],
    "on_drawing_changed": ["action"],
    "on_volume_updated": [],
    "on_error": ["message"],
}


@pytest.mark.parametrize(("event", "args"), EVENTS.items())
def test_event_spec_arguments(event, args):
    spec = Niivue.get_event_triggers()[event]
    assert callable(spec)
    assert list(inspect.signature(spec).parameters) == args
    camel = to_camel_case(event)
    assert f'emit("{camel}"' in JSX


def test_on_location_reaches_the_handler_with_four_arguments():
    out = rendered(niivue.view(on_location=LocState.set_location))
    assert "onLocation:((_mm,_vox,_values,_frac)=>" in out
    assert '["mm"]:_mm,["vox"]:_vox,["values"]:_values,["frac"]:_frac' in out


def test_other_events_reach_their_handlers():
    out = rendered(niivue.view(on_image_loaded=LocState.image_loaded, on_error=LocState.log))
    assert "onImageLoaded:((_name,_dims)=>" in out
    assert "onError:((_message)=>" in out


# --------------------------------------------------------------------- helpers
def _script(spec) -> str:
    for name, value in spec.args:
        if str(name) == "javascript_code":
            return value._var_value if hasattr(value, "_var_value") else str(value)
    raise AssertionError(spec)


@pytest.mark.parametrize(
    ("spec", "call"),
    [
        (niivue.save_image("mask.nii.gz"), '"saveImage", null, "mask.nii.gz", null, null'),
        (
            niivue.save_image("t1.nii.gz", drawing=False, volume=0, id="v"),
            '"saveImage", "v", "t1.nii.gz", false, 0',
        ),
        (niivue.save_scene("shot.png"), '"saveScene", null, "shot.png"'),
        (niivue.move_crosshair_to_mm((1, -2, 3.5)), '"moveCrosshairToMm", null, [1, -2, 3.5]'),
        (niivue.set_frame_4d(3), '"setFrame4D", null, 3, null'),
        (niivue.set_frame_4d(1, "pcasl", id="v"), '"setFrame4D", "v", 1, "pcasl"'),
        (niivue.set_slice_mm(False), '"setSliceMM", null, false'),
        (niivue.undo_draw(), '"undoDraw", null'),
        (niivue.clear_drawing(id="v"), '"clearDrawing", "v"'),
        (
            niivue.load_drawing_from_url("d.nii.gz", binarize=True),
            '"loadDrawingFromUrl", null, "d.nii.gz", true',
        ),
        (niivue.reset_view(), '"resetView", null'),
    ],
)
def test_helpers_call_the_wrapper_commands(spec, call):
    assert 'ReflexEvent("_call_script"' in str(rx.button("x", on_click=spec))
    assert _script(spec) == f"window.reflexNiivue?.command({call})"
    name = call.split(",")[0].strip('"')
    assert re.search(rf"^\s+(async )?{name}\(nv\b", JSX, re.M), name


def test_helpers_accept_state_vars():
    out = rendered(rx.button("go", on_click=niivue.move_crosshair_to_mm(LocState.target)))
    assert "JSON.stringify(" in out and "target" in out


def test_helpers_can_be_yielded_from_handlers():
    out = rendered(rx.button("save", on_click=LocState.save))
    assert "save" in out
