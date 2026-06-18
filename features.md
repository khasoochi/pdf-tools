# Ideas & Future Features

A running wishlist of things that would be fun (or genuinely useful) to add to
Smart PDF Compressor. Nothing here is promised — it's a backlog of directions
the project could grow in. PRs welcome.

> This started as a weekend vibe-coded project, so treat this list as
> "if I get another rainy Saturday…" rather than a roadmap.

## Compression & quality

- **Per-page compression strategy** — analyze each page individually and apply
  the best engine/quality per page instead of one setting for the whole doc.
- **Real size-estimation engine** — simulate compression on a sample of pages to
  predict the achievable size *before* running the full job (the product doc
  describes this; it isn't fully wired up yet).
- **Smarter "minimum achievable size" guard** — fail fast with a clear message
  when the requested target is physically smaller than the content allows.
- **Lossless mode** — pikepdf-only path that guarantees zero visual change, for
  users who only want structural/stream optimization.
- **Perceptual quality scoring (SSIM/LPIPS)** — score compressed output against
  the original so the tool can stop at "good enough" instead of a fixed quality
  floor.
- **Image downsampling presets per use case** — e.g. "email", "print",
  "archive", "web" instead of raw KB/MB targets.
- **WebP / AVIF image recompression** — modern codecs can beat JPEG inside PDFs
  where viewers support them.

## OCR & content

- **OCR for scanned PDFs** (Tesseract / ocrmypdf) — add a real text layer to
  image-only documents so `extract-text` and search actually work.
- **Searchable-PDF output** — combine OCR + compression in one pass.
- **Selective text removal** — redact by regex/keyword (e.g. emails, card
  numbers) instead of stripping the whole text layer.
- **Metadata scrubbing toggle** — explicit `--strip-metadata` / keep-metadata
  control (author, timestamps, GPS in embedded images).

## CLI & UX

- **Folder / recursive compression** — point it at a directory and walk it.
- **Per-stage ETA and progress** — "estimated time remaining" per page/stage.
- **`report.json` artifact** — machine-readable run report alongside the output.
- **Dry-run mode** — show predicted result and engine plan without writing files.
- **Config file support** — `.pdfcompressrc` for default tolerance/engine.
- **Shell completion** — generate completions for bash/zsh/fish via Click.

## Web app

- **Drag-and-drop folder / multi-file upload** with a batch queue.
- **Live preview** — first-page thumbnail before/after compression.
- **WebSocket progress** instead of polling `/api/job/<id>`.
- **Persistent job store** (SQLite/Redis) so jobs survive a server restart.
- **Auth + rate limiting** for any public deployment.
- **Download-all-as-zip** for batch results.

## Platform & distribution

- **Cloud batch API** — submit many PDFs, poll for results.
- **Docker image** — bundle Ghostscript so the "best" engine is always available.
- **Prebuilt binaries** (PyInstaller) for non-Python users.
- **GitHub Action** — compress PDFs in a repo on push.
- **Python API examples / cookbook** — document the importable
  `PDFCompressor` / `compress_pdf` API for library users.

## Engineering / quality of life

- **Test suite** — unit tests for `parse_size`, the analyzer heuristics, and a
  golden-file test per engine.
- **CI** — lint + tests on push (GitHub Actions).
- **Benchmark harness** — track size/time/quality across engines on a sample
  corpus.
- **Type checking** — `mypy`/`pyright` pass over the package.
- **Resolve known inconsistencies** — version string mismatch
  (`setup.py` 1.0.0 vs `__init__.py` 2.0.0), unused `--verbose` flag, and the
  unwired `compress_iterative()` / `estimate_quality_score()` helpers.
