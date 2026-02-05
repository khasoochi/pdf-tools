"""PDF Compression engine for Smart PDF Compressor."""

import io
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, Union

import fitz  # PyMuPDF
from PIL import Image

from .analyzer import AnalysisResult, PDFAnalyzer
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
    PDF compression engine with iterative optimization.

    Compresses PDFs to a target size while preserving maximum quality.
    Uses progressive optimization techniques including:
    - Image downscaling (adaptive DPI)
    - JPEG recompression with quality tuning
    - Metadata removal
    - Object deduplication
    """

    # Quality levels for iterative compression
    QUALITY_LEVELS = [95, 85, 75, 65, 55, 45, 35, 25]

    # DPI levels for image downscaling
    DPI_LEVELS = [300, 200, 150, 120, 100, 72]

    def __init__(
        self,
        pdf_path: Union[str, Path],
        target_size: int,
        tolerance: str = "balanced",
        progress_callback: Optional[Callable[[str, int], None]] = None,
    ):
        """
        Initialize compressor.

        Args:
            pdf_path: Path to input PDF
            target_size: Target size in bytes
            tolerance: "strict", "balanced", or "high_clarity"
            progress_callback: Optional callback for progress updates (stage, percentage)
        """
        self.pdf_path = Path(pdf_path)
        self.target_size = target_size
        self.tolerance = tolerance
        self.progress_callback = progress_callback

        # Tolerance affects how aggressively we compress
        self.tolerance_config = {
            "strict": {"max_iterations": 10, "min_quality": 25, "min_dpi": 72},
            "balanced": {"max_iterations": 6, "min_quality": 45, "min_dpi": 100},
            "high_clarity": {"max_iterations": 4, "min_quality": 65, "min_dpi": 150},
        }

        if not self.pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    def _report_progress(self, stage: str, percentage: int):
        """Report progress if callback is set."""
        if self.progress_callback:
            self.progress_callback(stage, percentage)

    def compress(self, output_path: Union[str, Path]) -> CompressionResult:
        """
        Compress PDF to target size.

        Args:
            output_path: Path for output PDF

        Returns:
            CompressionResult with compression details
        """
        output_path = Path(output_path)
        original_size = self.pdf_path.stat().st_size

        # If already under target, just copy
        if original_size <= self.target_size:
            import shutil
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

        # Determine compression strategy based on PDF type
        if analysis.pdf_type == "image-heavy":
            return self._compress_image_heavy(output_path, analysis)
        elif analysis.pdf_type == "text-heavy":
            return self._compress_text_heavy(output_path, analysis)
        else:
            return self._compress_mixed(output_path, analysis)

    def _compress_image_heavy(
        self,
        output_path: Path,
        analysis: AnalysisResult
    ) -> CompressionResult:
        """Compress image-heavy PDF with focus on image optimization."""
        config = self.tolerance_config[self.tolerance]
        best_result = None
        best_size = analysis.file_size

        iteration = 0
        for quality in self.QUALITY_LEVELS:
            if quality < config["min_quality"]:
                break

            for dpi in self.DPI_LEVELS:
                if dpi < config["min_dpi"]:
                    break

                iteration += 1
                if iteration > config["max_iterations"]:
                    break

                progress = min(90, int((iteration / config["max_iterations"]) * 90))
                self._report_progress(CompressionStage.PROCESSING_IMAGES, progress)

                # Try compression with these settings
                result = self._compress_with_settings(
                    output_path, quality, dpi, analysis
                )

                if result.success:
                    if result.compressed_size <= self.target_size:
                        # Target achieved
                        self._report_progress(CompressionStage.FINALIZING, 100)
                        result.target_achieved = True
                        result.iterations = iteration
                        return result

                    if result.compressed_size < best_size:
                        best_result = result
                        best_size = result.compressed_size

            if iteration > config["max_iterations"]:
                break

        self._report_progress(CompressionStage.FINALIZING, 100)

        # Return best result even if target not achieved
        if best_result:
            best_result.target_achieved = best_result.compressed_size <= self.target_size
            return best_result

        return CompressionResult(
            success=False,
            input_path=str(self.pdf_path),
            output_path=str(output_path),
            original_size=analysis.file_size,
            compressed_size=analysis.file_size,
            compression_ratio=0.0,
            quality_estimate="N/A",
            pages_processed=0,
            images_processed=0,
            target_size=self.target_size,
            target_achieved=False,
            error="Could not achieve target size",
        )

    def _compress_text_heavy(
        self,
        output_path: Path,
        analysis: AnalysisResult
    ) -> CompressionResult:
        """Compress text-heavy PDF with focus on object optimization."""
        self._report_progress(CompressionStage.OPTIMIZING_OBJECTS, 30)

        # For text-heavy PDFs, focus on:
        # - Metadata removal
        # - Object deduplication
        # - Stream compression
        # - Font subsetting

        try:
            doc = fitz.open(self.pdf_path)

            # Apply garbage collection and compression
            doc.save(
                output_path,
                garbage=4,  # Maximum garbage collection
                deflate=True,  # Compress streams
                clean=True,  # Clean content streams
                deflate_images=True,
                deflate_fonts=True,
            )

            compressed_size = output_path.stat().st_size

            self._report_progress(CompressionStage.FINALIZING, 100)

            doc.close()

            ratio = calculate_compression_ratio(analysis.file_size, compressed_size)
            quality = estimate_quality_score(
                analysis.file_size, compressed_size,
                analysis.image_percentage, 90
            )

            return CompressionResult(
                success=True,
                input_path=str(self.pdf_path),
                output_path=str(output_path),
                original_size=analysis.file_size,
                compressed_size=compressed_size,
                compression_ratio=ratio,
                quality_estimate=quality,
                pages_processed=analysis.page_count,
                images_processed=0,
                target_size=self.target_size,
                target_achieved=compressed_size <= self.target_size,
            )

        except Exception as e:
            return CompressionResult(
                success=False,
                input_path=str(self.pdf_path),
                output_path=str(output_path),
                original_size=analysis.file_size,
                compressed_size=analysis.file_size,
                compression_ratio=0.0,
                quality_estimate="N/A",
                pages_processed=0,
                images_processed=0,
                target_size=self.target_size,
                target_achieved=False,
                error=str(e),
            )

    def _compress_mixed(
        self,
        output_path: Path,
        analysis: AnalysisResult
    ) -> CompressionResult:
        """Compress mixed PDF with balanced approach."""
        # Use image-heavy approach with slightly more conservative settings
        return self._compress_image_heavy(output_path, analysis)

    def _compress_with_settings(
        self,
        output_path: Path,
        quality: int,
        target_dpi: int,
        analysis: AnalysisResult
    ) -> CompressionResult:
        """
        Compress PDF with specific quality and DPI settings.

        Args:
            output_path: Output file path
            quality: JPEG quality (1-100)
            target_dpi: Target DPI for images
            analysis: PDF analysis result

        Returns:
            CompressionResult
        """
        try:
            doc = fitz.open(self.pdf_path)
            images_processed = 0

            # Process each page
            for page_num, page in enumerate(doc):
                images = page.get_images(full=True)

                for img in images:
                    xref = img[0]

                    try:
                        # Extract and recompress image
                        base_image = doc.extract_image(xref)
                        if not base_image:
                            continue

                        image_bytes = base_image["image"]
                        img_ext = base_image["ext"]

                        # Load image with Pillow
                        pil_image = Image.open(io.BytesIO(image_bytes))

                        # Convert to RGB if necessary for JPEG
                        if pil_image.mode in ("RGBA", "P", "LA"):
                            # Create white background for transparency
                            background = Image.new("RGB", pil_image.size, (255, 255, 255))
                            if pil_image.mode == "P":
                                pil_image = pil_image.convert("RGBA")
                            if pil_image.mode in ("RGBA", "LA"):
                                background.paste(pil_image, mask=pil_image.split()[-1])
                                pil_image = background
                            else:
                                pil_image = pil_image.convert("RGB")
                        elif pil_image.mode != "RGB":
                            pil_image = pil_image.convert("RGB")

                        # Calculate scaling based on DPI
                        # Assume 72 DPI is the baseline
                        current_dpi = 150  # Assume moderate source DPI
                        scale = min(1.0, target_dpi / current_dpi)

                        if scale < 1.0:
                            new_size = (
                                int(pil_image.width * scale),
                                int(pil_image.height * scale)
                            )
                            if new_size[0] > 10 and new_size[1] > 10:
                                pil_image = pil_image.resize(
                                    new_size,
                                    Image.Resampling.LANCZOS
                                )

                        # Compress to JPEG
                        img_buffer = io.BytesIO()
                        pil_image.save(
                            img_buffer,
                            format="JPEG",
                            quality=quality,
                            optimize=True
                        )

                        # Only replace if smaller
                        new_image_bytes = img_buffer.getvalue()
                        if len(new_image_bytes) < len(image_bytes):
                            # Replace image in PDF
                            page.replace_image(xref, stream=new_image_bytes)
                            images_processed += 1

                    except Exception:
                        # Skip problematic images
                        continue

            # Save with optimization
            doc.save(
                output_path,
                garbage=4,
                deflate=True,
                clean=True,
                deflate_images=True,
                deflate_fonts=True,
            )

            compressed_size = output_path.stat().st_size
            doc.close()

            ratio = calculate_compression_ratio(analysis.file_size, compressed_size)
            quality_est = estimate_quality_score(
                analysis.file_size, compressed_size,
                analysis.image_percentage, quality
            )

            return CompressionResult(
                success=True,
                input_path=str(self.pdf_path),
                output_path=str(output_path),
                original_size=analysis.file_size,
                compressed_size=compressed_size,
                compression_ratio=ratio,
                quality_estimate=quality_est,
                pages_processed=analysis.page_count,
                images_processed=images_processed,
                target_size=self.target_size,
                target_achieved=compressed_size <= self.target_size,
            )

        except Exception as e:
            return CompressionResult(
                success=False,
                input_path=str(self.pdf_path),
                output_path=str(output_path),
                original_size=analysis.file_size,
                compressed_size=analysis.file_size,
                compression_ratio=0.0,
                quality_estimate="N/A",
                pages_processed=0,
                images_processed=0,
                target_size=self.target_size,
                target_achieved=False,
                error=str(e),
            )


def compress_pdf(
    input_path: Union[str, Path],
    output_path: Union[str, Path],
    target_size: int,
    tolerance: str = "balanced",
    progress_callback: Optional[Callable[[str, int], None]] = None,
) -> CompressionResult:
    """
    Convenience function to compress a PDF.

    Args:
        input_path: Path to input PDF
        output_path: Path for output PDF
        target_size: Target size in bytes
        tolerance: "strict", "balanced", or "high_clarity"
        progress_callback: Optional progress callback

    Returns:
        CompressionResult
    """
    compressor = PDFCompressor(
        input_path, target_size, tolerance, progress_callback
    )
    return compressor.compress(output_path)
