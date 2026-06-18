# Smart PDF Compressor — Web UI

A small Flask app that wraps the `pdfcompress` package in a browser interface:
drag in a PDF, see its analysis, pick a target size, watch live progress, and
download the result.

## Run

```bash
# from the project root, with dependencies installed (pip install -r requirements.txt)
python web/app.py
# open http://127.0.0.1:5000
```

By default the server binds to **loopback only** (`127.0.0.1`) with the Flask
debugger **off** — the Werkzeug debugger is a remote-code-execution risk, so it
must never be enabled on a non-local bind.

## Configuration (environment variables)

| Variable | Default | Purpose |
| --- | --- | --- |
| `PDFCOMPRESS_HOST` | `127.0.0.1` | Bind address. Keep on loopback unless you know what you're doing. |
| `PDFCOMPRESS_PORT` | `5000` | Port. |
| `PDFCOMPRESS_DEBUG` | `false` | Set `1`/`true` to enable the debugger — **local trusted use only**. |
| `PDFCOMPRESS_MAX_UPLOAD_MB` | `200` | Max upload size in MB. |
| `PDFCOMPRESS_MAX_JOBS` | `2` | Max concurrent compression jobs. |
| `FLASK_SECRET_KEY` | random | Stable session secret (set this if you run multiple workers). |

## API

| Method & path | Description |
| --- | --- |
| `GET /` | The web UI. |
| `POST /api/upload` | Multipart upload; returns a `file_id` + analysis JSON. |
| `POST /api/compress` | JSON `{file_id, filename, target_size, tolerance, extract_text, remove_text}`; returns a `job_id`. |
| `GET /api/job/<job_id>` | Poll job status / stage / progress. |
| `GET /api/download/<job_id>/<file_type>` | Download `compressed_pdf` / `extracted_text` / `notext_pdf`. |
| `GET /api/report/<job_id>` | Compression result JSON. |

Uploads and outputs are written to per-session temp folders and auto-cleaned
after ~1 hour. Jobs are tracked in memory (not persistent across restarts).

## Security

This app is meant to run **locally**. The hardening that's in place:

- Loopback bind + debugger off by default.
- Upload validation by extension **and** PDF magic bytes (`%PDF-`).
- Path-traversal guard: `file_id` must be a UUID the server issued and resolved
  paths must stay inside the upload folder; filenames pass through
  `secure_filename`.
- CORS restricted to the app's own origin.
- Bounded worker pool and capped upload size to limit denial-of-service risk.
- Decompression-bomb guard on image decoding (`PIL.Image.MAX_IMAGE_PIXELS`).
- Generic error responses (details are logged server-side, not leaked to clients).

There is **no authentication**. Before exposing this beyond `localhost`, put it
behind a reverse proxy with auth, TLS, and rate limiting.
