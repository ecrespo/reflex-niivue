"""Browser checks of the demo app (Playwright, headless Chromium with software WebGL2).

Skipped when Playwright's Chromium is not installed (``uv run playwright install chromium``),
when the demo app cannot be started, or when the browser has no WebGL2. Set
``NIIVUE_DEMO_URL=http://127.0.0.1:3000`` to test an already running demo instead of starting
one (it should use the offline data: ``NIIVUE_DEMO_OFFLINE=1``).
"""

import json

import pytest

pytestmark = pytest.mark.browser
playwright = pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="session")
def browser(browser_type, browser_type_launch_args):
    """Skip instead of erroring when Chromium is not installed."""
    try:
        b = browser_type.launch(**browser_type_launch_args)
    except playwright.Error as e:
        pytest.skip(f"Playwright browser not available: {str(e).splitlines()[0]}")
    yield b
    b.close()


@pytest.fixture
def demo(page, demo_url):
    if not page.evaluate("!!document.createElement('canvas').getContext('webgl2')"):
        pytest.skip("this headless Chromium has no WebGL2")
    page.set_viewport_size({"width": 1500, "height": 1000})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(demo_url)
    page.wait_for_selector("#volumes[data-niivue-ready=true]", timeout=90_000)
    yield page
    assert not errors, errors


def _gl(page, selector: str) -> dict:
    return page.evaluate(
        """(sel) => {
          const nv = document.querySelector(sel).niivue
          return {
            webgl2: nv.gl instanceof WebGL2RenderingContext,
            lost: nv.gl.isContextLost(),
            volumes: nv.volumes.map((v) => v.name),
          }
        }""",
        selector,
    )


def test_demo_mounts_a_canvas_with_a_webgl2_context(demo):
    # Exactly one canvas: a StrictMode remount (dev mode) must not leave the first one behind.
    assert demo.locator("#volumes canvas[data-niivue=canvas]").count() == 1
    assert demo.locator("[data-niivue-error]").count() == 0
    demo.wait_for_function(
        "document.querySelector('#volumes').niivue.volumes.length === 2", timeout=60_000
    )
    gl = _gl(demo, "#volumes")
    assert gl == {"webgl2": True, "lost": False, "volumes": ["t1", "overlay"]}


def test_label_overlay_gets_a_label_colormap(demo):
    demo.wait_for_function(
        "document.querySelector('#volumes').niivue.volumes.length === 2", timeout=60_000
    )
    labels = demo.evaluate(
        "document.querySelector('#volumes').niivue.volumes[1].colormapLabel?.labels"
    )
    assert labels[:4] == ["background", "left nucleus", "right nucleus", "ventricles"]


def test_click_reports_the_location_to_python_state(demo):
    demo.wait_for_function(
        "document.querySelector('#volumes').niivue.volumes.length === 2", timeout=60_000
    )
    box = demo.locator("#volumes canvas").bounding_box()
    assert box is not None
    demo.mouse.click(box["x"] + box["width"] * 0.25, box["y"] + box["height"] * 0.3)
    demo.wait_for_function(
        "JSON.parse(document.querySelector('#location').textContent || '{}').mm", timeout=15_000
    )
    loc = json.loads(demo.locator("#location").text_content() or "{}")
    assert len(loc["mm"]) == 3 and len(loc["vox"]) == 3 and len(loc["frac"]) == 3
    assert [v["name"] for v in loc["values"]] == ["t1", "overlay"]


def test_switching_tabs_tears_the_viewer_down(demo):
    demo.evaluate("window.__firstGl = document.querySelector('#volumes').niivue.gl")
    demo.get_by_role("tab", name="Synced viewers").click()
    demo.wait_for_selector("#left[data-niivue-ready=true]", timeout=60_000)
    demo.wait_for_selector("#right[data-niivue-ready=true]", timeout=60_000)
    assert demo.evaluate("window.__firstGl.isContextLost()")
    assert demo.locator("#volumes").count() == 0
    viewers = demo.evaluate("[...window.reflexNiivue.viewers.keys()].sort()")
    assert viewers == ["left", "right"]
    group = demo.evaluate("window.reflexNiivue.groups.get('pair')?.size")
    assert group == 2


def test_imperative_helper_moves_the_crosshair(demo):
    demo.get_by_role("tab", name="4D + tools").click()
    demo.wait_for_selector("#tools[data-niivue-ready=true]", timeout=60_000)
    demo.wait_for_function("document.querySelector('#tools').niivue.volumes.length === 1")
    demo.get_by_role("button", name="Move crosshair (mm)").click()
    demo.wait_for_function(
        """() => {
          const nv = document.querySelector('#tools').niivue
          const mm = nv.frac2mm(nv.scene.crosshairPos)
          return Math.abs(mm[0]) < 2.1 && Math.abs(mm[1] + 20) < 2.1 && Math.abs(mm[2] - 10) < 2.1
        }""",
        timeout=15_000,
    )
