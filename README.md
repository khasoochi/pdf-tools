# Smart PDF Compressor

Compress PDFs down to a **target file size** while keeping them as readable as
possible. It picks the right strategy for the document — heavy image
recompression for scanned/image PDFs, lossless structural optimization for
text PDFs — and stops as soon as it hits your target so quality isn't thrown
away needlessly.

Comes with both a **CLI** and a small **Flask web UI**.

> 🛠️ **Heads up:** this is a fun weekend vibe-coded project — built for the joy
> of it over a couple of evenings. It works and the security basics are covered,
> but it's a hobby tool, not enterprise software. Use it, hack on it, enjoy it.
> See [`features.md`](features.md) for ideas worth adding.

---

## How it works

A hybrid, multi-engine pipeline that keeps the smallest result that still hits
your target:

1. **Analyze** the PDF — pages, image vs. text ratio, embedded fonts, and an
   estimated achievable size range.
2. **Ghostscript** (if installed) — fast, high-quality downsampling via
   `pdfwrite`. Used first unless you opt out.
3. **Optimized PyMuPDF** — pure-Python fallback that caches every image once and
   **binary-searches JPEG quality/DPI** (recompressing images in parallel) to
   land near the target.
4. **pikepdf post-process** — lossless stream/metadata cleanup to squeeze out
   the last few percent if still over target.

Whichever engine produces the smaller file wins. Files already under the target
are copied through untouched.

## Features

- 🎯 Compress to a real target size (`5MB`, `800KB`, `1.5GB`, …).
- 🧠 Automatic image-heavy vs. text-heavy detection with per-type strategy.
- 🔀 Multi-engine pipeline (Ghostscript → PyMuPDF → pikepdf) with auto-fallback.
- 🎛️ Three quality tolerances: `strict`, `balanced`, `high_clarity`.
- 📊 `analyze` command: pages, image %, type, embedded fonts, size estimate.
- 📝 Extract the text layer to `.txt`, or strip text while keeping images.
- 📦 Batch-compress many files at once.
- 🖥️ Rich CLI progress bars + JSON output mode for automation.
- 🌐 Local Flask web UI with drag-and-drop, live progress, and downloads.

## Requirements

- **Python 3.9+**
- **Ghostscript** *(optional but recommended)* — enables the fastest,
  highest-quality engine. Without it, the tool still works via the pure-Python
  PyMuPDF engine.
  - Windows: <https://ghostscript.com/releases/gsdnld.html>
  - macOS: `brew install ghostscript`
  - Linux: `sudo apt install ghostscript`

## Installation

```bash
# from the project directory
pip install -r requirements.txt
pip install .          # installs the `pdfcompress` command
```

For development, an editable install: `pip install -e .`

## CLI usage

The package installs a `pdfcompress` command (also runnable as
`python -m pdfcompress`).

```bash
# Compress to a target size
pdfcompress compress input.pdf --target 5MB --output output.pdf

# Strict quality, also extract text and produce a text-free copy
pdfcompress compress input.pdf -t 800KB --tolerance strict --extract-text --remove-text

# Force the pure-Python engine, emit JSON
pdfcompress compress input.pdf -t 2MB --engine pymupdf --json-output

# See which engines are available on your machine
pdfcompress compress --show-engines

# Batch-compress into a directory
pdfcompress batch *.pdf --target 2MB --output-dir ./out

# Inspect a PDF without compressing
pdfcompress analyze input.pdf

# Text tools
pdfcompress extract-text input.pdf -o text.txt --no-page-markers
pdfcompress remove-text  input.pdf -o input_notext.pdf
```

### `compress` options

| Option | Description |
| --- | --- |
| `INPUT_FILE` | PDF to compress (optional only with `--show-engines`) |
| `-t, --target` | Target size, e.g. `5MB`, `800KB` (binary units; KB = 1024) |
| `-o, --output` | Output path (default `<input>_compressed.pdf`) |
| `--tolerance` | `strict` \| `balanced` \| `high_clarity` (default `balanced`) |
| `-e, --extract-text` | Also write the text layer to `<output>.txt` |
| `-r, --remove-text` | Also write a text-free `<stem>_notext.pdf` |
| `--engine` | `auto` \| `ghostscript` \| `pymupdf` (default `auto`) |
| `-j, --json-output` | Machine-readable JSON result |
| `--show-engines` | Print engine availability and exit |

**Tolerance presets** map to Ghostscript quality (and PyMuPDF quality floors):
`strict` ≈ screen/72dpi, `balanced` ≈ ebook/150dpi, `high_clarity` ≈
printer/300dpi (may exceed the target to preserve clarity).

## Web UI

```bash
python web/app.py
# then open http://127.0.0.1:5000
```

Drag in a PDF, see the analysis, choose a target size and tolerance, watch live
progress, and download the compressed PDF (plus extracted text / text-free PDF
if requested). See [`web/README.md`](web/README.md) for configuration and
deployment notes.

## Library usage

```python
from pdfcompress import compress_pdf, PDFAnalyzer
from pdfcompress.utils import parse_size

info = PDFAnalyzer("input.pdf").analyze()
print(info.pdf_type, info.image_percentage)

# target_size is in bytes — use parse_size() to turn "2MB" into an int
result = compress_pdf("input.pdf", "out.pdf", parse_size("2MB"), tolerance="balanced")
print(result.compressed_size, result.target_achieved, result.engine_used)
```

## Project layout

```
pdfcompress/            # core package
├── cli.py              # Click CLI (compress/batch/analyze/extract-text/remove-text)
├── analyzer.py         # PDF analysis + size estimation
├── compressor.py       # hybrid pipeline orchestration
├── text_handler.py     # text extraction / removal
├── utils.py            # size parsing, formatting, helpers
└── engines/            # ghostscript, pymupdf_optimized, pikepdf_engine
web/                    # Flask web UI (app.py, templates, static)
features.md             # backlog of ideas / future features
to-do.md                # product/vision doc
```

## Security notes

The web UI is intended to run **locally**. It binds to `127.0.0.1` with the
debugger off by default, validates uploads (PDF magic bytes), guards file paths
against traversal, restricts CORS to its own origin, caps concurrent jobs, and
limits upload size. If you expose it beyond localhost, add authentication and a
reverse proxy first. Configurable via environment variables — see
[`web/README.md`](web/README.md).

## License

[MIT](LICENSE)
