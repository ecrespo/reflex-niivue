"""Synthetic data for running the demo offline (numpy + nibabel), written into ``assets/``.

A head phantom with a label map, a 4D series, a surface mesh with a scalar layer, and two
drawings: one on the phantom's grid and one on the grid of NiiVue's ``mni152.nii.gz``, so that
"Load drawing" works with either background.
"""

from __future__ import annotations

import gzip
import struct
from pathlib import Path

import nibabel as nib
import numpy as np

ASSETS = Path(__file__).resolve().parent.parent / "assets"
SYNTHETIC = ASSETS / "synthetic"
GENERATED = ASSETS / "generated"

SHAPE = (96, 112, 96)
SPACING = 2.0
ORIGIN = (-96.0, -132.0, -78.0)
LABELS = {1: "left nucleus", 2: "right nucleus", 3: "ventricles"}

# The grid of https://niivue.com/demos/images/mni152.nii.gz (uint8, 0.737 mm isotropic).
MNI_SHAPE = (207, 256, 215)
MNI_AFFINE = np.array(
    [
        [0.737463116645813, 0.0, 0.0, -75.76253509521484],
        [0.0, 0.737463116645813, 0.0, -110.76253509521484],
        [0.0, 0.0, 0.737463116645813, -71.76253509521484],
        [0.0, 0.0, 0.0, 1.0],
    ]
)


def _affine(spacing: float = SPACING, origin=ORIGIN) -> np.ndarray:
    a = np.diag([spacing, spacing, spacing, 1.0])
    a[:3, 3] = origin
    return a


def _mm_grid(shape, affine) -> np.ndarray:
    """World coordinates (x, y, z) of every voxel centre, shape (*shape, 3)."""
    ijk = np.stack(np.meshgrid(*[np.arange(n) for n in shape], indexing="ij"), axis=-1)
    return ijk @ affine[:3, :3].T + affine[:3, 3]


def _ellipsoid(mm, centre, radii) -> np.ndarray:
    return (((mm - np.asarray(centre)) / np.asarray(radii)) ** 2).sum(-1)


def _save(data: np.ndarray, affine: np.ndarray, path: Path, *, intent: str | None = None) -> None:
    img = nib.Nifti1Image(data, affine)
    img.header.set_xyzt_units("mm", "sec")
    img.set_qform(affine, code=1)
    img.set_sform(affine, code=1)
    if intent:
        img.header.set_intent(intent)
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(img, path)


def head() -> tuple[np.ndarray, np.ndarray]:
    """T1-like phantom (float32, 0..100) and its label map (uint8, ``LABELS``)."""
    mm = _mm_grid(SHAPE, _affine())
    rng = np.random.default_rng(7)
    scalp = _ellipsoid(mm, (0, -18, 8), (72, 92, 78))
    brain = _ellipsoid(mm, (0, -18, 10), (62, 82, 66))
    vent = _ellipsoid(mm, (0, -12, 14), (10, 26, 10))
    left = _ellipsoid(mm, (-22, -10, 4), (9, 12, 9))
    right = _ellipsoid(mm, (22, -10, 4), (9, 12, 9))
    t1 = np.zeros(SHAPE, np.float32)
    t1[scalp <= 1] = 85  # scalp
    t1[(scalp <= 0.82) & (brain > 1)] = 15  # skull
    folds = 8 * np.sin(mm[..., 0] / 5) * np.sin(mm[..., 1] / 6) * np.sin(mm[..., 2] / 5)
    t1[brain <= 1] = (62 + folds)[brain <= 1]  # cortex-like texture
    t1[brain <= 0.55] = 78  # white matter
    t1[(left <= 1) | (right <= 1)] = 55
    t1[vent <= 1] = 20
    t1 += rng.normal(0, 1.5, SHAPE).astype(np.float32) * (scalp <= 1)
    t1 = np.clip(t1, 0, 100).astype(np.float32)
    labels = np.zeros(SHAPE, np.uint8)
    labels[left <= 1] = 1
    labels[right <= 1] = 2
    labels[vent <= 1] = 3
    return t1, labels


def series(frames: int = 10) -> np.ndarray:
    """A 4D series (int16): a blob that grows and fades over ``frames`` volumes."""
    shape = (48, 56, 48)
    mm = _mm_grid(shape, _affine(4.0))
    brain = _ellipsoid(mm, (0, -18, 10), (62, 82, 66)) <= 1
    out = np.zeros((*shape, frames), np.int16)
    for t in range(frames):
        blob = _ellipsoid(mm, (20, -30, 20), (14 + 2 * t,) * 3) <= 1
        out[..., t] = brain * 400 + blob * (1000 - 60 * t)
    return out


def sphere_mesh(radius: float = 40.0, centre=(0.0, -18.0, 10.0), n: int = 48):
    """A UV sphere: vertices (mm, float32), triangles (uint32) and a scalar per vertex."""
    theta = np.linspace(0, np.pi, n)
    phi = np.linspace(0, 2 * np.pi, 2 * n, endpoint=False)
    t, p = np.meshgrid(theta, phi, indexing="ij")
    unit = np.stack([np.sin(t) * np.cos(p), np.sin(t) * np.sin(p), np.cos(t)], -1).reshape(-1, 3)
    verts = (unit * radius + np.asarray(centre)).astype(np.float32)
    m = 2 * n
    tris = []
    for i in range(n - 1):
        for j in range(m):
            a, b = i * m + j, i * m + (j + 1) % m
            c, d = a + m, b + m
            tris += [(a, c, b), (b, c, d)]
    scalars = (5 * unit[:, 2] * np.cos(3 * np.arctan2(unit[:, 1], unit[:, 0]))).astype(np.float32)
    return verts, np.asarray(tris, np.uint32), scalars


def _mz3(path: Path, *, verts=None, tris=None, scalars=None) -> None:
    """Write NiiVue's MZ3 format (gzipped): a mesh, or a scalar layer for one."""
    attr = (1 if tris is not None else 0) | (2 if verts is not None else 0)
    attr |= 8 if scalars is not None else 0
    nvert = len(verts) if verts is not None else len(scalars)
    nface = len(tris) if tris is not None else 0
    body = struct.pack("<HHIII", 23117, attr, nface, nvert, 0)
    for part in (tris, verts, scalars):
        if part is not None:
            body += np.ascontiguousarray(part).tobytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(body, mtime=0))


def _drawing(shape, affine, centre, radius) -> np.ndarray:
    mm = _mm_grid(shape, affine)
    out = np.zeros(shape, np.uint8)
    out[_ellipsoid(mm, centre, (radius,) * 3) <= 1] = 1
    out[_ellipsoid(mm, np.add(centre, (radius * 1.6, 0, 0)), (radius / 2,) * 3) <= 1] = 2
    return out


def write_all(force: bool = False) -> None:
    """Write every file the offline demo and the "Load drawing" buttons use (if missing)."""
    files = (
        SYNTHETIC / "head.nii.gz",
        SYNTHETIC / "labels.nii.gz",
        SYNTHETIC / "series4d.nii.gz",
        SYNTHETIC / "sphere.mz3",
        SYNTHETIC / "sphere_layer.mz3",
        SYNTHETIC / "drawing.nii.gz",
        GENERATED / "mni152_drawing.nii.gz",
    )
    if not force and all(p.is_file() for p in files):
        return
    t1, labels = head()
    _save(t1, _affine(), SYNTHETIC / "head.nii.gz")
    _save(labels, _affine(), SYNTHETIC / "labels.nii.gz", intent="label")
    _save(series(), _affine(4.0), SYNTHETIC / "series4d.nii.gz")
    verts, tris, scalars = sphere_mesh()
    _mz3(SYNTHETIC / "sphere.mz3", verts=verts, tris=tris)
    _mz3(SYNTHETIC / "sphere_layer.mz3", scalars=scalars)
    _save(_drawing(SHAPE, _affine(), (-20, -30, 30), 10.0), _affine(), SYNTHETIC / "drawing.nii.gz")
    mni = _drawing(MNI_SHAPE, MNI_AFFINE, (-25, -20, 20), 10.0)
    _save(mni, MNI_AFFINE, GENERATED / "mni152_drawing.nii.gz")


if __name__ == "__main__":
    write_all(force=True)
    print(f"wrote synthetic data into {ASSETS}")
