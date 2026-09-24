"""Make one pixel-bearing overview per captured scene and visible-text evidence."""
from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.capture_visual_matrix import _pages, _themes, required_scenes, validate_matrix


def scene_image_keys(scene: str) -> tuple[str, ...]:
    return tuple(f"{scene}:{theme}:{view}" for theme in _themes(scene)
                 for view in ("desktop-full", "phone-full", "phone-first"))


def prepare(directory: Path) -> None:
    from playwright.sync_api import sync_playwright

    records = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    validate_matrix(records, directory)
    by_key = {record["key"]: directory / record["path"] for record in records}
    pages = _pages()
    text_lines = ["# Весь видимый текст локальной матрицы 345", ""]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for scene in required_scenes():
            page = browser.new_page(viewport={"width": 2000, "height": 900})
            page.route("**/*", lambda route: route.abort())
            page.set_content(pages[scene], wait_until="domcontentloaded")
            visible = page.locator("body").inner_text()
            text_lines.extend((f"## {scene}", "", visible, ""))
            images = []
            for key in scene_image_keys(scene):
                path = by_key[key]
                uri = "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")
                images.append(f'<div><h2>{key}</h2><img src="{uri}"></div>')
            sheet = ("<html><style>body{margin:0;padding:12px;background:#f7f5ee;font:18px sans-serif;}"
                     "main{display:flex;align-items:flex-start;gap:12px}h1{font-size:24px;margin:0 0 8px}"
                     "h2{font-size:16px;margin:0 0 6px}img{display:block;max-width:1160px;max-height:3650px;"
                     "width:auto;height:auto;border:1px solid #aaa}main div:nth-child(n+2) img{max-width:390px}"
                     "</style><h1>" + scene + "</h1><main>" + "".join(images) + "</main></html>")
            page.set_content(sheet, wait_until="load")
            page.screenshot(path=str(directory / f"sheet-{scene}.png"), full_page=True,
                            animations="disabled")
            page.close()
        browser.close()
    (directory / "visual-text.md").write_text("\n".join(text_lines), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix-dir", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.matrix_dir)
    print(f"prepared {len(required_scenes())} scene sheets and visible text")
