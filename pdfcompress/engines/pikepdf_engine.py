"""pikepdf-based PDF optimization engine."""
import shutil
from pathlib import Path
from typing import Callable, Optional

import pikepdf

from . import CompressionEngine, EngineResult


class PikepdfEngine(CompressionEngine):
    """
    pikepdf engine for PDF structure optimization.

    Best used as a post-processor after image compression.
    Provides:
    - Stream compression
    - Object deduplication
    - Metadata removal
    - Recompression of flate streams
    """

    def is_available(self) -> bool:
        return True  # pikepdf is in requirements.txt

    def get_name(self) -> str:
        return "pikepdf"

    def compress(
        self,
        input_path: Path,
        output_path: Path,
        target_size: int,
        quality_preset: str,
        progress_callback: Optional[Callable[[str, int], None]] = None
    ) -> EngineResult:
        """Optimize PDF structure using pikepdf."""

        try:
            if progress_callback:
                progress_callback("Opening with pikepdf", 10)

            pdf = pikepdf.open(input_path)

            if progress_callback:
                progress_callback("Removing metadata", 30)

            # Remove metadata for size reduction
            try:
                with pdf.open_metadata() as meta:
                    meta.clear()
            except Exception:
                pass  # Some PDFs don't support metadata operations

            if progress_callback:
                progress_callback("Optimizing streams", 60)

            # Save with optimization
            pdf.save(
                output_path,
                compress_streams=True,
                stream_decode_level=pikepdf.StreamDecodeLevel.specialized,
                object_stream_mode=pikepdf.ObjectStreamMode.generate,
                recompress_flate=True,
            )

            pdf.close()

            compressed_size = output_path.stat().st_size

            if progress_callback:
                progress_callback("Complete", 100)

            return EngineResult(
                success=True,
                compressed_size=compressed_size,
                quality_estimate="Excellent",  # pikepdf doesn't degrade quality
                method_used="pikepdf"
            )

        except Exception as e:
            return EngineResult(
                success=False,
                compressed_size=0,
                quality_estimate="N/A",
                method_used="pikepdf",
                error=str(e)
            )

    def post_process(
        self,
        input_path: Path,
        output_path: Path,
        progress_callback: Optional[Callable[[str, int], None]] = None
    ) -> EngineResult:
        """
        Post-process an already compressed PDF for additional optimization.

        This is the primary use case for pikepdf - running after image
        compression to squeeze out additional savings through stream
        optimization.
        """
        return self.compress(input_path, output_path, 0, "balanced", progress_callback)


def optimize_pdf_structure(
    input_path: Path,
    output_path: Path,
    progress_callback: Optional[Callable[[str, int], None]] = None
) -> EngineResult:
    """
    Convenience function for quick PDF structure optimization.

    Args:
        input_path: Path to input PDF
        output_path: Path for optimized output
        progress_callback: Optional progress callback

    Returns:
        EngineResult with optimization outcome
    """
    engine = PikepdfEngine()
    return engine.post_process(input_path, output_path, progress_callback)
