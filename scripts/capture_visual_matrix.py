"""Capture and validate local fictional UI evidence for the visual gate."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCENE_STATES = {
    "needs_connection": "needs_connection",
    "needs_token": "needs_token",
    "needs_client_use_bearer": "needs_client_use",
    "needs_client_use_oauth": "needs_client_use",
    "ready_bearer": "ready",
    "ready_oauth": "ready",
}
EXTRA_SCENES = ("issued", "landing")
VIEWPORTS = {"desktop": (1440, 900), "phone": (390, 844)}


def _code_states() -> set[str]:
    tree = ast.parse((ROOT / "web_html.py").read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "compute_activation_state")
    states = {node.value.value for node in ast.walk(function) if isinstance(node, ast.Return)
              and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)}
    return states


def required_scenes() -> tuple[str, ...]:
    code_states = _code_states()
    if code_states != set(SCENE_STATES.values()):
        raise ValueError(f"unmapped activation states: {sorted(code_states ^ set(SCENE_STATES.values()))}")
    return (*SCENE_STATES, *EXTRA_SCENES)


def _themes(scene: str) -> tuple[str, ...]:
    source = ROOT / ("landing_page.py" if scene == "landing" else "web_html.py")
    css = source.read_text(encoding="utf-8")
    return ("light", "dark") if re.search(r"prefers-color-scheme\s*:\s*dark", css) else ("light",)


def required_keys() -> tuple[str, ...]:
    return tuple(f"{scene}:{theme}:{view}"
                 for scene in required_scenes() for theme in _themes(scene)
                 for view in ("desktop-full", "phone-full", "phone-first"))


def validate_matrix(records: list[dict[str, str]], base_dir: Path | None = None) -> None:
    required = set(required_keys())
    keys = [item["key"] for item in records]
    missing = required - set(keys)
    if missing:
        raise ValueError(f"missing visual states: {sorted(missing)}")
    if len(keys) != len(set(keys)) or set(keys) != required:
        raise ValueError("duplicate or unexpected visual state key")
    hashes: dict[str, str] = {}
    for item in records:
        path = Path(item["path"])
        if not path.is_absolute():
            if base_dir is None:
                raise ValueError("relative screenshot path needs matrix directory")
            path = base_dir / path
        if not path.is_file():
            raise ValueError(f"missing screenshot: {path}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != item["sha256"]:
            raise ValueError(f"hash mismatch: {path}")
        if actual in hashes:
            raise ValueError(f"duplicate pixels: {hashes[actual]} and {item['key']}")
        hashes[actual] = item["key"]


def _pages() -> dict[str, str]:
    from landing_page import render_landing_page
    from tests.test_stage197_token_quick_issue import _account_page, _token_view

    oauth_unused = {"id": 1, "status": "active", "client_name": "ChatGPT", "has_live_access": True,
                    "created_at": "сегодня", "last_used_at": "Не использовался", "last_used_at_raw": None}
    oauth_used = {**oauth_unused, "last_used_at": "2026-09-24 12:00 UTC",
                  "last_used_at_raw": "2026-09-24T12:00:00+00:00"}
    return {
        "needs_connection": _account_page(active_connection=None, active_connection_count=0,
                                          integration_health_status="unknown"),
        "needs_token": _account_page(),
        "needs_client_use_bearer": _account_page(bearer_tokens=[_token_view()]),
        "needs_client_use_oauth": _account_page(oauth_grants=[oauth_unused]),
        "ready_bearer": _account_page(bearer_tokens=[_token_view(request_count=5)]),
        "ready_oauth": _account_page(oauth_grants=[oauth_used]),
        "issued": _account_page(issued_raw_token="vm_st_FICTIONAL_STAGE345_ONLY",
                                bearer_tokens=[_token_view()]),
        "landing": render_landing_page(),
    }


def validate_pages(pages: dict[str, str]) -> None:
    if set(pages) != set(required_scenes()):
        raise ValueError("missing or unexpected page fixture")
    for scene, state in SCENE_STATES.items():
        if f'data-activation-state="{state}"' not in pages[scene]:
            raise ValueError(f"wrong rendered state for {scene}: expected {state}")
    if 'id="issued-token-panel"' not in pages["issued"]:
        raise ValueError("missing one-time token scene")
    if 'id="examples"' not in pages["landing"]:
        raise ValueError("missing landing examples")


def capture(output_dir: Path) -> list[dict[str, str]]:
    from playwright.sync_api import sync_playwright

    output_dir.mkdir(parents=True, exist_ok=True)
    pages = _pages()
    validate_pages(pages)
    records = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for scene, html in pages.items():
            for theme in _themes(scene):
                for device, (width, height) in VIEWPORTS.items():
                    context = browser.new_context(viewport={"width": width, "height": height},
                                                  color_scheme=theme, device_scale_factor=1)
                    context.route("**/*", lambda route: route.abort())
                    page = context.new_page()
                    page.set_content(html, wait_until="domcontentloaded")
                    page.wait_for_timeout(150)
                    modes = ("full", "first") if device == "phone" else ("full",)
                    for mode in modes:
                        key = f"{scene}:{theme}:{device}-{mode}"
                        path = output_dir / f"{key.replace(':', '-')}.png"
                        page.screenshot(path=str(path), full_page=mode == "full", animations="disabled")
                        records.append({"key": key, "path": path.name,
                                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
                    context.close()
        browser.close()
    validate_matrix(records, output_dir)
    (output_dir / "manifest.json").write_text(json.dumps(records, ensure_ascii=False, indent=2))
    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    records = capture(args.output_dir)
    print(f"validated {len(records)} local screenshots across {len(required_scenes())} scenes")
