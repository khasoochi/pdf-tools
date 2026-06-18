#!/usr/bin/env python3
"""
Smart PDF Compressor - Flask Web Application

A local web interface for PDF compression with real-time progress tracking.
"""

import os
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, Optional

from flask import (
    Flask,
    jsonify,
    render_template,
    request,
    send_file,
)
from flask_cors import CORS
from werkzeug.utils import secure_filename

# Add parent directory to path to import pdfcompress
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from pdfcompress import PDFAnalyzer, PDFCompressor, TextHandler
from pdfcompress.utils import format_size, parse_size

app = Flask(__name__)
# Use a stable secret from the environment in production; fall back to a random
# one for local dev (sessions won't survive a restart, which is fine locally).
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or os.urandom(24)

# Restrict CORS to the app's own origin. The UI is served from the same origin,
# so no wildcard cross-origin access is needed.
CORS(app, origins=["http://127.0.0.1:5000", "http://localhost:5000"])

# Configuration
UPLOAD_FOLDER = Path(tempfile.gettempdir()) / "pdfcompress_uploads"
OUTPUT_FOLDER = Path(tempfile.gettempdir()) / "pdfcompress_output"
ALLOWED_EXTENSIONS = {"pdf"}
# Max upload size (override with PDFCOMPRESS_MAX_UPLOAD_MB). Smaller is safer:
# it limits the blast radius of decompression-bomb PDFs.
MAX_UPLOAD_MB = int(os.environ.get("PDFCOMPRESS_MAX_UPLOAD_MB", "200"))
MAX_CONTENT_LENGTH = MAX_UPLOAD_MB * 1024 * 1024
# Cap concurrent compression jobs so a flood of requests can't exhaust the box.
MAX_CONCURRENT_JOBS = int(os.environ.get("PDFCOMPRESS_MAX_JOBS", "2"))

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["OUTPUT_FOLDER"] = OUTPUT_FOLDER
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

# Create folders with restrictive permissions (best effort; no-op on Windows).
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
for _folder in (UPLOAD_FOLDER, OUTPUT_FOLDER):
    try:
        os.chmod(_folder, 0o700)
    except OSError:
        pass

# Job tracking
jobs: Dict[str, dict] = {}
jobs_lock = threading.Lock()
# Bounded worker pool: backs the compression jobs instead of unbounded threads.
executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_JOBS)


def allowed_file(filename: str) -> bool:
    """Check if file extension is allowed."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def is_pdf(file_path: Path) -> bool:
    """Verify the file actually starts with the PDF magic bytes."""
    try:
        with open(file_path, "rb") as fh:
            return fh.read(5) == b"%PDF-"
    except OSError:
        return False


def resolve_upload_path(file_id: str, filename: str) -> Optional[Path]:
    """Safely resolve an uploaded file path, guarding against path traversal.

    Returns the resolved path if (and only if) ``file_id`` is a UUID we issued
    and the final path stays inside UPLOAD_FOLDER. Returns None otherwise.
    """
    try:
        uuid.UUID(str(file_id))
    except (ValueError, TypeError, AttributeError):
        return None

    safe_name = secure_filename(filename or "")
    if not safe_name:
        return None

    upload_root = UPLOAD_FOLDER.resolve()
    candidate = (upload_root / f"{file_id}_{safe_name}").resolve()
    if upload_root not in candidate.parents:
        return None
    return candidate


def cleanup_old_files(max_age_hours: int = 1):
    """Clean up files older than max_age_hours."""
    now = time.time()
    max_age_seconds = max_age_hours * 3600

    for folder in [UPLOAD_FOLDER, OUTPUT_FOLDER]:
        for file_path in folder.iterdir():
            if file_path.is_file():
                age = now - file_path.stat().st_mtime
                if age > max_age_seconds:
                    try:
                        file_path.unlink()
                    except Exception:
                        pass


@app.route("/")
def index():
    """Serve the main page."""
    return render_template("index.html")


@app.route("/api/upload", methods=["POST"])
def upload_file():
    """Handle PDF upload and return analysis."""
    cleanup_old_files()

    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]

    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    if not allowed_file(file.filename):
        return jsonify({"error": "Only PDF files are allowed"}), 400

    # Generate unique ID for this upload
    file_id = str(uuid.uuid4())
    filename = secure_filename(file.filename)
    file_path = UPLOAD_FOLDER / f"{file_id}_{filename}"

    file.save(file_path)

    # Defense in depth: reject anything that isn't actually a PDF, regardless
    # of its extension.
    if not is_pdf(file_path):
        file_path.unlink(missing_ok=True)
        return jsonify({"error": "Not a valid PDF file"}), 400

    # Analyze the PDF
    try:
        analyzer = PDFAnalyzer(file_path)
        analysis = analyzer.analyze()

        if analysis.error:
            return jsonify({"error": analysis.error}), 400

        return jsonify({
            "file_id": file_id,
            "filename": filename,
            "analysis": {
                "current_size": analysis.file_size,
                "current_size_formatted": format_size(analysis.file_size),
                "pages": analysis.page_count,
                "image_percentage": round(analysis.image_percentage, 1),
                "text_detected": analysis.has_text,
                "pdf_type": analysis.pdf_type,
                "estimated_min_size": analysis.estimated_min_size,
                "estimated_min_size_formatted": format_size(analysis.estimated_min_size),
                "estimated_max_size": analysis.estimated_max_size,
                "estimated_max_size_formatted": format_size(analysis.estimated_max_size),
                "image_count": analysis.image_count,
                "has_embedded_fonts": analysis.has_embedded_fonts,
            }
        })

    except Exception:
        app.logger.exception("Upload analysis failed")
        return jsonify({"error": "Failed to analyze PDF"}), 500


@app.route("/api/compress", methods=["POST"])
def start_compression():
    """Start compression job."""
    data = request.get_json()

    if not data:
        return jsonify({"error": "No data provided"}), 400

    file_id = data.get("file_id")
    filename = secure_filename(data.get("filename") or "")
    target_size_str = data.get("target_size")
    tolerance = data.get("tolerance", "balanced")
    extract_text = data.get("extract_text", False)
    remove_text = data.get("remove_text", False)

    if not all([file_id, filename, target_size_str]):
        return jsonify({"error": "Missing required fields"}), 400

    # Find the uploaded file, guarding against path traversal: file_id must be a
    # UUID we issued and the resolved path must stay inside UPLOAD_FOLDER.
    file_path = resolve_upload_path(file_id, filename)
    if file_path is None:
        return jsonify({"error": "Invalid file reference"}), 400
    if not file_path.exists():
        return jsonify({"error": "File not found. Please upload again."}), 404

    # Parse target size
    try:
        target_bytes = parse_size(target_size_str)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    # Create job
    job_id = str(uuid.uuid4())

    with jobs_lock:
        jobs[job_id] = {
            "status": "starting",
            "stage": "Initializing",
            "progress": 0,
            "file_id": file_id,
            "filename": filename,
            "target_size": target_bytes,
            "result": None,
            "error": None,
            "output_files": {},
        }

    # Submit to the bounded worker pool (caps concurrent compressions).
    executor.submit(
        run_compression_job,
        job_id, file_path, target_bytes, tolerance, extract_text, remove_text,
    )

    return jsonify({"job_id": job_id})


def run_compression_job(
    job_id: str,
    file_path: Path,
    target_bytes: int,
    tolerance: str,
    extract_text: bool,
    remove_text: bool,
):
    """Run compression job in background."""
    def progress_callback(stage: str, percentage: int):
        with jobs_lock:
            if job_id in jobs:
                jobs[job_id]["stage"] = stage
                jobs[job_id]["progress"] = percentage
                jobs[job_id]["status"] = "processing"

    try:
        # Create output path
        output_filename = file_path.stem.replace(f"{jobs[job_id]['file_id']}_", "") + "_compressed.pdf"
        output_path = OUTPUT_FOLDER / f"{job_id}_{output_filename}"

        # Run compression
        compressor = PDFCompressor(
            file_path,
            target_bytes,
            tolerance=tolerance,
            progress_callback=progress_callback,
        )

        result = compressor.compress(output_path)

        output_files = {}

        if result.success:
            output_files["compressed_pdf"] = str(output_path)

            # Handle text extraction
            if extract_text:
                text_output = output_path.with_suffix(".txt")
                handler = TextHandler(file_path)
                text_result = handler.extract_text(text_output)
                if text_result.success:
                    output_files["extracted_text"] = str(text_output)

            # Handle text removal
            if remove_text:
                notext_output = OUTPUT_FOLDER / f"{job_id}_{file_path.stem}_notext.pdf"
                handler = TextHandler(file_path)
                removal_result = handler.remove_text(notext_output)
                if removal_result.success:
                    output_files["notext_pdf"] = str(notext_output)

        with jobs_lock:
            jobs[job_id]["status"] = "completed" if result.success else "failed"
            jobs[job_id]["stage"] = "Complete" if result.success else "Failed"
            jobs[job_id]["progress"] = 100
            jobs[job_id]["result"] = result.to_dict()
            jobs[job_id]["output_files"] = output_files
            if not result.success:
                jobs[job_id]["error"] = result.error

    except Exception:
        app.logger.exception("Compression job %s failed", job_id)
        with jobs_lock:
            jobs[job_id]["status"] = "failed"
            jobs[job_id]["stage"] = "Error"
            jobs[job_id]["error"] = "Compression failed"


@app.route("/api/job/<job_id>")
def get_job_status(job_id: str):
    """Get job status and progress."""
    with jobs_lock:
        if job_id not in jobs:
            return jsonify({"error": "Job not found"}), 404

        job = jobs[job_id].copy()

    return jsonify(job)


@app.route("/api/download/<job_id>/<file_type>")
def download_file(job_id: str, file_type: str):
    """Download output file."""
    with jobs_lock:
        if job_id not in jobs:
            return jsonify({"error": "Job not found"}), 404

        job = jobs[job_id]

        if job["status"] != "completed":
            return jsonify({"error": "Job not completed"}), 400

        if file_type not in job["output_files"]:
            return jsonify({"error": "File not found"}), 404

        file_path = Path(job["output_files"][file_type])

    if not file_path.exists():
        return jsonify({"error": "File no longer available"}), 404

    # Determine download filename
    original_name = job["filename"].replace(".pdf", "")
    if file_type == "compressed_pdf":
        download_name = f"{original_name}_compressed.pdf"
    elif file_type == "extracted_text":
        download_name = f"{original_name}_text.txt"
    elif file_type == "notext_pdf":
        download_name = f"{original_name}_notext.pdf"
    else:
        download_name = file_path.name

    return send_file(
        file_path,
        as_attachment=True,
        download_name=download_name,
    )


@app.route("/api/report/<job_id>")
def get_report(job_id: str):
    """Get compression report as JSON."""
    with jobs_lock:
        if job_id not in jobs:
            return jsonify({"error": "Job not found"}), 404

        job = jobs[job_id]

        if job["status"] != "completed":
            return jsonify({"error": "Job not completed"}), 400

    return jsonify(job["result"])


if __name__ == "__main__":
    # Bind to loopback by default and keep the debugger off — the Werkzeug
    # debugger is a remote-code-execution risk if exposed. Override only for
    # trusted local dev via env vars.
    host = os.environ.get("PDFCOMPRESS_HOST", "127.0.0.1")
    port = int(os.environ.get("PDFCOMPRESS_PORT", "5000"))
    debug = os.environ.get("PDFCOMPRESS_DEBUG", "").lower() in ("1", "true", "yes")

    print("Starting Smart PDF Compressor Web Server...")
    print(f"Open http://{host}:{port} in your browser")
    app.run(debug=debug, host=host, port=port)
