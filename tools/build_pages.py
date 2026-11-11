#!/usr/bin/env python3
"""Assemble the GitHub Pages site for BoardReady into _site/ (stdlib only).

    python3 tools/build_pages.py

The website (site/index.html) links to ../web/ (portraits, icon), ../resources/ (page_afp.css)
and ../dist/ (the DMG and the Windows installer). On Pages those become web/, resources/ and the
latest GitHub Release, so the page works from the repo's own site root.
"""
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "_site"
repo = os.environ.get("GITHUB_REPOSITORY", "gauthiervasseur/boardready")
RELEASE = f"https://github.com/{repo}/releases/latest/download/"

if OUT.exists():
    shutil.rmtree(OUT)
shutil.copytree(ROOT / "site", OUT, ignore=shutil.ignore_patterns(".DS_Store"))
(OUT / "web").mkdir()
shutil.copytree(ROOT / "web" / "portraits", OUT / "web" / "portraits")
shutil.copy2(ROOT / "web" / "icon.svg", OUT / "web" / "icon.svg")
(OUT / "resources" / "styles").mkdir(parents=True)
shutil.copy2(ROOT / "resources" / "styles" / "page_afp.css", OUT / "resources" / "styles" / "page_afp.css")

page = OUT / "index.html"
html = page.read_text(encoding="utf-8")
for name in ("BoardReady.dmg", "BoardReady-Setup.exe"):
    html = html.replace(f"../dist/{name}", RELEASE + name)
html = html.replace('"../web/', '"web/').replace('"../resources/', '"resources/')
assert "../" not in html.replace("../../", ""), "a relative ../ link was left in the page"
page.write_text(html, encoding="utf-8")
(OUT / ".nojekyll").touch()
print("site ->", OUT, "| downloads ->", RELEASE)
