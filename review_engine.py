"""
BoardReady engine: the part of the app that does the work.

  1. extract_document()  turns a Markdown, Word, Excel or CSV file into Markdown text.
  2. run_review()        sends that text to each chosen persona, once per chosen action,
                         in parallel, then (optionally) to a chair who combines the reviews.
  3. build_report()      writes the result as a Marp document on the `page_afp` theme,
                         following 4_Communicate/AFP2026_Doc_template.md, and cuts long
                         reviews into Letter pages so nothing runs past the footer.
  4. render_report()     exports that Markdown to HTML (and PDF) with the Marp CLI.

The personas are NOT copied here: each one is read from its file in the Think_Ask folder
(02, 03 and 04), so editing a persona file changes the app on its next run.
"""

from __future__ import annotations

import csv
import glob
import io
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# Two ways to run:
#   from the workshop folder: personas, theme and .env are read live from AFP-Workshop;
#   as the packaged app (the DMG): they are copies inside the app, the API key lives in
#   ~/Library/Application Support/BoardReady and reviews go to ~/Documents/BoardReady.
FROZEN = bool(getattr(sys, "frozen", False))
HERE = Path(__file__).resolve().parent            # .../1. Think_Ask/document review
RES = Path(getattr(sys, "_MEIPASS", HERE))         # web/, site/, bundled copies
if FROZEN:
    PERSONA_DIR = RES / "personas"
    THEME_CSS = RES / "styles" / "page_afp.css"
    OUTPUTS = Path.home() / "Documents" / "BoardReady"
    SETTINGS_FILE = Path.home() / "Library" / "Application Support" / "BoardReady" / "settings.env"
else:
    THINK_ASK = HERE.parent                        # .../1. Think_Ask
    WORKSHOP = THINK_ASK.parent                    # .../AFP-Workshop
    PERSONA_DIR = THINK_ASK
    THEME_CSS = WORKSHOP / "styles" / "page_afp.css"
    OUTPUTS = HERE / "outputs"
    SETTINGS_FILE = THINK_ASK / ".env"             # shared with 08-premortem-agent.py
SETTINGS_FILE = Path(os.environ.get("DR_SETTINGS_FILE", SETTINGS_FILE))
SAMPLE_MEMO = PERSONA_DIR / "sample-draft-forecast-memo.md"
MARP_VERSION = "4.5.1"

# ---------------------------------------------------------------------------
# Personas and actions
# ---------------------------------------------------------------------------

PERSONAS = {
    "cfo": {
        "file": "02-persona-skeptical-cfo.md",
        "name": "Elena Varga",
        "title": "The Skeptical CFO",
        "tag": "Skeptical CFO",
        "short": "Group CFO",
        "accent": "#002B49",
        "portrait": "cfo.svg",
        "cares": ["Does it tie?", "Real or mechanical?", "What decision changes?"],
        "blind_spot": "Loves a clean story",
    },
    "controller": {
        "file": "03-persona-controller.md",
        "name": "The Group Controller",
        "title": "The Controller",
        "tag": "Ties every number",
        "short": "Group Controller",
        "accent": "#3C8C94",
        "portrait": "controller.svg",
        "cares": ["Every figure sourced", "Methods stated", "Estimates flagged"],
        "blind_spot": "Checks ties, not the business question",
    },
    "redteam": {
        "file": "04-persona-red-team-reviewer.md",
        "name": "The Red-Team Reviewer",
        "title": "The Red-Team Reviewer",
        "tag": "Attacks from outside",
        "short": "Red-Team Reviewer",
        "accent": "#B3261E",
        "portrait": "redteam.svg",
        "cares": ["Who will dispute it?", "What gets gamed?", "The quote after a restatement"],
        "blind_spot": "Assumes bad faith",
    },
}

ACTIONS = {
    "criticize": {
        "label": "Criticize",
        "heading": "Critique",
        "blurb": "Find what would stop the document, in the persona's own review format.",
        "prompt": (
            "Review the document above as yourself. Answer in the Output format of your "
            "instructions, but write the verdict as the first line described below instead of "
            "numbering it."
        ),
    },
    "consistency": {
        "label": "Review for consistency",
        "heading": "Consistency review",
        "blurb": "Hunt for figures, terms, dates and claims that contradict each other.",
        "prompt": (
            "This time your task is a CONSISTENCY review, not a general critique. Read the "
            "document above through your own lens and stakes, and find where it disagrees "
            "with itself: figures that do not foot or that change between sections, totals "
            "that do not add up, the same term used with two meanings, dates, periods, units "
            "or currencies that shift, claims in one place that another place contradicts, "
            "and conclusions the figures do not support.\n\n"
            "Ignore the Output section of your instructions and answer in this format:\n"
            "### Inconsistencies\n"
            "A Markdown table with the columns: # | First statement (quoted) | Conflicting "
            "statement (quoted) | The inconsistency | Why it matters to you. At most 10 rows, "
            "most serious first. Keep each cell short.\n"
            "### Fix first\n"
            "One or two sentences: the inconsistency to fix before anything else, and why.\n\n"
            "If you find no inconsistency, say so in one line. Do not invent any. You may only "
            "compare statements that are in the document; never recompute from data you do "
            "not have, and say \"I would need to check\" when you cannot tell."
        ),
    },
    "enrich": {
        "label": "Suggest enrichments",
        "heading": "Enrichment suggestions",
        "blurb": "Propose what to add so the document answers its reader's real questions.",
        "prompt": (
            "This time your task is to SUGGEST ENRICHMENTS, not to critique. From your own "
            "role, stakes and expertise, say what the author should ADD so the document "
            "survives your review: missing analysis, context, comparisons, sources, "
            "reconciliations, sensitivities, risks, a decision or an owner. You still never "
            "rewrite the document, and you never invent figures, rates or sources: describe "
            "the content to add and the data the author must fetch.\n\n"
            "Ignore the Output section of your instructions and answer in this format:\n"
            "### Suggested additions\n"
            "A numbered list of at most 6 additions, most valuable first. Each item: **what "
            "to add** in bold, then where it goes (quote the nearest sentence or name the "
            "section), why it matters to you, and the data or source the author needs.\n"
            "### The one addition that matters most\n"
            "One or two sentences.\n\n"
            "If the document already gives you what you need, say so in one line."
        ),
    },
}

COMMON_RULES = """
Formatting rules for this answer:
- Start with exactly one line: **Verdict:** followed by your verdict in one sentence.
- Write in Markdown. For headings use ### only, never # or ##. Do not use horizontal rules (---).
- Stay under 450 words. Keep tables to at most 10 rows and short cells.
- Quote the document exactly when you object or point to a passage.
- Answer in the language the document is written in.
""".strip()

CHAIR_PROMPT = """You chair a review panel on a document. You receive the document and the reviews written by the panel: one or more personas, each doing one or more tasks (critique, consistency review, enrichment suggestions).
Combine them. Do not add objections, inconsistencies or suggestions the reviewers did not raise. Do not invent figures, rates, sources or links. Never recompute a number from data you do not have. Name who raised each point.

Start with exactly one line: **Verdict:** followed by one sentence: ready for its reader, or not yet.
Then use these sections, with ### headings only (never # or ##, no horizontal rules), and skip a section that has nothing in the reviews:

### The three points most likely to stop it
A numbered list: the point, the quoted sentence or number, who raised it, the suggested fix.

### Where the panel disagrees
One short paragraph: the tension the author has to decide.

### What to add first
At most three enrichments, if any reviewer suggested some.

### The business question, sharpened
One sentence: the question the document should answer, as the panel would now ask it.

Stay under 500 words. Answer in the language the document is written in."""


def load_persona_prompt(persona_id: str) -> str:
    """A persona file keeps its prompt in the first ```text block. Return that block."""
    text = (PERSONA_DIR / PERSONAS[persona_id]["file"]).read_text(encoding="utf-8")
    start = text.index("```text") + len("```text")
    end = text.index("```", start)
    return text[start:end].strip()


def persona_card(persona_id: str) -> dict:
    """What the UI shows for a persona: the static fields plus the lines from its file."""
    p = dict(PERSONAS[persona_id])
    p["id"] = persona_id
    text = (PERSONA_DIR / p["file"]).read_text(encoding="utf-8")
    role = re.search(r"\*\*Role in the decision:\*\*\s*(.+)", text)
    use = re.search(r"\*\*Use it for:\*\*\s*(.+)", text)
    p["role"] = role.group(1).strip() if role else ""
    p["use_for"] = use.group(1).strip() if use else ""
    return p


# ---------------------------------------------------------------------------
# Settings: PROVIDER, API_KEY, MODEL in SETTINGS_FILE (see the paths at the top)
# ---------------------------------------------------------------------------

def load_settings() -> dict:
    env_file = SETTINGS_FILE
    settings = {}
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                settings[key.strip()] = value.strip()
    return settings


def settings_status() -> dict:
    s = load_settings()
    key = s.get("API_KEY", "")
    return {
        "provider": s.get("PROVIDER", ""),
        "model": s.get("MODEL", ""),
        "ready": bool(s.get("PROVIDER") and s.get("MODEL") and key and key != "paste-your-key-here"),
        "has_key": bool(key and key != "paste-your-key-here"),
        "key_hint": ("…" + key[-4:]) if len(key) > 12 and key != "paste-your-key-here" else "",
        "env_path": str(SETTINGS_FILE),
        "packaged": FROZEN,
    }


def save_settings(provider: str, model: str, api_key: str | None) -> None:
    """Update PROVIDER, MODEL and (if given) API_KEY in place, keeping the file's comments."""
    provider = provider.strip().lower()
    if provider not in ("anthropic", "openai"):
        raise ValueError("Provider must be anthropic or openai.")
    model = model.strip()
    if not re.fullmatch(r"[A-Za-z0-9._:/-]{2,80}", model):
        raise ValueError("Enter a model name, for example claude-sonnet-5-5.")
    values = {"PROVIDER": provider, "MODEL": model}
    if api_key and api_key.strip():
        key = api_key.strip()
        if any(c.isspace() for c in key) or len(key) < 20:
            raise ValueError("That does not look like an API key.")
        values["API_KEY"] = key
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = SETTINGS_FILE.read_text(encoding="utf-8").splitlines() if SETTINGS_FILE.exists() else [
        "# BoardReady settings. Keep this file private: it holds your API key."]
    done = set()
    for i, line in enumerate(lines):
        name = line.split("=", 1)[0].strip()
        if "=" in line and not line.lstrip().startswith("#") and name in values:
            lines[i] = f"{name}={values[name]}"
            done.add(name)
    lines += [f"{k}={v}" for k, v in values.items() if k not in done]
    SETTINGS_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(SETTINGS_FILE, 0o600)


# ---------------------------------------------------------------------------
# 1. Extraction
# ---------------------------------------------------------------------------

SUPPORTED = {
    ".md": "Markdown", ".markdown": "Markdown", ".txt": "Text",
    ".docx": "Word", ".xlsx": "Excel", ".xlsm": "Excel", ".csv": "CSV",
}
MAX_SHEET_ROWS = 400          # rows sent per sheet; the reviewer is told when a sheet is cut
MAX_FORMULAS = 40             # formulas listed per sheet


@dataclass
class Extracted:
    name: str
    kind: str
    text: str
    stats: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)


def _md_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        value = f"{value:,.2f}" if abs(value) >= 1000 else (f"{value:g}")
    elif isinstance(value, datetime):
        value = value.strftime("%Y-%m-%d") if value.time() == datetime.min.time() else value.isoformat(sep=" ")
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def _md_table(rows: list[list]) -> str:
    width = max(len(r) for r in rows)
    rows = [list(r) + [""] * (width - len(r)) for r in rows]
    head = [c or f"Col {i + 1}" for i, c in enumerate(rows[0])]
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * width]
    out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(out)


def _trim_grid(grid: list[list[str]]) -> list[list[str]]:
    grid = [r for r in grid if any(c for c in r)]
    if not grid:
        return grid
    keep = [i for i in range(max(len(r) for r in grid)) if any(i < len(r) and r[i] for r in grid)]
    return [[r[i] if i < len(r) else "" for i in keep] for r in grid]


def _extract_excel(path: Path) -> tuple[str, dict, list]:
    import openpyxl

    wb_values = openpyxl.load_workbook(path, data_only=True, read_only=True)
    wb_formulas = openpyxl.load_workbook(path, data_only=False, read_only=True)
    parts, notes = [], []
    total_rows = formulas_total = 0
    for ws in wb_values.worksheets:
        wf = wb_formulas[ws.title]
        grid, formulas = [], []
        for row_v, row_f in zip(ws.iter_rows(), wf.iter_rows()):
            cells = []
            for cv, cf in zip(row_v, row_f):
                v = cv.value
                f = cf.value
                if isinstance(f, str) and f.startswith("="):
                    formulas_total += 1
                    if len(formulas) < MAX_FORMULAS:
                        formulas.append(f"{cf.coordinate}: `{f}`")
                    if v is None:  # file saved without calculated values
                        v = f
                cells.append(_md_cell(v))
            grid.append(cells)
        grid = _trim_grid(grid)
        parts.append(f"## Sheet: {ws.title}")
        if not grid:
            parts.append("*(empty sheet)*")
            continue
        total_rows += len(grid)
        shown = grid[: MAX_SHEET_ROWS + 1]
        parts.append(_md_table(shown))
        if len(grid) > len(shown):
            msg = f"Sheet '{ws.title}': only the first {MAX_SHEET_ROWS} of {len(grid) - 1} data rows were sent."
            parts.append(f"*{msg}*")
            notes.append(msg)
        if formulas:
            parts.append("Formulas on this sheet (cell: formula):\n" + "\n".join(f"- {f}" for f in formulas))
    header = (
        "*Spreadsheet converted to tables, one per sheet. Cells show the values saved in the file; "
        "formulas are listed under each sheet.*"
    )
    stats = {"sheets": len(wb_values.worksheets), "rows": total_rows, "formulas": formulas_total}
    wb_values.close()
    wb_formulas.close()
    return header + "\n\n" + "\n\n".join(parts), stats, notes


def _extract_docx(path: Path) -> str:
    pandoc = shutil.which("pandoc") or next((p for p in ("/usr/local/bin/pandoc", "/opt/homebrew/bin/pandoc") if Path(p).exists()), None)
    if pandoc:
        out = subprocess.run(
            [pandoc, str(path), "-f", "docx", "-t", "gfm", "--wrap=none"],
            capture_output=True, text=True, timeout=120,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout
    import docx  # python-docx fallback

    d = docx.Document(str(path))
    parts = []
    for block in d.element.body.iterchildren():
        tag = block.tag.rsplit("}", 1)[-1]
        if tag == "p":
            para = docx.text.paragraph.Paragraph(block, d)
            text = para.text.strip()
            if not text:
                continue
            style = (para.style.name or "").lower()
            if style.startswith("heading"):
                level = re.sub(r"\D", "", style) or "2"
                parts.append("#" * min(int(level), 6) + " " + text)
            elif "list" in style:
                parts.append("- " + text)
            else:
                parts.append(text)
        elif tag == "tbl":
            table = docx.table.Table(block, d)
            rows = [[_md_cell(c.text) for c in r.cells] for r in table.rows]
            if rows:
                parts.append(_md_table(rows))
    return "\n\n".join(parts)


def extract_document(name: str, data: bytes) -> Extracted:
    suffix = Path(name).suffix.lower()
    if suffix not in SUPPORTED:
        raise ValueError(
            f"{suffix or 'This file type'} is not supported. Drop a Markdown (.md), Word (.docx), "
            "Excel (.xlsx) or CSV file. Save older .doc or .xls files in the new format first."
        )
    kind = SUPPORTED[suffix]
    stats, notes = {}, []
    if suffix in (".md", ".markdown", ".txt"):
        text = data.decode("utf-8", errors="replace")
    elif suffix == ".csv":
        raw = data.decode("utf-8-sig", errors="replace")
        rows = [[_md_cell(c) for c in r] for r in csv.reader(io.StringIO(raw))]
        rows = _trim_grid(rows)
        stats["rows"] = len(rows)
        shown = rows[: MAX_SHEET_ROWS + 1]
        text = _md_table(shown) if shown else ""
        if len(rows) > len(shown):
            msg = f"Only the first {MAX_SHEET_ROWS} of {len(rows) - 1} data rows were sent."
            text += f"\n\n*{msg}*"
            notes.append(msg)
    else:
        fd, tmp_name = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        path = Path(tmp_name)
        path.write_bytes(data)
        try:
            if suffix == ".docx":
                text = _extract_docx(path)
            else:
                text, stats, notes = _extract_excel(path)
        finally:
            path.unlink(missing_ok=True)
    text = text.strip()
    if not text:
        raise ValueError("The file has no readable text.")
    stats.setdefault("words", len(re.findall(r"\w+", text)))
    stats["tables"] = len(re.findall(r"^\|[ :-]*-{3,}", text, flags=re.M)) or len(re.findall(r"^\|?\s*-{3,}\s*\|", text, flags=re.M))
    return Extracted(name=name, kind=kind, text=text, stats=stats, notes=notes)


# ---------------------------------------------------------------------------
# 2. Model calls
# ---------------------------------------------------------------------------

class ReviewError(RuntimeError):
    pass


def ask(settings: dict, instructions: str, message: str) -> str:
    """One call to the model: the persona as instructions, the document as the message."""
    provider = settings.get("PROVIDER", "").lower()
    if provider == "anthropic":
        import anthropic

        client = anthropic.Anthropic(api_key=settings["API_KEY"])
        try:
            # Streaming keeps a long review clear of HTTP timeouts.
            with client.messages.stream(
                model=settings["MODEL"],
                max_tokens=32000,
                system=instructions,
                messages=[{"role": "user", "content": message}],
            ) as stream:
                reply = stream.get_final_message()
        except anthropic.AuthenticationError:
            raise ReviewError("The API key was refused. Check it in Settings.")
        except anthropic.NotFoundError:
            raise ReviewError(f"Model '{settings['MODEL']}' was not found. Check the model in Settings.")
        except anthropic.RateLimitError:
            raise ReviewError("Rate limit reached. Wait a minute and run again.")
        except anthropic.APIStatusError as e:
            raise ReviewError(f"API error {e.status_code}: {e.message}")
        except anthropic.APIConnectionError:
            raise ReviewError("No connection to the API. Check the network.")
        if reply.stop_reason == "refusal":
            raise ReviewError("The model declined this request.")
        # Thinking blocks come before the answer: keep only the text blocks.
        text = "".join(b.text for b in reply.content if b.type == "text").strip()
        if reply.stop_reason == "max_tokens" or not text:
            raise ReviewError(f"The model stopped before finishing (stop_reason: {reply.stop_reason}).")
        return text
    if provider == "openai":
        from openai import OpenAI

        client = OpenAI(api_key=settings["API_KEY"])
        reply = client.responses.create(model=settings["MODEL"], instructions=instructions, input=message)
        return reply.output_text.strip()
    raise ReviewError("The provider in Settings must be anthropic or openai.")


def document_message(doc: Extracted) -> str:
    kind = {"Excel": "an Excel workbook", "Word": "a Word document", "CSV": "a CSV file"}.get(doc.kind, "a document")
    note = ("\n\nNote: " + " ".join(doc.notes)) if doc.notes else ""
    return f'<document name="{doc.name}" source="{kind}">\n{doc.text}\n</document>{note}'


@dataclass
class Task:
    key: str
    persona: str | None      # None for the chair
    action: str | None
    label: str
    state: str = "queued"     # queued, running, done, error
    started: float = 0.0
    finished: float = 0.0
    text: str = ""
    error: str = ""


@dataclass
class Job:
    id: str
    doc: Extracted
    personas: list
    actions: list
    synthesis: bool
    pdf: bool
    tasks: list = field(default_factory=list)
    state: str = "running"    # running, rendering, done, error
    error: str = ""
    created: float = field(default_factory=time.time)
    outputs: dict = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def to_dict(self) -> dict:
        now = time.time()
        return {
            "id": self.id,
            "state": self.state,
            "error": self.error,
            "elapsed": round(now - self.created, 1),
            "outputs": self.outputs,
            "tasks": [
                {
                    "key": t.key, "persona": t.persona, "action": t.action, "label": t.label,
                    "state": t.state, "error": t.error,
                    "seconds": round((t.finished or now) - t.started, 1) if t.started else 0,
                }
                for t in self.tasks
            ],
        }


def plan_tasks(personas: list, actions: list, synthesis: bool) -> list[Task]:
    tasks = [
        Task(key=f"{p}:{a}", persona=p, action=a, label=f"{PERSONAS[p]['name']} · {ACTIONS[a]['label']}")
        for p in personas for a in actions
    ]
    if synthesis and len(tasks) > 1:
        tasks.append(Task(key="chair", persona=None, action=None, label="Chair · Panel synthesis"))
    return tasks


def run_review(job: Job) -> None:
    """Runs in a background thread. Updates job.tasks as each review lands."""
    try:
        settings = load_settings()
        if not settings_status()["ready"]:
            raise ReviewError("Add your provider, model and API key in Settings first.")
        message = document_message(job.doc)
        reviewers = [t for t in job.tasks if t.persona]

        def one(t: Task):
            t.state, t.started = "running", time.time()
            try:
                system = load_persona_prompt(t.persona)
                t.text = ask(settings, system, f"{message}\n\n{ACTIONS[t.action]['prompt']}\n\n{COMMON_RULES}")
                t.state = "done"
            except Exception as e:  # one failed review must not sink the others
                t.state, t.error = "error", str(e)
            t.finished = time.time()

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(one, reviewers))

        done = [t for t in reviewers if t.state == "done"]
        if not done:
            raise ReviewError(reviewers[0].error if reviewers else "Nothing to review.")

        chair = next((t for t in job.tasks if t.key == "chair"), None)
        if chair:
            chair.state, chair.started = "running", time.time()
            body = "\n\n".join(f"## Review: {t.label}\n\n{t.text}" for t in done)
            try:
                chair.text = ask(settings, CHAIR_PROMPT, f"{message}\n\n# Reviews\n\n{body}")
                chair.state = "done"
            except Exception as e:
                chair.state, chair.error = "error", str(e)
            chair.finished = time.time()

        job.state = "rendering"
        md_path = write_report(job, settings)
        job.outputs["md"] = md_path.name
        html, pdf, render_error = render_report(md_path, pdf=job.pdf)
        if html:
            job.outputs["html"] = html.name
        if pdf:
            job.outputs["pdf"] = pdf.name
        if render_error:
            job.outputs["render_error"] = render_error
        job.state = "done"
    except Exception as e:
        job.state, job.error = "error", str(e)


# ---------------------------------------------------------------------------
# 3. Report: a Marp document on page_afp, cut into Letter pages
# ---------------------------------------------------------------------------

# Page geometry from page_afp.css: Letter, 0.55in top, 0.8in bottom, 0.7in sides.
PAGE_PT = (11 - 0.55 - 0.8) * 72 * 0.93       # usable height, with a 7% safety margin
BODY_PT = 11.5 * 1.5                            # body line: 11.5pt at 1.5
LIST_PT = 11.5 * 1.45
TABLE_PX_PER_LINE = 9 * 1.35                    # tables are 9px at 1.35
PX = 0.75                                       # 1px = 0.75pt
TEXT_W_PT = (8.5 - 1.4) * 72
CPL_BODY = 94                                   # characters per line, body text
CPL_LIST = 86
CPL_QUOTE = 74
TABLE_W_CHARS = 120                             # 9px characters across the full table


def _plain_len(s: str) -> int:
    s = re.sub(r"\*\*|__|`|\[([^\]]*)\]\([^)]*\)", lambda m: m.group(1) or "", s)
    return len(s)


def _lines(text: str, cpl: int) -> int:
    return max(1, math.ceil(_plain_len(text) / cpl))


def _split_row(row: str) -> list[str]:
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|") and not row.endswith("\\|"):
        row = row[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", row)]


def table_row_pt(cells: list[str], widths: list[int]) -> float:
    lines = 1
    for cell, w in zip(cells, widths):
        lines = max(lines, math.ceil(max(1, _plain_len(cell)) / max(6, w)))
    return lines * TABLE_PX_PER_LINE * PX + 9 * PX


def table_widths(rows: list[list[str]]) -> list[int]:
    n = max(len(r) for r in rows)
    longest = [max((_plain_len(r[i]) if i < len(r) else 0) for r in rows) for i in range(n)]
    total = sum(max(4, l) for l in longest) or 1
    usable = TABLE_W_CHARS - 2 * n
    return [max(8, int(usable * max(4, l) / total)) for l in longest]


def classify(block: str) -> str:
    first = block.lstrip().splitlines()[0]
    if first.startswith("```"):
        return "code"
    if first.startswith("|"):
        return "table"
    if re.match(r"\s*([-*+]|\d+[.)])\s", first):
        return "list"
    if first.startswith(">"):
        return "quote"
    m = re.match(r"(#{1,6})\s", first)
    if m:
        return f"h{len(m.group(1))}"
    return "para"


def block_height(block: str) -> float:
    kind = classify(block)
    if kind == "code":
        return len(block.splitlines()) * 9 * 1.45 + 20
    if kind == "table":
        rows = [_split_row(r) for r in block.splitlines() if r.strip() and not re.match(r"^\|?[\s:|-]+\|?$", r.strip())]
        if not rows:
            return 0
        w = table_widths(rows)
        return sum(table_row_pt(r, w) for r in rows) + 14 + 4
    if kind == "list":
        items = split_list_items(block)
        return sum(_lines(i, CPL_LIST) * LIST_PT + 2.3 for i in items) + 9
    if kind == "quote":
        return _lines(block, CPL_QUOTE) * 13 * 1.45 + 22
    if kind == "h3":
        return _lines(block, 70) * 12.5 * 1.25 + 18
    if kind in ("h4", "h5", "h6"):
        return _lines(block, 70) * 12 * 1.4 + 30
    return _lines(block, CPL_BODY) * BODY_PT + 8


def split_list_items(block: str) -> list[str]:
    items, cur = [], []
    for line in block.splitlines():
        if re.match(r"([-*+]|\d+[.)])\s", line) and cur:
            items.append("\n".join(cur))
            cur = []
        cur.append(line)
    if cur:
        items.append("\n".join(cur))
    return items


def to_blocks(md: str) -> list[str]:
    """Split Markdown into blocks: paragraphs, whole lists, whole tables, code fences."""
    blocks, cur, fence = [], [], False
    for line in md.splitlines():
        if line.strip().startswith("```"):
            fence = not fence
            cur.append(line)
            if not fence:
                blocks.append("\n".join(cur))
                cur = []
            continue
        if fence:
            cur.append(line)
            continue
        if not line.strip():
            if cur:
                blocks.append("\n".join(cur))
                cur = []
            continue
        # a heading always stands alone
        if re.match(r"#{1,6}\s", line):
            if cur:
                blocks.append("\n".join(cur))
                cur = []
            blocks.append(line)
            continue
        # a table or list starting right under a paragraph line starts a new block
        if cur and classify(line) in ("table", "list") and classify(cur[0]) not in ("table", "list"):
            blocks.append("\n".join(cur))
            cur = []
        cur.append(line)
    if cur:
        blocks.append("\n".join(cur))
    # merge list blocks separated by blank lines (loose lists)
    merged = []
    for b in blocks:
        if merged and classify(b) == "list" and classify(merged[-1]) == "list":
            merged[-1] += "\n" + b
        else:
            merged.append(b)
    return merged


def split_block(block: str, room: float) -> tuple[str | None, str | None]:
    """Cut a block so its first part fits in `room` points. Returns (head, rest)."""
    kind = classify(block)
    if kind == "table":
        lines = [l for l in block.splitlines() if l.strip()]
        header, sep, body = lines[0], lines[1], lines[2:]
        rows = [_split_row(r) for r in [header] + body]
        w = table_widths(rows)
        used = table_row_pt(rows[0], w) + 18
        take = 0
        for r in rows[1:]:
            h = table_row_pt(r, w)
            if used + h > room:
                break
            used += h
            take += 1
        if take == 0:
            return None, block
        head = "\n".join([header, sep] + body[:take])
        rest = "\n".join([header, sep] + body[take:]) if body[take:] else None
        return head, rest
    if kind == "list":
        items = split_list_items(block)
        used, take = 9.0, 0
        for it in items:
            h = _lines(it, CPL_LIST) * LIST_PT + 2.3
            if used + h > room:
                break
            used += h
            take += 1
        if take == 0:
            return None, block
        return "\n".join(items[:take]), ("\n".join(items[take:]) or None)
    if kind == "para":
        sentences = re.split(r"(?<=[.!?])\s+", block)
        take, used = 0, 8.0
        for s in sentences:
            nxt = " ".join(sentences[: take + 1])
            if _lines(nxt, CPL_BODY) * BODY_PT + 8 > room:
                break
            take += 1
        if take == 0:
            return None, block
        return " ".join(sentences[:take]), (" ".join(sentences[take:]) or None)
    return None, block


def paginate(body_md: str, title_pt: float) -> list[str]:
    """Greedy fill: whole blocks while they fit, then cut tables, lists and paragraphs."""
    pages, cur, used = [], [], title_pt
    queue = to_blocks(body_md)
    while queue:
        block = queue.pop(0)
        h = block_height(block)
        if used + h <= PAGE_PT:
            cur.append(block)
            used += h
            continue
        head, rest = split_block(block, PAGE_PT - used)
        # never leave a heading alone at the foot of a page
        if head is None and cur and classify(cur[-1]).startswith("h"):
            queue.insert(0, block)
            queue.insert(0, cur.pop())
            pages.append("\n\n".join(cur))
            cur, used = [], title_pt
            continue
        if head:
            cur.append(head)
        if cur:
            pages.append("\n\n".join(cur))
            cur, used = [], title_pt
            if rest:
                queue.insert(0, rest)
        else:
            # a block taller than a whole page that cannot be cut: give it its own page
            pages.append(block)
            used = title_pt
    if cur:
        pages.append("\n\n".join(cur))
    return pages or [""]


def clean_model_md(text: str) -> str:
    """Make a model answer safe for a Marp page: no page breaks, no title levels."""
    out = []
    for line in text.splitlines():
        if re.fullmatch(r"\s*([-*_])\s*(\1\s*){2,}", line):     # --- *** ___ would start a new page
            continue
        if re.match(r"\s*<!--", line):                         # no Marp directives from the model
            continue
        m = re.match(r"(#{1,6})\s+(.*)", line)
        if m:
            level = len(m.group(1))
            line = ("### " + m.group(2)) if level <= 3 else f"**{m.group(2).strip()}**"
        out.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def split_verdict(text: str) -> tuple[str, str]:
    m = re.search(r"^\s*\**\s*verdict\s*:?\s*\**\s*:?\s*(.+)$", text, flags=re.I | re.M)
    if m:
        verdict = m.group(1).strip().strip("*").strip()
        rest = (text[: m.start()] + text[m.end():]).strip()
        return verdict, rest
    first = re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0]
    return first.strip(), text


def page(cls: str | None, content: str) -> str:
    head = f"<!-- _class: {cls} -->\n\n" if cls else ""
    return head + content.strip() + "\n"


def title_height(title: str, subtitle: str | None) -> float:
    h = _lines(title, 42) * 24 * 1.2 + 8
    if subtitle:
        h += _lines(subtitle, 70) * 15 * 1.25 + 8
    return h


def content_pages(title: str, subtitle: str, body: str, cls: str | None = None) -> list[str]:
    out = []
    chunks = paginate(body, title_height(title, subtitle) + 4)
    for i, chunk in enumerate(chunks):
        sub = subtitle if i == 0 else f"{subtitle} (continued)"
        out.append(page(cls, f"# {title}\n\n## {sub}\n\n{chunk}"))
    return out


def slug(text: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", Path(text).stem).strip("-").lower()
    return (s or "document")[:48]


def human_list(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def document_title(doc: Extracted) -> str:
    """The document's own first heading when it has one, else its file name."""
    if doc.kind in ("Markdown", "Text", "Word"):
        m = re.search(r"^#{1,2}\s+(.+)$", doc.text, flags=re.M)
        if m:
            title = re.sub(r"[*_`]", "", m.group(1)).strip()
            if 3 <= len(title) <= 90:
                return title
    stem = Path(doc.name).stem.replace("_", " ").replace("-", " ").strip()
    return stem[:1].upper() + stem[1:]


def esc_cell(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def build_report(job: Job, settings: dict) -> str:
    """Assemble the review as a Marp document on page_afp (AFP2026_Doc_template.md)."""
    now = datetime.now()
    doc = job.doc
    reviews = [t for t in job.tasks if t.persona]
    chair = next((t for t in job.tasks if t.key == "chair" and t.state == "done"), None)
    persona_names = [PERSONAS[p]["name"] for p in job.personas]
    action_names = [ACTIONS[a]["heading"].lower() for a in job.actions]
    doc_title = document_title(doc)
    in_text = [n[0].lower() + n[1:] if n.startswith("The ") else n for n in persona_names]

    front = (
        "---\nmarp: true\ntheme: page_afp\npaginate: true\nbackgroundColor: white\n"
        f'header: ""\nfooter: "BoardReady · {esc_cell(doc_title)[:60]}"\n---\n'
    )
    pages = []

    # Cover, as in the template: AFP logo drawn by `first`, DWA logo by `partner-dwa`.
    pages.append(page(
        "cover first partner-dwa",
        f"# BoardReady Review\n\n"
        f"## {doc_title}\n\n"
        f"{human_list([a.capitalize() if i == 0 else a for i, a in enumerate(action_names)])} "
        f"by {human_list(in_text)}\n\n"
        f"Think · Ask · Data Wise Academy\n\n"
        f"*{now.strftime('%-d %B %Y')}*",
    ))

    # The brief: what was reviewed, by whom, and each verdict.
    rows = ["| Reviewer | Request | Verdict |", "| --- | --- | --- |"]
    for t in reviews:
        if t.state == "done":
            verdict, _ = split_verdict(clean_model_md(t.text))
        else:
            verdict = f"*Review failed: {t.error}*"
        rows.append(
            f"| **{PERSONAS[t.persona]['name']}** | {ACTIONS[t.action]['label']} | {esc_cell(verdict)} |"
        )
    stats = doc.stats
    facts = [f"{stats.get('words', 0):,} words"]
    if stats.get("sheets"):
        facts.append(f"{stats['sheets']} sheet{'s' if stats['sheets'] > 1 else ''}")
    if stats.get("tables"):
        facts.append(f"{stats['tables']} table{'s' if stats['tables'] > 1 else ''}")
    brief = (
        f"The {doc.kind} file **{esc_cell(doc.name)}** ({', '.join(facts)}) was reviewed by "
        f"{len(job.personas)} persona{'s' if len(job.personas) > 1 else ''} from the Think_Ask kit, "
        f"for {len(reviews)} review{'s' if len(reviews) > 1 else ''} in all."
        + (" A chair then combined them." if chair else "")
        + "\n\n#### Each reviewer's verdict\n\n"
        + "\n".join(rows)
    )
    if doc.notes:
        brief += "\n\n" + "\n".join(f"- {n}" for n in doc.notes)
    brief += (
        "\n\n> The personas critique; they never rewrite. The author stays responsible for every "
        "number."
    )
    pages += content_pages("Review Brief", "What was reviewed, by whom, and each verdict", brief)

    # The chair's synthesis on a sky page, the template's executive-summary ground.
    if chair:
        verdict, rest = split_verdict(clean_model_md(chair.text))
        body = f"**Verdict:** {verdict}\n\n{rest}"
        pages += content_pages("Panel Synthesis", "The chair combines the reviews", body, cls="sky")

    # One divider per persona, then one page (or more) per action.
    for p in job.personas:
        info = PERSONAS[p]
        pages.append(page("divider", f"# {info['name']}\n\n## {info['title']} · {persona_card(p)['role']}"))
        for t in [t for t in reviews if t.persona == p]:
            heading = ACTIONS[t.action]["heading"]
            if t.state != "done":
                pages += content_pages(heading, info["name"], f"#### This review did not run\n\n{t.error}")
                continue
            verdict, rest = split_verdict(clean_model_md(t.text))
            body = f"> {verdict}\n\n{rest}"
            who = info["name"] if info["short"] in info["name"] else f"{info['name']} · {info['short']}"
            pages += content_pages(heading, who, body)

    # Closing page: provenance.
    persona_files = ", ".join(f"`{PERSONAS[p]['file']}`" for p in job.personas)
    pages.append(page(
        "deco",
        "# About This Review\n\n## How it was produced\n\n"
        f"- **Document:** {esc_cell(doc.name)} ({doc.kind})\n"
        f"- **Personas:** {persona_files}, from the Think_Ask folder\n"
        f"- **Requests:** {', '.join(ACTIONS[a]['label'] for a in job.actions)}\n"
        f"- **Model:** {settings.get('MODEL', '?')} ({settings.get('PROVIDER', '?')})\n"
        f"- **Date:** {now.strftime('%-d %B %Y, %H:%M')}\n\n"
        "#### Read it as a pre-mortem, not a verdict\n\n"
        "The personas are fictional. Each one has a stated blind spot, and a model can misread a "
        "figure. Where two reviewers disagree, check the source yourself: that is the same reflex "
        "as tying a number to a second source.\n\n"
        "Styled with `page_afp.css`, on the layout of `AFP2026_Doc_template.md`.",
    ))

    return front + "\n" + "\n---\n\n".join(pages)


def write_report(job: Job, settings: dict) -> Path:
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    path = OUTPUTS / f"{stamp}-{slug(job.doc.name)}-review.md"
    n = 2
    while path.exists():
        path = OUTPUTS / f"{stamp}-{slug(job.doc.name)}-review-{n}.md"
        n += 1
    path.write_text(build_report(job, settings), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# 4. Rendering with the Marp CLI
# ---------------------------------------------------------------------------

def bundled_marp() -> tuple[Path, Path] | None:
    """The packaged app ships Node and the Marp CLI in Contents/Resources/marp."""
    for base in (RES / "marp", Path(sys.executable).resolve().parent.parent / "Resources" / "marp"):
        node, cli = base / "node", base / "node_modules" / "@marp-team" / "marp-cli" / "marp-cli.js"
        if node.exists() and cli.exists():
            return node, cli
    return None


def find_npx() -> str | None:
    found = shutil.which("npx")
    if found:
        return found
    candidates = sorted(glob.glob(os.path.expanduser("~/.nvm/versions/node/*/bin/npx")), reverse=True)
    candidates += ["/opt/homebrew/bin/npx", "/usr/local/bin/npx"]
    return next((c for c in candidates if Path(c).exists()), None)


def marp_status() -> dict:
    npx = find_npx()
    return {"available": bool(bundled_marp() or npx), "npx": npx, "bundled": bool(bundled_marp()), "theme": THEME_CSS.exists()}


# Shown around the pages of the HTML export: Letter sheets on a grey desk.
PAGE_DESK_CSS = """<style>
html{background:#E6EAF0}body{margin:0;padding:28px 16px}
svg[data-marpit-svg]{max-width:860px;margin:0 auto 26px;background:#fff;
box-shadow:0 2px 6px rgba(0,30,60,.12),0 14px 34px rgba(0,30,60,.14)}
</style>"""


def render_report(md_path: Path, pdf: bool = True) -> tuple[Path | None, Path | None, str]:
    env = dict(os.environ)
    packaged = bundled_marp()
    if packaged:
        base = [str(packaged[0]), str(packaged[1])]
    else:
        npx = find_npx()
        if not npx:
            return None, None, "Node.js (npx) was not found, so only the Markdown was written."
        env["PATH"] = str(Path(npx).parent) + os.pathsep + env.get("PATH", "/usr/bin:/bin")
        base = [npx, "--yes", f"@marp-team/marp-cli@{MARP_VERSION}"]
    # Deck path first, --theme-set last: it is an array option and swallows what follows.
    common = ["--allow-local-files", "--no-stdin", "--theme-set", str(THEME_CSS)]
    html_path, pdf_path, errors = md_path.with_suffix(".html"), md_path.with_suffix(".pdf"), []

    def run(args):
        r = subprocess.run(args, capture_output=True, text=True, timeout=240, env=env, stdin=subprocess.DEVNULL)
        if r.returncode != 0:
            errors.append((r.stderr or r.stdout).strip().splitlines()[-1:] or ["Marp failed"])
        return r.returncode == 0

    # No --html: a model's answer is never allowed to inject raw HTML into the report.
    ok_html = run(base + [str(md_path), "--template", "bare", "-o", str(html_path)] + common)
    ok_pdf = run(base + [str(md_path), "--pdf", "-o", str(pdf_path)] + common) if pdf else False
    if ok_html:
        html = html_path.read_text(encoding="utf-8")
        html = html.replace("</head>", PAGE_DESK_CSS + "</head>", 1)
        html_path.write_text(html, encoding="utf-8")
    err = "; ".join(e[0] for e in errors)
    return (html_path if ok_html else None), (pdf_path if ok_pdf else None), err


def list_reviews(limit: int = 12) -> list[dict]:
    if not OUTPUTS.exists():
        return []
    items = []
    for md in sorted(OUTPUTS.glob("*-review*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
        items.append({
            "md": md.name,
            "html": md.with_suffix(".html").name if md.with_suffix(".html").exists() else None,
            "pdf": md.with_suffix(".pdf").name if md.with_suffix(".pdf").exists() else None,
            "modified": datetime.fromtimestamp(md.stat().st_mtime).strftime("%-d %b, %H:%M"),
            "title": re.sub(r"^\d{4}-\d{2}-\d{2}-\d{4}-|-review(-\d+)?$", "", md.stem).replace("-", " "),
        })
    return items
