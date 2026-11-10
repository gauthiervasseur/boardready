# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "anthropic",
#   "openai",
#   "openpyxl",
#   "python-docx",
#   "pywebview>=5",
# ]
# ///
"""
BoardReady: submit a Markdown, Word or Excel document to the Think_Ask personas.

Run it:
  uv run app.py              native Mac window (what "BoardReady.app" does)
  uv run app.py --browser    same app in your browser, as a local website
  uv run app.py --serve      server only (prints the address; nothing opens)
  python3 app.py --browser   without uv, after: pip install -r requirements.txt

The server listens on 127.0.0.1 only: nothing is reachable from another machine.
Your document leaves the Mac only to go to the model provider named in Think_Ask/.env.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import secrets
import socket
import subprocess
import sys
import threading
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import review_engine as engine

HERE = engine.RES                            # the folder, or the app's Resources when packaged
WEB = HERE / "web"
SITE = HERE / "site"
# Every POST must carry this token. It is written into the page the app serves, so a web
# page from anywhere else cannot drive this local server (start reviews, change the key).
TOKEN = secrets.token_urlsafe(24)
JOBS: dict[str, engine.Job] = {}
DOCS: dict[str, engine.Extracted] = {}       # extracted documents, by upload id
MAX_UPLOAD = 40 * 1024 * 1024

mimetypes.add_type("text/markdown; charset=utf-8", ".md")
mimetypes.add_type("image/svg+xml", ".svg")


def inside(base: Path, rel: str) -> Path | None:
    """Resolve rel under base, refusing anything that escapes it."""
    target = (base / unquote(rel)).resolve()
    return target if target.is_file() and (target == base or base.resolve() in target.parents) else None


class Handler(BaseHTTPRequestHandler):
    server_version = "BoardReady/1.0"

    def log_message(self, fmt, *args):  # keep the terminal quiet
        pass

    # -- helpers ------------------------------------------------------------
    def send_json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path | None, download=False):
        if not path or not path.is_file():
            return self.send_json({"error": "Not found"}, 404)
        data = path.read_bytes()
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.end_headers()
        self.wfile.write(data)

    def read_json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_UPLOAD * 1.4:
            raise ValueError("The file is larger than 40 MB.")
        return json.loads(self.rfile.read(n) or b"{}")

    # -- routes -------------------------------------------------------------
    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            page = (WEB / "index.html").read_text(encoding="utf-8").replace("__DR_TOKEN__", TOKEN)
            body = page.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return self.wfile.write(body)
        if path.startswith("/web/"):
            return self.send_file(inside(WEB, path[5:]))
        if path in ("/site", "/site/"):
            return self.send_file(SITE / "index.html")
        if path.startswith("/site/"):
            return self.send_file(inside(SITE, path[6:]))
        if path in ("/theme/page_afp.css", "/styles/page_afp.css"):  # the second: the website's relative link
            return self.send_file(engine.THEME_CSS if engine.THEME_CSS.exists() else None)
        if path == "/dist/BoardReady.dmg":  # the website's download link, from the workshop folder
            return self.send_file(inside(HERE / "dist", "BoardReady.dmg"), download=True)
        if path.startswith("/outputs/"):
            return self.send_file(inside(engine.OUTPUTS, path[9:]), download="download=1" in self.path)
        if path == "/api/config":
            return self.send_json({
                "personas": [engine.persona_card(p) for p in engine.PERSONAS],
                "actions": [{"id": k, "label": v["label"], "blurb": v["blurb"]} for k, v in engine.ACTIONS.items()],
                "settings": engine.settings_status(),
                "marp": engine.marp_status(),
                "accept": sorted(engine.SUPPORTED),
                "native": bool(getattr(self.server, "native", False)),
            })
        if path == "/api/history":
            return self.send_json({"items": engine.list_reviews()})
        if path.startswith("/api/jobs/"):
            job = JOBS.get(path.rsplit("/", 1)[-1])
            return self.send_json(job.to_dict() if job else {"error": "Unknown job"}, 200 if job else 404)
        self.send_json({"error": "Not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        if not secrets.compare_digest(self.headers.get("X-DR-Token", ""), TOKEN):
            return self.send_json({"error": "Reload the page."}, 403)
        try:
            data = self.read_json()
        except Exception as e:
            return self.send_json({"error": str(e)}, 400)

        if path in ("/api/extract", "/api/sample"):
            try:
                if path == "/api/sample":
                    sample = engine.SAMPLE_MEMO
                    data = {"name": sample.name}
                    raw = sample.read_bytes()
                else:
                    raw = base64.b64decode(data["data"])
                doc = engine.extract_document(data["name"], raw)
            except Exception as e:
                return self.send_json({"error": str(e)}, 400)
            upload_id = uuid.uuid4().hex[:12]
            DOCS[upload_id] = doc
            return self.send_json({
                "upload": upload_id, "name": doc.name, "kind": doc.kind, "size": len(raw),
                "stats": doc.stats, "notes": doc.notes, "preview": doc.text[:6000],
            })

        if path == "/api/review":
            doc = DOCS.get(data.get("upload", ""))
            personas = [p for p in data.get("personas", []) if p in engine.PERSONAS]
            actions = [a for a in data.get("actions", []) if a in engine.ACTIONS]
            if not doc:
                return self.send_json({"error": "Drop a document first."}, 400)
            if not personas or not actions:
                return self.send_json({"error": "Pick at least one persona and one action."}, 400)
            job = engine.Job(
                id=uuid.uuid4().hex[:10], doc=doc, personas=personas, actions=actions,
                synthesis=bool(data.get("synthesis")), pdf=bool(data.get("pdf", True)),
            )
            job.tasks = engine.plan_tasks(personas, actions, job.synthesis)
            JOBS[job.id] = job
            threading.Thread(target=engine.run_review, args=(job,), daemon=True).start()
            return self.send_json(job.to_dict())

        if path in ("/api/open", "/api/reveal"):
            target = inside(engine.OUTPUTS, data.get("file", ""))
            if not target:
                return self.send_json({"error": "Not found"}, 404)
            args = ["open", "-R", str(target)] if path == "/api/reveal" else ["open", str(target)]
            subprocess.Popen(args)
            return self.send_json({"ok": True})

        if path == "/api/settings":
            try:
                engine.save_settings(data.get("provider", ""), data.get("model", ""), data.get("api_key"))
            except Exception as e:
                return self.send_json({"error": str(e)}, 400)
            return self.send_json({"settings": engine.settings_status()})

        if path == "/api/open-folder":
            engine.OUTPUTS.mkdir(parents=True, exist_ok=True)
            subprocess.Popen(["open", str(engine.OUTPUTS)])
            return self.send_json({"ok": True})

        self.send_json({"error": "Not found"}, 404)


def free_port(preferred=8765) -> int:
    for port in (preferred, 0):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("No free port")


def brand_native_app():
    """Show "BoardReady" and its icon in the menu bar and Dock instead of "Python"."""
    try:
        from AppKit import NSApplication, NSImage
        from Foundation import NSBundle

        info = NSBundle.mainBundle().localizedInfoDictionary() or NSBundle.mainBundle().infoDictionary()
        info["CFBundleName"] = "BoardReady"
        icon = HERE / "web" / "icon.png"
        if icon.exists():
            NSApplication.sharedApplication().setApplicationIconImage_(NSImage.alloc().initWithContentsOfFile_(str(icon)))
    except Exception:
        pass  # cosmetic only


def main():
    if {"-h", "--help"} & set(sys.argv):
        print(__doc__)
        return
    browser = "--browser" in sys.argv and not engine.FROZEN
    serve_only = "--serve" in sys.argv
    port = free_port(int(next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--port=")), 8765)))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.native = not (browser or serve_only)
    url = f"http://127.0.0.1:{port}/"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"BoardReady is running at {url}   (website: {url}site/)", flush=True)

    if serve_only:
        print("Press Ctrl+C to stop.", flush=True)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            server.shutdown()
        return

    if not browser:
        try:
            import webview

            brand_native_app()
            webview.create_window(
                "BoardReady", url, width=1280, height=900, min_size=(980, 700),
                background_color="#F4F6F9",
            )
            webview.start()
            server.shutdown()
            return
        except Exception as e:  # no pywebview: fall back to the browser
            print(f"Native window unavailable ({e}); opening the browser instead.")

    webbrowser.open(url)
    print("Press Ctrl+C to stop.")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
