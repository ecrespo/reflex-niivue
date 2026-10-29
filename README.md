# reflex-niivue

A [Reflex](https://reflex.dev) component wrapping [NiiVue](https://github.com/niivue/niivue), the
WebGL2 viewer for medical images: NIfTI, NRRD, MHA/MHD, MGH, DICOM, meshes (GIfTI, MZ3, OBJ,
...), tractography, connectomes and drawings.

- One general-purpose `niivue.view(...)` component: volumes and overlays, label maps, meshes
  with layers, multiplanar and 3D render views, clip planes, drawing, synced viewers.
- Props map 1:1 to NiiVue methods; volumes and meshes are diffed by url, so changing an
  opacity or a colormap never downloads the image again.
- NiiVue events (`on_location`, `on_image_loaded`, ...) arrive in your Reflex state.
- Imperative actions (`save_image`, `undo_draw`, `move_crosshair_to_mm`, ...) are events you
  return or `yield` from a handler.
- NiiVue itself (`@niivue/niivue` 0.69.0) comes from npm when your app builds; nothing is
  vendored. No image data passes through Reflex state: NiiVue fetches the files itself.

Requires Python 3.11+, Reflex 0.10+ and a browser with WebGL2.

## Install

```bash
uv add reflex-niivue    # or: pip install reflex-niivue
```

## Quick start

```python
import reflex as rx
from reflex_niivue import label_colormap, niivue

IMAGES = "https://niivue.com/demos/images/"


class State(rx.State):
    opacity: float = 0.7
    mm: list[float] = []

    @rx.event
    def located(self, mm: list[float], vox: list[int], values: list[dict], frac: list[float]):
        self.mm = mm

    @rx.event
    def save(self):
        yield niivue.save_image("mask.nii.gz")  # the drawing, as NIfTI

    @rx.var
    def volumes(self) -> list[dict]:
        return [
            {"url": IMAGES + "mni152.nii.gz", "name": "t1"},
            {
                "url": IMAGES + "hippo.nii.gz",
                "name": "hippocampus",
                "opacity": self.opacity,
                "colormap_label": label_colormap({9: ("hippocampus", (255, 70, 70))}),
            },
        ]


def index():
    return rx.vstack(
        niivue.view(
            volumes=State.volumes,
            slice_type="multiplanar",
            drawing_enabled=True,
            pen_value=1,
            on_location=State.located,
            height="500px",
        ),
        rx.text(State.mm.to_string()),
        rx.hstack(
            rx.button("Undo", on_click=niivue.undo_draw()),
            rx.button("Save drawing", on_click=State.save),
        ),
    )


app = rx.App()
app.add_page(index)
```

## Props

| Prop | Type | NiiVue |
|---|---|---|
| `volumes` | `list[dict]` | `loadVolumes` / `addVolumeFromUrl` / `removeVolume`, `setColormap`, `setOpacity`, `cal_min`/`cal_max`, `setColormapLabel` |
| `meshes` | `list[dict]` | `addMeshFromUrl` / `removeMesh`, `setMeshProperty`, `setMeshLayerProperty`, `setMeshShader` |
| `slice_type` | `"axial"`, `"coronal"`, `"sagittal"`, `"multiplanar"`, `"render"` | `setSliceType` |
| `multiplanar_layout` | `"auto"`, `"column"`, `"grid"`, `"row"` | `setMultiplanarLayout` |
| `show_3d_crosshair` | `bool` | `opts.show3Dcrosshair` |
| `crosshair_color`, `crosshair_width` | RGBA 0..1, `float` | `setCrosshairColor`, `setCrosshairWidth` |
| `back_color` | RGBA 0..1 | `opts.backColor` |
| `drag_mode` | `"none"`, `"contrast"`, `"measurement"`, `"pan"`, `"slicer3d"`, `"angle"`, `"roi_selection"`, `"crosshair"`, `"windowing"`, `"callback_only"` | `setDragMode` |
| `is_colorbar`, `is_orient_cube` | `bool` | `opts.isColorbar`, `opts.isOrientCube` |
| `is_radiological` | `bool` | `setRadiologicalConvention` |
| `clip_plane` | `[depth, azimuth, elevation]` (depth ≥ 2 = off) | `setClipPlane` |
| `render_azimuth_elevation` | `[azimuth, elevation]` | `setRenderAzimuthElevation` |
| `selected_volume` | `int` | the layer whose colorbar shows; default target of `set_frame_4d` / `save_image` |
| `drawing_enabled` | `bool` | `setDrawingEnabled` |
| `pen_value` | `int` (0 erases) | `setPenValue` |
| `draw_opacity` | `float` | `setDrawOpacity` |
| `drawing_fill_overwrites` | `bool` | `drawFillOverwrites` |
| `options` | `dict` (camelCase `NVConfigOptions`) | merged into `new Niivue(options)`; the props above win |
| `sync_group` | `str` | viewers in the same group `broadcastTo` each other (crosshair, pan/zoom, 3D camera) |
| `sync_opts` | `dict` | what a group shares, default `{"2d": True, "3d": True}` |
| `height`, `width`, `id` | | default `480px` × `100%`; `id` names the viewer for the helpers |

`niivue_options(**props)` shows the constructor options a set of literal props produces.

### Volume descriptors

```python
{
    "url": "https://.../t1.nii.gz",  # required (NIfTI, NRRD, MHA, MGH, ...)
    "name": "t1",  # display name (shown in on_location values)
    "colormap": "gray",  # see colormaps()
    "opacity": 1.0,
    "visible": True,  # False = opacity 0, the volume stays loaded
    "cal_min": 0,
    "cal_max": 100,  # display range
    "colormap_label": label_colormap({1: ("liver", (255, 0, 0))}),  # label map
    # any other NiiVue ImageFromUrlOptions, camelCase or snake_case:
    "colormap_negative": "winter",
    "frame_4d": 0,
    "headers": {"Authorization": "..."},
}
```

The first volume is the background. Volumes are matched by `url` (or `name`): changing a
property updates the loaded volume; adding volumes after the existing ones appends them;
replacing the background or reordering reloads the list.

### Mesh descriptors

```python
{
    "url": "https://.../BrainMesh_ICBM152.lh.mz3",
    "name": "lh",
    "rgba255": [200, 200, 200, 255],
    "opacity": 1.0,
    "visible": True,
    "layers": [
        {"url": ".../lh.motor.mz3", "colormap": "warm", "cal_min": 2, "cal_max": 5, "opacity": 0.7}
    ],
}
```

## Events

| Event | Handler arguments |
|---|---|
| `on_location` | `mm: list[float]`, `vox: list[int]`, `values: list[dict]` (`name`, `id`, `value`, `vox`, `mm` per volume), `frac: list[float]` — throttled to 20/s |
| `on_image_loaded` | `name: str`, `dims: list[int]` |
| `on_mesh_loaded` | `name: str` |
| `on_frame_time_ms` | `ms: float` — mean redraw time, at most once per second |
| `on_frame_change` | `name: str`, `frame: int` (4D volumes) |
| `on_intensity_change` | `volume: dict` (`name`, `id`, `index`, `cal_min`, `cal_max`) |
| `on_drawing_changed` | `action: str` (`"draw"`, `"undo"`, `"load"`, `"close"`) |
| `on_volume_updated` | — |
| `on_error` | `message: str` (no WebGL2, failed download, unreadable file) |

## Imperative helpers

Each returns an event: use it as an event trigger, or `return`/`yield` it from a handler.
`id` picks the viewer (its `id` prop); without it the most recently mounted viewer is used.

```python
rx.button("Undo", on_click=niivue.undo_draw(id="main"))


@rx.event
def save(self):
    yield niivue.save_image("mask.nii.gz", id="main")
```

| Helper | Does |
|---|---|
| `move_crosshair_to_mm([x, y, z])` | moves the crosshair (fires `on_location`) |
| `set_frame_4d(frame, volume=None)` | shows a frame of a 4D volume |
| `save_image(filename, drawing=None, volume=None)` | downloads the drawing (default when there is one) or a volume as NIfTI |
| `save_scene(filename)` | downloads a PNG screenshot |
| `set_slice_mm(True)` | world-space (True) or voxel-space slices |
| `undo_draw()` / `clear_drawing()` | drawing undo / erase |
| `load_drawing_from_url(url, binarize=False)` | loads a drawing on the background's grid |
| `reset_view()` | resets pan/zoom, crosshair and 3D camera |

Arguments may be state Vars: `niivue.move_crosshair_to_mm(State.target)`.

## Colormaps

```python
from reflex_niivue import colormaps, label_colormap

colormaps()  # ["actc", ..., "gray", "hot", ..., "x_rain"]: NiiVue's built-in names

label_colormap({1: ("liver", (255, 0, 0)), 2: ("spleen", "#00ff0080")})
# {"R": [0, 255, 0], "G": [0, 0, 255], "B": [0, 0, 0], "A": [0, 255, 128],
#  "I": [0, 1, 2], "labels": ["background", "liver", "spleen"]}
```

## Demo

```bash
git clone https://github.com/ecrespo/reflex-niivue && cd reflex-niivue
uv sync
cd niivue_demo && uv run reflex run
```

Tabs: volume + label overlay (colormap, opacity, label/heat), multiplanar vs 3D render (camera,
clip plane), drawing (pen, undo, clear, save, load), meshes with a scalar layer, two synced
viewers, 4D frames and the imperative helpers, and a panel showing `on_location` from Python
state. It uses NiiVue's demo images and falls back to a synthetic phantom (numpy + nibabel,
written to `niivue_demo/assets/`) when they cannot be downloaded; `NIIVUE_DEMO_OFFLINE=1` forces
the offline data.

## Development

```bash
uv sync
uv run pre-commit run --all-files
uv run playwright install chromium   # once, for the browser checks
uv run pytest                        # or: uv run pytest -m "not browser"
uv build
```

## Releasing

Releases are published from GitHub Actions with Trusted Publishing (no API tokens):

| Event | Result |
|---|---|
| push to `main` | all checks, then the development pre-release `0.1.1.devN` on PyPI (`pip install --pre reflex-niivue`) and an install check |
| tag `v0.2.0rc1` (or `a1`, `b1`) on main | all checks, then a pre-release on PyPI (`pip install --pre reflex-niivue`) and a GitHub pre-release |
| tag `v0.2.0` on main | all checks, then the release on PyPI and a GitHub release |

```bash
git tag v0.1.0rc1 && git push origin v0.1.0rc1   # pre-release
git tag v0.1.0 && git push origin v0.1.0         # release
```

## License

Apache-2.0 (see `LICENSE` and `NOTICE`). NiiVue is BSD-2-Clause and is installed from npm.
