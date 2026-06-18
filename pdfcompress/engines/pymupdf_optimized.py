"""Optimized PyMuPDF-based compression engine with caching and parallel processing."""
import io
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import fitz
from PIL import Image

from . import CompressionEngine, EngineResult

# Guard against decompression-bomb images: a small compressed image that
# declares enormous dimensions can decode into gigabytes of raster and OOM the
# process. Above this pixel count PIL raises DecompressionBombError, which we
# catch and skip.
Image.MAX_IMAGE_PIXELS = 64_000_000  # ~64 megapixels


@dataclass
class CachedImage:
    """Cached image data to avoid re-extraction."""
    xref: int
    original_bytes: bytes
    width: int
    height: int
    mode: str
    pil_image: Optional[Image.Image] = None


class ImageCache:
    """Cache for extracted PDF images - extract once, reuse across iterations."""

    def __init__(self, doc: fitz.Document):
        self.images: Dict[int, CachedImage] = {}
        self._extract_all(doc)

    def _extract_all(self, doc: fitz.Document):
        """Extract all images once and cache them."""
        seen_xrefs = set()

        for page in doc:
            for img in page.get_images(full=True):
                xref = img[0]
                if xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)

                try:
                    base_image = doc.extract_image(xref)
                    if base_image:
                        image_bytes = base_image["image"]
                        pil_img = Image.open(io.BytesIO(image_bytes))
                        # Force a decode so the bomb guard actually triggers
                        # here rather than later during recompression.
                        pil_img.load()

                        self.images[xref] = CachedImage(
                            xref=xref,
                            original_bytes=image_bytes,
                            width=pil_img.width,
                            height=pil_img.height,
                            mode=pil_img.mode,
                            pil_image=pil_img.copy()
                        )
                        pil_img.close()
                except Exception:
                    continue

    def get(self, xref: int) -> Optional[CachedImage]:
        return self.images.get(xref)

    def __len__(self):
        return len(self.images)


class OptimizedPyMuPDFEngine(CompressionEngine):
    """
    Optimized PyMuPDF engine with:
    - Image caching between iterations (extract once)
    - Binary search for optimal quality settings
    - Parallel image processing using ThreadPoolExecutor
    """

    # Quality and DPI levels for compression
    QUALITY_LEVELS = [95, 85, 75, 65, 55, 45, 35, 25]
    DPI_LEVELS = [300, 200, 150, 120, 100, 72]

    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers

    def is_available(self) -> bool:
        return True  # PyMuPDF is a core dependency

    def get_name(self) -> str:
        return "Optimized PyMuPDF"

    def compress(
        self,
        input_path: Path,
        output_path: Path,
        target_size: int,
        quality_preset: str,
        progress_callback: Optional[Callable[[str, int], None]] = None
    ) -> EngineResult:
        """Compress using optimized PyMuPDF approach."""

        try:
            doc = fitz.open(input_path)
            original_size = input_path.stat().st_size

            if progress_callback:
                progress_callback("Caching images", 5)

            # Cache all images once - this is the key optimization
            cache = ImageCache(doc)

            if len(cache) == 0:
                # No images - just optimize the PDF structure
                doc.close()
                return self._optimize_structure_only(
                    input_path, output_path, original_size, progress_callback
                )

            if progress_callback:
                progress_callback("Finding optimal settings", 20)

            # Use binary search to find optimal quality
            config = self._get_config(quality_preset)
            best_result = self._binary_search_compression(
                input_path, cache, output_path, target_size, config, progress_callback
            )

            doc.close()
            return best_result

        except Exception as e:
            return EngineResult(
                success=False,
                compressed_size=0,
                quality_estimate="N/A",
                method_used="pymupdf_optimized",
                error=str(e)
            )

    def _get_config(self, preset: str) -> dict:
        """Get configuration for quality preset."""
        configs = {
            "strict": {"min_quality": 25, "min_dpi": 72, "max_iterations": 8},
            "balanced": {"min_quality": 45, "min_dpi": 100, "max_iterations": 6},
            "high_clarity": {"min_quality": 65, "min_dpi": 150, "max_iterations": 4},
        }
        return configs.get(preset, configs["balanced"])

    def _binary_search_compression(
        self,
        input_path: Path,
        cache: ImageCache,
        output_path: Path,
        target_size: int,
        config: dict,
        progress_callback: Optional[Callable[[str, int], None]]
    ) -> EngineResult:
        """Use binary search to find optimal quality setting."""

        low_quality = config["min_quality"]
        high_quality = 95
        min_dpi = config["min_dpi"]
        best_size = float('inf')
        best_quality = high_quality
        best_output_path = None
        iterations = 0
        max_iterations = config["max_iterations"]

        # Create temp directory for intermediate files
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_dir_path = Path(tmp_dir)

            while low_quality <= high_quality and iterations < max_iterations:
                mid_quality = (low_quality + high_quality) // 2
                iterations += 1

                if progress_callback:
                    progress = 20 + int((iterations / max_iterations) * 60)
                    progress_callback(f"Testing quality {mid_quality}", progress)

                # Use temp file for this attempt
                tmp_output = tmp_dir_path / f"attempt_{iterations}.pdf"

                # Compress with this quality using parallel processing
                compressed_size = self._compress_with_quality_parallel(
                    input_path, cache, tmp_output, mid_quality, min_dpi
                )

                if compressed_size is None:
                    # Compression failed, try lower quality
                    high_quality = mid_quality - 1
                    continue

                if compressed_size <= target_size:
                    # Target achieved - can we get better quality?
                    if compressed_size < best_size or mid_quality > best_quality:
                        best_size = compressed_size
                        best_quality = mid_quality
                        if best_output_path and best_output_path.exists():
                            best_output_path.unlink()
                        best_output_path = tmp_output
                    low_quality = mid_quality + 1
                else:
                    # Need more compression
                    if compressed_size < best_size:
                        best_size = compressed_size
                        best_quality = mid_quality
                        if best_output_path and best_output_path.exists():
                            best_output_path.unlink()
                        best_output_path = tmp_output
                    high_quality = mid_quality - 1

            # Copy best result to output path
            if best_output_path and best_output_path.exists():
                shutil.copy2(best_output_path, output_path)
            else:
                # Fallback: run one more compression with min quality
                if progress_callback:
                    progress_callback("Finalizing", 90)
                compressed_size = self._compress_with_quality_parallel(
                    input_path, cache, output_path, low_quality, min_dpi
                )
                if compressed_size:
                    best_size = compressed_size
                    best_quality = low_quality

        if progress_callback:
            progress_callback("Complete", 100)

        if best_size == float('inf'):
            return EngineResult(
                success=False,
                compressed_size=0,
                quality_estimate="N/A",
                method_used="pymupdf_optimized",
                error="Failed to compress PDF"
            )

        return EngineResult(
            success=True,
            compressed_size=int(best_size),
            quality_estimate=self._quality_to_estimate(best_quality),
            method_used="pymupdf_optimized"
        )

    def _compress_with_quality_parallel(
        self,
        input_path: Path,
        cache: ImageCache,
        output_path: Path,
        quality: int,
        target_dpi: int
    ) -> Optional[int]:
        """Compress images in parallel using cached data."""

        try:
            # Open a fresh copy of the document for modification
            doc = fitz.open(input_path)

            # Process images in parallel
            compressed_images: Dict[int, bytes] = {}

            def process_image(xref: int) -> Tuple[int, Optional[bytes]]:
                cached = cache.get(xref)
                if not cached or not cached.pil_image:
                    return xref, None

                try:
                    pil_image = cached.pil_image.copy()

                    # Convert to RGB for JPEG
                    if pil_image.mode in ("RGBA", "P", "LA"):
                        background = Image.new("RGB", pil_image.size, (255, 255, 255))
                        if pil_image.mode == "P":
                            pil_image = pil_image.convert("RGBA")
                        if pil_image.mode in ("RGBA", "LA"):
                            alpha = pil_image.split()[-1]
                            background.paste(pil_image, mask=alpha)
                            pil_image = background
                        else:
                            pil_image = pil_image.convert("RGB")
                    elif pil_image.mode != "RGB":
                        pil_image = pil_image.convert("RGB")

                    # Scale based on DPI (assume 150 DPI source)
                    scale = min(1.0, target_dpi / 150)
                    if scale < 1.0:
                        new_width = max(10, int(pil_image.width * scale))
                        new_height = max(10, int(pil_image.height * scale))
                        pil_image = pil_image.resize(
                            (new_width, new_height),
                            Image.Resampling.LANCZOS
                        )

                    # Compress to JPEG
                    buffer = io.BytesIO()
                    pil_image.save(buffer, format="JPEG", quality=quality, optimize=True)
                    new_bytes = buffer.getvalue()

                    # Only use if smaller
                    if len(new_bytes) < len(cached.original_bytes):
                        return xref, new_bytes
                    return xref, None

                except Exception:
                    return xref, None

            # Use ThreadPoolExecutor for parallel processing
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {
                    executor.submit(process_image, xref): xref
                    for xref in cache.images
                }
                for future in as_completed(futures):
                    xref, compressed = future.result()
                    if compressed:
                        compressed_images[xref] = compressed

            # Apply compressed images to document
            for page in doc:
                for img in page.get_images(full=True):
                    xref = img[0]
                    if xref in compressed_images:
                        try:
                            page.replace_image(xref, stream=compressed_images[xref])
                        except Exception:
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

            doc.close()
            return output_path.stat().st_size

        except Exception:
            return None

    def _optimize_structure_only(
        self,
        input_path: Path,
        output_path: Path,
        original_size: int,
        progress_callback: Optional[Callable[[str, int], None]]
    ) -> EngineResult:
        """Optimize PDF with no images (text-heavy)."""
        if progress_callback:
            progress_callback("Optimizing structure", 50)

        try:
            doc = fitz.open(input_path)
            doc.save(
                output_path,
                garbage=4,
                deflate=True,
                clean=True,
                deflate_images=True,
                deflate_fonts=True,
            )
            doc.close()

            compressed_size = output_path.stat().st_size

            if progress_callback:
                progress_callback("Complete", 100)

            return EngineResult(
                success=True,
                compressed_size=compressed_size,
                quality_estimate="Excellent",
                method_used="pymupdf_optimized"
            )

        except Exception as e:
            return EngineResult(
                success=False,
                compressed_size=0,
                quality_estimate="N/A",
                method_used="pymupdf_optimized",
                error=str(e)
            )

    def _quality_to_estimate(self, quality: int) -> str:
        """Map quality level to human-readable estimate."""
        if quality >= 75:
            return "Excellent"
        elif quality >= 55:
            return "Good"
        elif quality >= 40:
            return "Fair"
        else:
            return "Reduced"
