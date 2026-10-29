// React wrapper around NiiVue (@niivue/niivue) for Reflex.
//
// One Niivue instance per mounted component, kept in a ref and attached to a canvas created on
// mount (a canvas whose WebGL context was lost can never get a new one, and React StrictMode
// mounts twice in development). Every prop maps to NiiVue methods or options through its own
// effect; volumes and meshes are diffed by url/name so unchanged ones are not downloaded again.
// The tables below are mirrored in reflex_niivue/niivue.py and compared by the tests.
import { useEffect, useRef, useState } from "react";
import { Niivue, INITIAL_SCENE_DATA } from "@niivue/niivue";

// <tables>
export const SLICE_TYPES = { axial: 0, coronal: 1, sagittal: 2, multiplanar: 3, render: 4 };
export const MULTIPLANAR_LAYOUTS = { auto: 0, column: 1, grid: 2, row: 3 };
export const DRAG_MODES = {
  none: 0,
  contrast: 1,
  measurement: 2,
  pan: 3,
  slicer3d: 4,
  callback_only: 5,
  roi_selection: 6,
  angle: 7,
  crosshair: 8,
  windowing: 9,
};
// Component prop (camelCase, as Reflex renders it) -> NiiVue constructor option.
export const PROP_OPTIONS = {
  sliceType: "sliceType",
  multiplanarLayout: "multiplanarLayout",
  show3dCrosshair: "show3Dcrosshair",
  crosshairColor: "crosshairColor",
  crosshairWidth: "crosshairWidth",
  backColor: "backColor",
  dragMode: "dragMode",
  isColorbar: "isColorbar",
  isOrientCube: "isOrientCube",
  isRadiological: "isRadiologicalConvention",
  penValue: "penValue",
};
// snake_case keys accepted in volume, mesh and mesh layer descriptors -> NiiVue's names.
export const VOLUME_KEYS = {
  colormap_label: "colormapLabel",
  colormap_negative: "colormapNegative",
  cal_min_neg: "cal_minNeg",
  cal_max_neg: "cal_maxNeg",
  frame_4d: "frame4D",
  limit_frames_4d: "limitFrames4D",
  ignore_zero_voxels: "ignoreZeroVoxels",
  trust_cal_min_max: "trustCalMinMax",
  percentile_frac: "percentileFrac",
  colorbar_visible: "colorbarVisible",
  alpha_threshold: "alphaThreshold",
  use_qform_not_sform: "useQFormNotSForm",
  url_image_data: "urlImageData",
  image_type: "imageType",
};
export const MESH_KEYS = {
  mesh_shader_index: "meshShaderIndex",
  colorbar_visible: "colorbarVisible",
};
export const LAYER_KEYS = {
  colormap_negative: "colormapNegative",
  use_negative_cmap: "useNegativeCmap",
  cal_min_neg: "cal_minNeg",
  cal_max_neg: "cal_maxNeg",
  colorbar_visible: "colorbarVisible",
  show_legend: "showLegend",
  outline_border: "outlineBorder",
};
// </tables>

const DEFAULT_SYNC = { "2d": true, "3d": true };
const NO_WEBGL =
  "WebGL2 is not available in this browser. Turn on hardware acceleration, or use a current " +
  "Chrome, Edge, Firefox or Safari.";

const rename = (obj, table) => {
  const out = {};
  for (const [k, v] of Object.entries(obj || {})) out[table[k] ?? k] = v;
  return out;
};
const toArray = (v) => (v == null ? v : Array.from(v, Number));
const sig = (v) => JSON.stringify(v ?? null);
const message = (e) => String(e?.message ?? e);
/** Key used to diff descriptors: the url, or the name for sources without one. */
const keyOf = (d) => String(d.url ?? d.name ?? "");

/** NiiVue constructor options for the given (camelCase) component props. */
export function niivueOptions(props) {
  const opts = { ...(props.options || {}) };
  for (const [prop, opt] of Object.entries(PROP_OPTIONS)) {
    const v = props[prop];
    if (v === undefined || v === null) continue;
    if (prop === "sliceType") opts[opt] = SLICE_TYPES[v] ?? v;
    else if (prop === "multiplanarLayout") opts[opt] = MULTIPLANAR_LAYOUTS[v] ?? v;
    else if (prop === "dragMode") opts[opt] = DRAG_MODES[v] ?? v;
    else opts[opt] = v;
  }
  return opts;
}

// ------------------------------------------------------------- shared registries
// Viewers by id, for the imperative helpers (rx.call_script), and sync groups.
const registry = (() => {
  if (typeof window === "undefined") return null;
  if (window.reflexNiivue) return window.reflexNiivue;
  const viewers = new Map(); // id -> Niivue
  const groups = new Map(); // sync group -> Set<Niivue>
  const get = (id) => (id == null ? [...viewers.values()].at(-1) : viewers.get(id));
  const api = {
    viewers,
    groups,
    get,
    /** Run a command (see COMMANDS) on viewer ``id`` (null: the most recently mounted). */
    async command(name, id, ...args) {
      const nv = get(id);
      const fn = COMMANDS[name];
      if (!nv || !fn) {
        console.warn(`reflex-niivue: no viewer ${id ?? ""} for ${name}`);
        return false;
      }
      return fn(nv, ...args);
    },
  };
  window.reflexNiivue = api;
  return api;
})();

function joinGroup(name, nv, syncOpts) {
  const members = registry.groups.get(name) ?? new Set();
  registry.groups.set(name, members);
  nv.reflexSyncOpts = syncOpts;
  members.add(nv);
  rewire(members);
}
function leaveGroup(name, nv) {
  const members = registry.groups.get(name);
  if (!members) return;
  members.delete(nv);
  nv.broadcastTo([]);
  if (members.size === 0) registry.groups.delete(name);
  else rewire(members);
}
function rewire(members) {
  for (const nv of members) {
    nv.broadcastTo([...members].filter((o) => o !== nv), nv.reflexSyncOpts ?? DEFAULT_SYNC);
  }
}

const volumeIndex = (nv, ref) => {
  if (ref == null) return nv.reflexSelected ?? 0;
  if (typeof ref === "number") return ref;
  return nv.volumes.findIndex((v) => v.name === ref || nv.mediaUrlMap?.get(v) === ref);
};

const COMMANDS = {
  moveCrosshairToMm(nv, mm) {
    nv.scene.crosshairPos = nv.mm2frac(mm);
    nv.createOnLocationChange();
    nv.drawScene();
    return true;
  },
  setFrame4D(nv, frame, volume) {
    const vol = nv.volumes[volumeIndex(nv, volume)];
    if (!vol) return false;
    nv.setFrame4D(vol.id, frame);
    return true;
  },
  async saveImage(nv, filename, drawing, volume) {
    const isSaveDrawing = drawing ?? !!nv.drawBitmap;
    const ok = await nv.saveImage({ filename, isSaveDrawing, volumeByIndex: volumeIndex(nv, volume) });
    return ok !== false;
  },
  async saveScene(nv, filename) {
    await nv.saveScene(filename);
    return true;
  },
  setSliceMM(nv, isSliceMM) {
    nv.setSliceMM(isSliceMM);
    return true;
  },
  undoDraw(nv) {
    nv.drawUndo();
    return true;
  },
  clearDrawing(nv) {
    nv.closeDrawing();
    if (nv.opts.drawingEnabled) nv.createEmptyDrawing();
    return true;
  },
  loadDrawingFromUrl(nv, url, binarize) {
    return nv.loadDrawingFromUrl(url, !!binarize);
  },
  resetView(nv) {
    nv.scene.pan2Dxyzmm = [0, 0, 0, 1];
    nv.scene.crosshairPos = [0.5, 0.5, 0.5];
    nv.scene.volScaleMultiplier = 1;
    nv.setRenderAzimuthElevation(INITIAL_SCENE_DATA.azimuth, INITIAL_SCENE_DATA.elevation);
    nv.createOnLocationChange();
    nv.drawScene();
    return true;
  },
};

// ---------------------------------------------------------------- volume / mesh diffing
/** Split a volume descriptor into NiiVue load options and the properties applied afterwards. */
function normalizeVolume(d) {
  const { visible = true, colormapLabel = null, ...load } = rename(d, VOLUME_KEYS);
  if (load.colorMap && !load.colormap) load.colormap = load.colorMap;
  delete load.colorMap;
  return { key: keyOf(d), load, visible, colormapLabel, label: displayName(load) };
}

/**
 * NiiVue picks the file reader from the extension of ``name`` (else ``url``), so a display name
 * without one ("t1") is applied after loading: load under the url's file name, return the label.
 */
function displayName(load) {
  const label = load.name;
  if (!label || !load.url || /\.[a-z0-9]+$/i.test(label)) return null;
  load.name = decodeURIComponent(new URL(load.url, window.location.href).pathname.split("/").pop());
  return label;
}

const nameVolume = (img, want) => {
  if (want.label) img.name = want.label;
};

function applyVolume(nv, img, want, have) {
  const v = want.load;
  let dirty = false;
  // Setting a colormap recomputes the display range, so explicit ranges are applied again.
  let rangeReset = false;
  if (v.colormap && v.colormap !== have?.load.colormap) {
    img.colormap = v.colormap;
    dirty = rangeReset = true;
  }
  if ((v.colormapNegative ?? "") !== (have?.load.colormapNegative ?? "")) {
    img.colormapNegative = v.colormapNegative ?? "";
    dirty = true;
  }
  for (const k of ["cal_min", "cal_max", "cal_minNeg", "cal_maxNeg"]) {
    if (v[k] != null && (rangeReset || v[k] !== have?.load[k])) {
      img[k] = v[k];
      dirty = true;
    }
  }
  const opacity = want.visible === false ? 0 : (v.opacity ?? 1);
  if (opacity !== img.opacity) {
    img.opacity = opacity;
    dirty = true;
  }
  const labelSig = sig(want.colormapLabel);
  if (labelSig !== img.reflexLabelSig) {
    if (want.colormapLabel) img.setColormapLabel(want.colormapLabel);
    else img.colormapLabel = null;
    img.reflexLabelSig = labelSig;
    dirty = true;
  }
  return dirty;
}

async function syncVolumes(nv, wanted, state, onError) {
  const want = wanted.map(normalizeVolume);
  for (const w of want) if (w.label) nv.reflexLabels.set(w.load.name, w.label);
  const keys = want.map((w) => w.key);
  const haveKeys = [...state.keys()];
  const kept = haveKeys.filter((k) => keys.includes(k));
  const added = keys.filter((k) => !state.has(k));
  // Removing layers and appending new ones keeps NiiVue's order only if the kept volumes stay
  // in order before every new one; otherwise (new background, reordering) reload everything.
  const incremental =
    haveKeys.length > 0 &&
    kept.length > 0 &&
    kept.join("\n") === keys.slice(0, kept.length).join("\n") &&
    added.every((k) => keys.indexOf(k) >= kept.length);
  if (!incremental) {
    state.clear();
    const list = want.map((w) => w.load);
    try {
      await nv.loadVolumes(list);
    } catch (e) {
      onError(`Could not load the volumes: ${message(e)}`);
      return;
    }
    nv.volumes.forEach((img, i) => {
      if (!want[i]) return;
      img.reflexLabelSig = sig(null);
      nameVolume(img, want[i]);
      applyVolume(nv, img, want[i], { load: want[i].load });
      state.set(want[i].key, { img, ...want[i] });
    });
  } else {
    for (const k of haveKeys) {
      if (keys.includes(k)) continue;
      nv.removeVolume(state.get(k).img);
      state.delete(k);
    }
    for (const w of want) {
      if (state.has(w.key)) continue;
      try {
        const img = await nv.addVolumeFromUrl(w.load);
        img.reflexLabelSig = sig(null);
        nameVolume(img, w);
        applyVolume(nv, img, w, { load: w.load });
        state.set(w.key, { img, ...w });
      } catch (e) {
        onError(`Could not load ${w.key}: ${message(e)}`);
      }
    }
    for (const w of want) {
      const have = state.get(w.key);
      if (have && applyVolume(nv, have.img, w, have)) state.set(w.key, { img: have.img, ...w });
    }
  }
  nv.updateGLVolume();
}

function normalizeMesh(d) {
  const { layers = [], ...load } = rename(d, MESH_KEYS);
  const label = displayName(load);
  return { key: keyOf(d), load, label, layers: layers.map((l) => rename(l, LAYER_KEYS)) };
}

async function syncMeshes(nv, wanted, state, onError) {
  const want = wanted.map(normalizeMesh);
  for (const w of want) if (w.label) nv.reflexLabels.set(w.load.name, w.label);
  const keys = new Set(want.map((w) => w.key));
  const layerUrls = (w) => w.layers.map((l) => l.url).join("\n");
  for (const [k, have] of [...state]) {
    const w = want.find((x) => x.key === k);
    if (w && layerUrls(w) === layerUrls(have)) continue;
    nv.removeMesh(have.mesh);
    state.delete(k);
  }
  for (const w of want) {
    const have = state.get(w.key);
    if (!have) {
      try {
        const mesh = await nv.addMeshFromUrl({ ...w.load, layers: w.layers });
        if (w.label) mesh.name = w.label;
        state.set(w.key, { mesh, ...w });
      } catch (e) {
        onError(`Could not load ${w.key}: ${message(e)}`);
      }
      continue;
    }
    const id = have.mesh.id;
    for (const k of ["opacity", "visible", "rgba255", "meshShaderIndex"]) {
      if (w.load[k] !== undefined && sig(w.load[k]) !== sig(have.load[k])) {
        if (k === "meshShaderIndex") nv.setMeshShader(id, w.load[k]);
        else nv.setMeshProperty(id, k, w.load[k]);
      }
    }
    for (let i = 0; i < w.layers.length; i++) {
      for (const [k, v] of Object.entries(w.layers[i])) {
        if (k !== "url" && sig(v) !== sig(have.layers[i]?.[k])) await nv.setMeshLayerProperty(id, i, k, v);
      }
    }
    state.set(w.key, { mesh: have.mesh, ...w });
  }
  if (keys.size === 0) nv.drawScene();
}

// ------------------------------------------------------------------------- component
export function NiivueView(props) {
  const {
    volumes = [],
    meshes = [],
    sliceType,
    multiplanarLayout,
    show3dCrosshair,
    crosshairColor,
    crosshairWidth,
    backColor,
    dragMode,
    isColorbar,
    isOrientCube,
    isRadiological,
    clipPlane,
    renderAzimuthElevation,
    selectedVolume,
    drawingEnabled,
    penValue,
    drawOpacity,
    drawingFillOverwrites,
    options,
    syncGroup,
    syncOpts,
    id,
    className,
    style,
    ref: outerRef, // React 19 passes refs as props; Reflex sets one for components with an id
  } = props;
  const holderRef = useRef(null);
  const nvRef = useRef(null);
  const volState = useRef(new Map()); // key -> { img, load, visible, colormapLabel }
  const meshState = useRef(new Map()); // key -> { mesh, load, layers }
  const queue = useRef(Promise.resolve()); // serialises volume/mesh updates
  const [ready, setReady] = useState(false);
  const [error, setError] = useState(null);

  // Latest callbacks for the NiiVue callbacks, which are set once.
  const cb = useRef({});
  cb.current = props;
  const emit = (name, ...args) => cb.current[name]?.(...args);
  const fail = (msg) => {
    setError(msg);
    emit("onError", msg);
  };

  // ---------------------------------------------------------- mount / unmount
  useEffect(() => {
    const holder = holderRef.current;
    const canvas = document.createElement("canvas");
    canvas.dataset.niivue = "canvas";
    holder.appendChild(canvas);
    const nv = new Niivue({ logLevel: "warn", ...niivueOptions(cb.current) });
    nv.reflexLabels = new Map(); // file name NiiVue loads under -> display name
    nvRef.current = nv;
    let alive = true;
    let locTimer = null;
    let lastLoc = null;
    let frames = { n: 0, ms: 0, since: performance.now() };

    nv.onLocationChange = (loc) => {
      lastLoc = loc;
      if (locTimer) return;
      locTimer = setTimeout(() => {
        locTimer = null;
        const l = lastLoc;
        if (!l || !alive) return;
        const values = (l.values || []).map((v) => ({
          name: v.name,
          id: v.id,
          value: Number(v.value),
          vox: toArray(v.vox),
          mm: toArray(v.mm)?.slice(0, 3),
        }));
        emit("onLocation", toArray(l.mm).slice(0, 3), toArray(l.vox), values, toArray(l.frac));
      }, 50);
    };
    nv.onImageLoaded = (vol) => {
      const dims = vol.hdr?.dims ?? [];
      emit("onImageLoaded", nv.reflexLabels.get(vol.name) ?? vol.name, Array.from(dims.slice(1, 1 + (dims[0] || 3)), Number));
    };
    nv.onMeshLoaded = (mesh) => emit("onMeshLoaded", nv.reflexLabels.get(mesh.name) ?? mesh.name);
    nv.onIntensityChange = (vol) =>
      emit("onIntensityChange", {
        name: vol.name,
        id: vol.id,
        index: nv.volumes.indexOf(vol),
        cal_min: vol.cal_min,
        cal_max: vol.cal_max,
      });
    nv.onDrawingChanged = (action) => emit("onDrawingChanged", action);
    nv.onVolumeUpdated = () => emit("onVolumeUpdated");
    nv.onFrameChange = (vol, frame) => emit("onFrameChange", vol.name, frame);
    nv.onError = (e) => emit("onError", message(e ?? "NiiVue error"));
    // Frame time: the mean drawScene() duration, reported at most once per second.
    const draw = nv.drawScene.bind(nv);
    nv.drawScene = (...args) => {
      const t0 = performance.now();
      const out = draw(...args);
      const t1 = performance.now();
      frames.n += 1;
      frames.ms += t1 - t0;
      if (cb.current.onFrameTimeMs && t1 - frames.since > 1000) {
        emit("onFrameTimeMs", Math.round((frames.ms / frames.n) * 100) / 100);
        frames = { n: 0, ms: 0, since: t1 };
      }
      return out;
    };

    const key = id ?? `niivue-${Math.random().toString(36).slice(2)}`;
    registry?.viewers.set(key, nv);
    holder.niivue = nv; // for browser tests and debugging
    nv.attachToCanvas(canvas)
      .then(() => {
        if (alive) setReady(true);
      })
      .catch((e) => {
        if (!alive) return;
        console.error("NiiVue could not start:", e);
        fail(/webgl2/i.test(message(e)) ? NO_WEBGL : `NiiVue could not start: ${message(e)}`);
      });

    return () => {
      alive = false;
      clearTimeout(locTimer);
      if (registry?.viewers.get(key) === nv) registry.viewers.delete(key);
      for (const [name, members] of registry?.groups ?? []) if (members.has(nv)) leaveGroup(name, nv);
      try {
        nv.cleanup();
        nv.gl?.getExtension("WEBGL_lose_context")?.loseContext();
      } catch (e) {
        console.warn("NiiVue teardown:", e);
      }
      canvas.remove();
      delete holder.niivue;
      volState.current.clear();
      meshState.current.clear();
      nvRef.current = null;
      setReady(false);
    };
  }, []);

  useEffect(() => {
    if (typeof outerRef === "function") {
      outerRef(holderRef.current);
      return () => outerRef(null);
    }
    if (outerRef) outerRef.current = holderRef.current;
  }, [outerRef]);

  // Run ``fn(nv)`` once the viewer is attached; NiiVue methods need the GL context.
  const live = (fn) => {
    const nv = nvRef.current;
    if (ready && nv) fn(nv);
  };

  // ------------------------------------------------------------ volumes / meshes
  const volSig = sig(volumes);
  useEffect(() => {
    const nv = nvRef.current;
    if (!ready || !nv) return;
    queue.current = queue.current.then(() => syncVolumes(nv, volumes || [], volState.current, fail));
  }, [volSig, ready]);

  const meshSig = sig(meshes);
  useEffect(() => {
    const nv = nvRef.current;
    if (!ready || !nv) return;
    queue.current = queue.current.then(() => syncMeshes(nv, meshes || [], meshState.current, fail));
  }, [meshSig, ready]);

  // ------------------------------------------------------------ display props
  useEffect(() => live((nv) => {
    if (sliceType != null) nv.setSliceType(SLICE_TYPES[sliceType] ?? sliceType);
  }), [sliceType, ready]);
  useEffect(() => live((nv) => {
    if (multiplanarLayout != null) nv.setMultiplanarLayout(MULTIPLANAR_LAYOUTS[multiplanarLayout] ?? multiplanarLayout);
  }), [multiplanarLayout, ready]);
  useEffect(() => live((nv) => {
    if (show3dCrosshair == null) return;
    nv.opts.show3Dcrosshair = show3dCrosshair;
    nv.drawScene();
  }), [show3dCrosshair, ready]);
  useEffect(() => live((nv) => {
    if (crosshairColor != null) nv.setCrosshairColor(crosshairColor);
  }), [sig(crosshairColor), ready]);
  useEffect(() => live((nv) => {
    if (crosshairWidth != null) nv.setCrosshairWidth(crosshairWidth);
  }), [crosshairWidth, ready]);
  useEffect(() => live((nv) => {
    if (backColor == null) return;
    nv.opts.backColor = backColor;
    nv.drawScene();
  }), [sig(backColor), ready]);
  useEffect(() => live((nv) => {
    if (dragMode != null) nv.setDragMode(DRAG_MODES[dragMode] ?? dragMode);
  }), [dragMode, ready]);
  useEffect(() => live((nv) => {
    if (isColorbar == null) return;
    nv.opts.isColorbar = isColorbar;
    nv.drawScene();
  }), [isColorbar, ready]);
  useEffect(() => live((nv) => {
    if (isOrientCube == null) return;
    nv.opts.isOrientCube = isOrientCube;
    nv.drawScene();
  }), [isOrientCube, ready]);
  useEffect(() => live((nv) => {
    if (isRadiological != null) nv.setRadiologicalConvention(isRadiological);
  }), [isRadiological, ready]);
  useEffect(() => live((nv) => {
    if (clipPlane != null) nv.setClipPlane(clipPlane);
  }), [sig(clipPlane), ready]);
  useEffect(() => live((nv) => {
    if (renderAzimuthElevation != null) nv.setRenderAzimuthElevation(...renderAzimuthElevation);
  }), [sig(renderAzimuthElevation), ready]);
  // The selected layer is the default target of set_frame_4d / save_image and the only one
  // whose colorbar is shown. Re-applied when the volumes change (new layers show theirs).
  useEffect(() => live((nv) => {
    if (selectedVolume == null) return;
    nv.reflexSelected = selectedVolume;
    queue.current = queue.current.then(() => {
      nv.volumes.forEach((v, i) => { v.colorbarVisible = i === selectedVolume; });
      nv.updateGLVolume();
    });
  }), [selectedVolume, volSig, ready]);
  useEffect(() => live((nv) => {
    if (sig(options) === "null") return;
    Object.assign(nv.opts, niivueOptions({ options }));
    nv.updateGLVolume();
  }), [sig(options), ready]);

  // ------------------------------------------------------------------ drawing
  // After the volumes: enabling the pen creates a drawing sized to the background image.
  useEffect(() => live((nv) => {
    if (drawingEnabled == null) return;
    queue.current = queue.current.then(() => nv.setDrawingEnabled(drawingEnabled));
  }), [drawingEnabled, volSig, ready]);
  useEffect(() => live((nv) => {
    if (penValue != null) nv.setPenValue(penValue, nv.opts.isFilledPen);
  }), [penValue, ready]);
  useEffect(() => live((nv) => {
    if (drawOpacity != null) nv.setDrawOpacity(drawOpacity);
  }), [drawOpacity, ready]);
  useEffect(() => live((nv) => {
    if (drawingFillOverwrites != null) nv.drawFillOverwrites = drawingFillOverwrites;
  }), [drawingFillOverwrites, ready]);

  // --------------------------------------------------------------------- sync
  const syncSig = sig(syncOpts);
  useEffect(() => {
    const nv = nvRef.current;
    if (!ready || !nv || !syncGroup || !registry) return;
    joinGroup(syncGroup, nv, syncOpts ?? DEFAULT_SYNC);
    return () => leaveGroup(syncGroup, nv);
  }, [syncGroup, syncSig, ready]);

  return (
    <div
      ref={holderRef}
      id={id}
      className={`reflex-niivue${className ? ` ${className}` : ""}`}
      style={{ position: "relative", overflow: "hidden", ...style }}
      data-niivue-ready={ready ? "true" : "false"}
    >
      {error && (
        <div
          role="alert"
          data-niivue-error=""
          style={{
            position: "absolute", inset: 0, display: "grid", placeItems: "center", padding: 16,
            background: "rgba(0,0,0,0.75)", color: "#f87171", font: "13px/1.45 system-ui, sans-serif",
            textAlign: "center", zIndex: 2,
          }}
        >
          {error}
        </div>
      )}
    </div>
  );
}
