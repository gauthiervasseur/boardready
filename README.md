# BoardReady

A Mac app that submits a Markdown, Word or Excel document to the three Think_Ask personas and returns one review document in the AFP style.

- **Who reviews it:** Elena Varga (the Skeptical CFO), the Group Controller and the Red-Team Reviewer. Pick any of them.
- **What you ask for:** criticize, review for consistency, suggest enrichments. Pick any of them. Every chosen persona answers every chosen request.
- **What you get:** a Marp document on `page_afp`, laid out like `4_Communicate/AFP2026_Doc_template.md`, plus HTML and PDF exports, in `outputs/`.

The persona prompts are read live from `02-persona-skeptical-cfo.md`, `03-persona-controller.md` and `04-persona-red-team-reviewer.md` in the Think_Ask folder. Edit a persona file and the next review uses the new version.

## The DMG (for anyone)

`./build_dmg.sh` builds `dist/BoardReady.dmg` (about 100 MB): a self-contained app for Apple-silicon Macs. Python, the UI, the website, copies of the three persona files, the sample memo, `page_afp.css`, Node and the Marp CLI are all inside; no API key is. Users drag it to Applications, right-click › Open the first time (the app is ad-hoc signed, not notarized), and add their provider, model and key in **Settings**, which saves them to `~/Library/Application Support/BoardReady/settings.env`. Reviews go to `~/Documents/BoardReady`. The PDF export needs Chrome or Edge.

The personas inside the DMG are copies: after editing a persona file, run `./build_dmg.sh` again. The build copies Node and Marp CLI 4.5.1 from this Mac (the npx cache), and builds Python in a clean uv environment.

## Run it from the workshop folder

| How | Command |
|---|---|
| Mac app | `./build_app.sh` once, then double-click **BoardReady.app** |
| Browser (the "website" version of the app) | `uv run app.py --browser` |
| Server only | `uv run app.py --serve` (prints the address) |
| Without uv | `pip install -r requirements.txt`, then `python3 app.py --browser` |

The presentation website is `site/index.html`. Open it from the folder, or at `/site/` while the app runs.

**Needs:** an API key in `Think_Ask/.env`, the same file `08-premortem-agent.py` uses. Copy `example.env`, or enter the key in the app's Settings, which writes that file. Node.js and Google Chrome are needed for the HTML and PDF exports (Marp CLI runs through `npx`). pandoc gives the best Word import; without it the app falls back to python-docx.

`build_app.sh` writes this folder's path into the app, so you can drag the app to Applications or the Dock. If you move the folder, run the script again. The app's log is `~/Library/Logs/BoardReady.log`.

## Files

| File | Role |
|---|---|
| `app.py` | Local server on 127.0.0.1, native window (pywebview) or browser |
| `review_engine.py` | Extraction, prompts, parallel model calls, report layout, Marp export |
| `web/` | The app: `index.html`, `app.css` (on top of `styles/page_afp.css`), `app.js`, portraits, icon |
| `site/` | The presentation website, with screenshots and a sample review |
| `build_app.sh` | Builds a light `BoardReady.app` that runs this folder's code with uv |
| `build_dmg.sh` | Builds the self-contained `dist/BoardReady.dmg` |
| `outputs/` | Every review: `.md`, `.html`, `.pdf` |

## How a review runs

1. The document becomes Markdown. Word goes through pandoc. Excel is read sheet by sheet: the saved values as tables, then up to 40 formulas per sheet. Sheets and CSV files are cut at 400 rows, and both the reviewer and the report say so.
2. Each persona × request pair is one model call, with the persona file as instructions. Up to four calls run at once.
3. If more than one review ran and the chair's synthesis is on, a chair combines them. It must not add objections of its own.
4. The answers are cleaned (no `#` titles, no `---`, which would start a new page) and paginated onto Letter pages, with tables and lists split across pages when needed.
5. Marp exports the document to HTML and PDF with `--theme-set ../../styles/page_afp.css`.

On the sample memo, nine reviews plus the chair took about 40 seconds with `claude-sonnet-5-5`.

## Change it

- **A persona's wording:** edit its file in Think_Ask.
- **A new persona:** add its file (with the prompt in a ```` ```text ```` block), a portrait in `web/portraits/`, and an entry in `PERSONAS` at the top of `review_engine.py`.
- **A request:** edit or add an entry in `ACTIONS` in `review_engine.py`. Its `prompt` replaces the persona's Output section.
- **The model:** `MODEL` in `Think_Ask/.env`.

Older `.doc` and `.xls` files are not read: save them as `.docx` or `.xlsx` first.
