"""PDF Compression engine for Smart PDF Compressor."""

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Union

from .analyzer import AnalysisResult, PDFAnalyzer
from .engines import EngineResult
from .engines.ghostscript import GhostscriptEngine
from .engines.pikepdf_engine import PikepdfEngine
from .engines.pymupdf_optimized import OptimizedPyMuPDFEngine
from .utils import calculate_compression_ratio, estimate_quality_score, format_size


@dataclass
class CompressionResult:
    """Result of PDF compression."""
    success: bool
    input_path: str
    output_path: str
    original_size: int
    compressed_size: int
    compression_ratio: float
    quality_estimate: str
    pages_processed: int
    images_processed: int
    target_size: int
    target_achieved: bool
    iterations: int = 1
    engine_used: str = "auto"
    error: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "success": self.success,
            "input_path": self.input_path,
            "output_path": self.output_path,
            "original_size": self.original_size,
            "original_size_formatted": format_size(self.original_size),
            "compressed_size": self.compressed_size,
            "compressed_size_formatted": format_size(self.compressed_size),
            "compression_ratio": round(self.compression_ratio * 100, 1),
            "quality_estimate": self.quality_estimate,
            "pages_processed": self.pages_processed,
            "images_processed": self.images_processed,
            "target_size": self.target_size,
            "target_size_formatted": format_size(self.target_size),
            "target_achieved": self.target_achieved,
            "iterations": self.iterations,
            "engine_used": self.engine_used,
            "error": self.error,
        }


class CompressionStage:
    """Enumeration of compression stages for progress reporting."""
    ANALYZING = "Analyzing PDF"
    PROCESSING_IMAGES = "Processing images"
    OPTIMIZING_OBJECTS = "Optimizing objects"
    FINALIZING = "Finalizing PDF"


class PDFCompressor:
    """
    PDF compression engine with hybrid multi-engine approach.

    Compression strategy:
    1. Try Ghostscript first (fastest, best compression) if available
    2. If unavailable or target not met, use optimized PyMuPDF
    3. Post-process with pikepdf for additional optimization

    Features:
    - Automatic engine selection based on availability
    - Image caching and parallel processing (PyMuPDF engine)
    - Binary search for optimal quality settings
    - Fallback chain for maximum compatibility
    """

    def __init__(
        self,
        pdf_path: Union[str, Path],
        target_size: int,
        tolerance: str = "balanced",
        progress_callback: Optional[Callable[[str, int], None]] = None,
        prefer_engine: Optional[str] = None,
    ):
        """
        Initialize compressor.

        Args:
            pdf_path: Path to input PDF
            target_size: Target size in bytes
            tolerance: "strict", "balanced", or "high_clarity"
            progress_callback: Optional callback for progress updates (stage, percentage)
            prefer_engine: Engine preference - "auto", "ghostscript", or "pymupdf"
        """
        self.pdf_path = Path(pdf_path)
        self.target_size = target_size
        self.tolerance = tolerance
        self.progress_callback = progress_callback
        self.prefer_engine = prefer_engine or "auto"

        # Initialize engines
        self._gs_engine = GhostscriptEngine()
        self._pymupdf_engine = OptimizedPyMuPDFEngine()
        self._pikepdf_engine = PikepdfEngine()

        if not self.pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    def _report_progress(self, stage: str, percentage: int):
        """Report progress if callback is set."""
        if self.progress_callback:
            self.progress_callback(stage, percentage)

    def compress(self, output_path: Union[str, Path]) -> CompressionResult:
        """
        Compress PDF to target size using hybrid engine approach.

        Args:
            output_path: Path for output PDF

        Returns:
            CompressionResult with compression details
        """
        output_path = Path(output_path)
        original_size = self.pdf_path.stat().st_size

        # If already under target, just copy
        if original_size <= self.target_size:
            shutil.copy2(self.pdf_path, output_path)
            return CompressionResult(
                success=True,
                input_path=str(self.pdf_path),
                output_path=str(output_path),
                original_size=original_size,
                compressed_size=original_size,
                compression_ratio=0.0,
                quality_estimate="Excellent",
                pages_processed=0,
                images_processed=0,
                target_size=self.target_size,
                target_achieved=True,
                engine_used="none (already under target)",
            )

        self._report_progress(CompressionStage.ANALYZING, 0)

        # Analyze the PDF
        analyzer = PDFAnalyzer(self.pdf_path)
        analysis = analyzer.analyze()

        if analysis.error:
            return CompressionResult(
                success=False,
                input_path=str(self.pdf_path),
                output_path=str(output_path),
                original_size=original_size,
                compressed_size=original_size,
                compression_ratio=0.0,
                quality_estimate="N/A",
                pages_processed=0,
                images_processed=0,
                target_size=self.target_size,
                target_achieved=False,
                error=analysis.error,
            )

        self._report_progress(CompressionStage.ANALYZING, 100)

        # Strategy 1: Try Ghostscript first (if available and not disabled)
        if self._should_try_ghostscript():
            result = self._try_ghostscript(output_path, analysis)
            if result and result.target_achieved:
                return result
            # Keep the result if it's the best we have so far
            gs_result = result
        else:
            gs_result = None

        # Strategy 2: Use optimized PyMuPDF
        result = self._try_optimized_pymupdf(output_path, analysis)

        # If Ghostscript was better, use that instead
        if gs_result and gs_result.success:
            if not result.success or gs_result.compressed_size < result.compressed_size:
                # Re-run Ghostscript to final output
                gs_final = self._try_ghostscript(output_path, analysis)
                if gs_final:
                    result = gs_final

        # Strategy 3: Post-process with pikepdf if still above target
        if result.success and result.compressed_size > self.target_size:
            post_result = self._try_pikepdf_postprocess(output_path, result, analysis)
            if post_result.compressed_size < result.compressed_size:
                result = post_result

        return result

    def _should_try_ghostscript(self) -> bool:
        """Determine if we should try Ghostscript."""
        if self.prefer_engine == "pymupdf":
            return False
        return self._gs_engine.is_available()

    def _try_ghostscript(
        self,
        output_path: Path,
        analysis: AnalysisResult
    ) -> Optional[CompressionResult]:
        """Try compression with Ghostscript."""
        self._report_progress("Trying Ghostscript compression", 10)

        engine_result = self._gs_engine.compress(
            self.pdf_path,
            output_path,
            self.target_size,
            self.tolerance,
            self.progress_callback
        )

        if not engine_result.success:
            return None

        ratio = calculate_compression_ratio(analysis.file_size, engine_result.compressed_size)

        return CompressionResult(
            success=True,
            input_path=str(self.pdf_path),
            output_path=str(output_path),
            original_size=analysis.file_size,
            compressed_size=engine_result.compressed_size,
            compression_ratio=ratio,
            quality_estimate=engine_result.quality_estimate,
            pages_processed=analysis.page_count,
            images_processed=analysis.image_count,
            target_size=self.target_size,
            target_achieved=engine_result.compressed_size <= self.target_size,
            iterations=1,
            engine_used="ghostscript",
        )

    def _try_optimized_pymupdf(
        self,
        output_path: Path,
        analysis: AnalysisResult
    ) -> CompressionResult:
        """Compress using optimized PyMuPDF engine."""
        self._report_progress("Using optimized PyMuPDF", 20)

        engine_result = self._pymupdf_engine.compress(
            self.pdf_path,
            output_path,
            self.target_size,
            self.tolerance,
            self.progress_callback
        )

        ratio = calculate_compression_ratio(analysis.file_size, engine_result.compressed_size)

        return CompressionResult(
            success=engine_result.success,
            input_path=str(self.pdf_path),
            output_path=str(output_path),
            original_size=analysis.file_size,
            compressed_size=engine_result.compressed_size,
            compression_ratio=ratio,
            quality_estimate=engine_result.quality_estimate,
            pages_processed=analysis.page_count,
            images_processed=analysis.image_count,
            target_size=self.target_size,
            target_achieved=engine_result.compressed_size <= self.target_size,
            engine_used="pymupdf_optimized",
            error=engine_result.error,
        )

    def _try_pikepdf_postprocess(
        self,
        output_path: Path,
        previous_result: CompressionResult,
        analysis: AnalysisResult
    ) -> CompressionResult:
        """Post-process with pikepdf for additional compression."""
        self._report_progress("Post-processing with pikepdf", 90)

        # Save current output to temp, then optimize to final path
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            # Copy current output to temp
            shutil.copy2(output_path, tmp_path)

            # Optimize with pikepdf
            engine_result = self._pikepdf_engine.post_process(tmp_path, output_path)

            if engine_result.success and engine_result.compressed_size < previous_result.compressed_size:
                ratio = calculate_compression_ratio(analysis.file_size, engine_result.compressed_size)
                return CompressionResult(
                    success=True,
                    input_path=str(self.pdf_path),
                    output_path=str(output_path),
                    original_size=analysis.file_size,
                    compressed_size=engine_result.compressed_size,
                    compression_ratio=ratio,
                    quality_estimate=previous_result.quality_estimate,
                    pages_processed=analysis.page_count,
                    images_processed=previous_result.images_processed,
                    target_size=self.target_size,
                    target_achieved=engine_result.compressed_size <= self.target_size,
                    engine_used=f"{previous_result.engine_used}+pikepdf",
                )
        finally:
            # Cleanup
            if tmp_path.exists():
                tmp_path.unlink()

        return previous_result

    @staticmethod
    def get_available_engines() -> dict:
        """
        Get information about available compression engines.

        Returns:
            Dictionary with engine availability status
        """
        gs = GhostscriptEngine()
        return {
            "ghostscript": {
                "available": gs.is_available(),
                "description": "Fast external compression (requires Ghostscript installed)",
            },
            "pymupdf_optimized": {
                "available": True,
                "description": "Optimized PyMuPDF with image caching and parallel processing",
            },
            "pikepdf": {
                "available": True,
                "description": "PDF structure optimization (post-processor)",
            },
        }


def compress_pdf(
    input_path: Union[str, Path],
    output_path: Union[str, Path],
    target_size: int,
    tolerance: str = "balanced",
    progress_callback: Optional[Callable[[str, int], None]] = None,
    prefer_engine: Optional[str] = None,
) -> CompressionResult:
    """
    Convenience function to compress a PDF.

    Args:
        input_path: Path to input PDF
        output_path: Path for output PDF
        target_size: Target size in bytes
        tolerance: "strict", "balanced", or "high_clarity"
        progress_callback: Optional progress callback
        prefer_engine: Optional engine preference ("auto", "ghostscript", "pymupdf")

    Returns:
        CompressionResult
    """
    compressor = PDFCompressor(
        input_path, target_size, tolerance, progress_callback, prefer_engine
    )
    return compressor.compress(output_path)
