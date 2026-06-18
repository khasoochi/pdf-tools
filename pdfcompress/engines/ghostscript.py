"""Ghostscript-based PDF compression engine."""
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Optional

from . import CompressionEngine, EngineResult


class GhostscriptEngine(CompressionEngine):
    """
    High-performance compression using Ghostscript.

    Presets map to Ghostscript PDFSETTINGS:
    - /screen: 72 dpi (smallest, lowest quality)
    - /ebook: 150 dpi (good balance, 50-70% reduction typical)
    - /printer: 300 dpi (high quality)
    - /prepress: 300 dpi (highest quality, preserves colors)
    """

    PRESETS = {
        "strict": "/screen",       # Maximum compression
        "balanced": "/ebook",      # Good balance
        "high_clarity": "/printer" # High quality
    }

    def __init__(self):
        self._gs_path = self._find_ghostscript()

    def _find_ghostscript(self) -> Optional[str]:
        """Find Ghostscript executable."""
        # Check common names across platforms
        for name in ["gs", "gswin64c", "gswin32c", "gswin64", "gswin32"]:
            path = shutil.which(name)
            if path:
                return path
        return None

    def is_available(self) -> bool:
        """Check if Ghostscript is installed."""
        return self._gs_path is not None

    def get_name(self) -> str:
        return "Ghostscript"

    def compress(
        self,
        input_path: Path,
        output_path: Path,
        target_size: int,
        quality_preset: str,
        progress_callback: Optional[Callable[[str, int], None]] = None
    ) -> EngineResult:
        """Compress using Ghostscript."""
        if not self.is_available():
            return EngineResult(
                success=False,
                compressed_size=0,
                quality_estimate="N/A",
                method_used="ghostscript",
                error="Ghostscript not installed"
            )

        preset = self.PRESETS.get(quality_preset, "/ebook")

        if progress_callback:
            progress_callback("Compressing with Ghostscript", 10)

        # Build Ghostscript command
        cmd = [
            self._gs_path,
            "-sDEVICE=pdfwrite",
            f"-dPDFSETTINGS={preset}",
            "-dNOPAUSE",
            "-dQUIET",
            "-dBATCH",
            "-dCompatibilityLevel=1.4",
            "-dDetectDuplicateImages=true",
            "-dCompressFonts=true",
            "-dSubsetFonts=true",
            f"-sOutputFile={output_path}",
            str(input_path)
        ]

        try:
            if progress_callback:
                progress_callback("Running Ghostscript", 30)

            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=300,  # 5 minute timeout
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )

            if result.returncode != 0:
                error_msg = result.stderr.decode(errors='replace').strip()
                return EngineResult(
                    success=False,
                    compressed_size=0,
                    quality_estimate="N/A",
                    method_used="ghostscript",
                    error=f"Ghostscript error: {error_msg or 'Unknown error'}"
                )

            if not output_path.exists():
                return EngineResult(
                    success=False,
                    compressed_size=0,
                    quality_estimate="N/A",
                    method_used="ghostscript",
                    error="Output file not created"
                )

            compressed_size = output_path.stat().st_size

            if progress_callback:
                progress_callback("Ghostscript compression complete", 100)

            return EngineResult(
                success=True,
                compressed_size=compressed_size,
                quality_estimate=self._estimate_quality(preset),
                method_used="ghostscript"
            )

        except subprocess.TimeoutExpired:
            return EngineResult(
                success=False,
                compressed_size=0,
                quality_estimate="N/A",
                method_used="ghostscript",
                error="Ghostscript timeout (exceeded 5 minutes)"
            )
        except Exception as e:
            return EngineResult(
                success=False,
                compressed_size=0,
                quality_estimate="N/A",
                method_used="ghostscript",
                error=str(e)
            )

    def _estimate_quality(self, preset: str) -> str:
        """Map preset to quality estimate."""
        mapping = {
            "/screen": "Reduced",
            "/ebook": "Good",
            "/printer": "Excellent",
            "/prepress": "Excellent"
        }
        return mapping.get(preset, "Good")

    def compress_iterative(
        self,
        input_path: Path,
        output_path: Path,
        target_size: int,
        progress_callback: Optional[Callable[[str, int], None]] = None
    ) -> EngineResult:
        """
        Try multiple presets to achieve target size.

        Tries from highest quality to lowest, stopping when target is achieved.
        """
        if not self.is_available():
            return EngineResult(
                success=False,
                compressed_size=0,
                quality_estimate="N/A",
                method_used="ghostscript",
                error="Ghostscript not installed"
            )

        # Order from highest quality to lowest
        presets_to_try = [
            ("high_clarity", "/printer"),
            ("balanced", "/ebook"),
            ("strict", "/screen"),
        ]

        best_result = None

        for preset_name, preset_value in presets_to_try:
            if progress_callback:
                progress_callback(f"Trying {preset_name} preset", 30)

            # Use temp file for intermediate attempts
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp_path = Path(tmp.name)

            try:
                result = self.compress(
                    input_path,
                    tmp_path,
                    target_size,
                    preset_name,
                    None  # Don't pass callback for sub-attempts
                )

                if result.success:
                    best_result = result

                    if result.compressed_size <= target_size:
                        # Target achieved - copy to output and return
                        shutil.copy2(tmp_path, output_path)
                        tmp_path.unlink()

                        if progress_callback:
                            progress_callback("Target achieved", 100)

                        return EngineResult(
                            success=True,
                            compressed_size=result.compressed_size,
                            quality_estimate=result.quality_estimate,
                            method_used="ghostscript"
                        )

                tmp_path.unlink()

            except Exception:
                if tmp_path.exists():
                    tmp_path.unlink()
                continue

        # If we get here, no preset achieved target - use best result with strictest setting
        if best_result:
            # Run final compression with strictest preset
            final_result = self.compress(
                input_path,
                output_path,
                target_size,
                "strict",
                progress_callback
            )
            return final_result

        return EngineResult(
            success=False,
            compressed_size=0,
            quality_estimate="N/A",
            method_used="ghostscript",
            error="All presets failed"
        )
