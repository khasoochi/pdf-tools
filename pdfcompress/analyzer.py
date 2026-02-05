"""PDF Analysis module for Smart PDF Compressor."""

import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple, Union

import fitz  # PyMuPDF


@dataclass
class ImageInfo:
    """Information about an image in the PDF."""
    page_number: int
    width: int
    height: int
    bits_per_component: int
    colorspace: str
    size_bytes: int
    xref: int
    compression: str = "unknown"


@dataclass
class AnalysisResult:
    """Result of PDF analysis."""
    file_path: str
    file_size: int
    page_count: int
    has_text: bool
    text_character_count: int
    image_count: int
    total_image_bytes: int
    image_percentage: float
    images: List[ImageInfo] = field(default_factory=list)
    pdf_type: str = "mixed"  # "image-heavy", "text-heavy", "mixed"
    estimated_min_size: int = 0
    estimated_max_size: int = 0
    has_embedded_fonts: bool = False
    has_metadata: bool = False
    is_encrypted: bool = False
    error: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "file_path": self.file_path,
            "file_size": self.file_size,
            "page_count": self.page_count,
            "has_text": self.has_text,
            "text_character_count": self.text_character_count,
            "image_count": self.image_count,
            "total_image_bytes": self.total_image_bytes,
            "image_percentage": round(self.image_percentage, 1),
            "pdf_type": self.pdf_type,
            "estimated_min_size": self.estimated_min_size,
            "estimated_max_size": self.estimated_max_size,
            "has_embedded_fonts": self.has_embedded_fonts,
            "has_metadata": self.has_metadata,
            "is_encrypted": self.is_encrypted,
            "error": self.error,
        }


class PDFAnalyzer:
    """Analyzes PDF files to determine structure and estimate compression potential."""

    def __init__(self, pdf_path: Union[str, Path]):
        """
        Initialize analyzer with PDF path.

        Args:
            pdf_path: Path to the PDF file
        """
        self.pdf_path = Path(pdf_path)
        if not self.pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    def analyze(self) -> AnalysisResult:
        """
        Perform comprehensive analysis of the PDF.

        Returns:
            AnalysisResult with all analysis data
        """
        file_size = self.pdf_path.stat().st_size

        try:
            doc = fitz.open(self.pdf_path)
        except Exception as e:
            return AnalysisResult(
                file_path=str(self.pdf_path),
                file_size=file_size,
                page_count=0,
                has_text=False,
                text_character_count=0,
                image_count=0,
                total_image_bytes=0,
                image_percentage=0.0,
                error=f"Failed to open PDF: {str(e)}"
            )

        try:
            # Basic info
            page_count = len(doc)
            is_encrypted = doc.is_encrypted

            # Analyze text content
            text_content = ""
            for page in doc:
                text_content += page.get_text()

            has_text = len(text_content.strip()) > 0
            text_character_count = len(text_content)

            # Analyze images
            images, total_image_bytes = self._analyze_images(doc)
            image_count = len(images)

            # Calculate image percentage of total file
            image_percentage = (total_image_bytes / file_size * 100) if file_size > 0 else 0

            # Determine PDF type
            pdf_type = self._determine_pdf_type(image_percentage, has_text, text_character_count, page_count)

            # Check for embedded fonts
            has_embedded_fonts = self._check_embedded_fonts(doc)

            # Check metadata
            has_metadata = bool(doc.metadata)

            # Estimate achievable compression
            est_min, est_max = self._estimate_compression(
                file_size, image_percentage, images, has_text, has_embedded_fonts
            )

            doc.close()

            return AnalysisResult(
                file_path=str(self.pdf_path),
                file_size=file_size,
                page_count=page_count,
                has_text=has_text,
                text_character_count=text_character_count,
                image_count=image_count,
                total_image_bytes=total_image_bytes,
                image_percentage=image_percentage,
                images=images,
                pdf_type=pdf_type,
                estimated_min_size=est_min,
                estimated_max_size=est_max,
                has_embedded_fonts=has_embedded_fonts,
                has_metadata=has_metadata,
                is_encrypted=is_encrypted,
            )

        except Exception as e:
            doc.close()
            return AnalysisResult(
                file_path=str(self.pdf_path),
                file_size=file_size,
                page_count=0,
                has_text=False,
                text_character_count=0,
                image_count=0,
                total_image_bytes=0,
                image_percentage=0.0,
                error=f"Analysis failed: {str(e)}"
            )

    def _analyze_images(self, doc: fitz.Document) -> Tuple[List[ImageInfo], int]:
        """
        Analyze all images in the PDF.

        Args:
            doc: PyMuPDF document

        Returns:
            Tuple of (list of ImageInfo, total bytes)
        """
        images = []
        total_bytes = 0
        seen_xrefs = set()

        for page_num, page in enumerate(doc):
            image_list = page.get_images(full=True)

            for img in image_list:
                xref = img[0]

                # Skip already processed images (same image on multiple pages)
                if xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)

                try:
                    base_image = doc.extract_image(xref)
                    if base_image:
                        image_bytes = len(base_image["image"])
                        total_bytes += image_bytes

                        # Get colorspace name
                        cs = img[5] if len(img) > 5 else "unknown"

                        images.append(ImageInfo(
                            page_number=page_num + 1,
                            width=base_image.get("width", 0),
                            height=base_image.get("height", 0),
                            bits_per_component=base_image.get("bpc", 8),
                            colorspace=cs,
                            size_bytes=image_bytes,
                            xref=xref,
                            compression=base_image.get("ext", "unknown"),
                        ))
                except Exception:
                    # Some images may not be extractable
                    continue

        return images, total_bytes

    def _determine_pdf_type(
        self,
        image_percentage: float,
        has_text: bool,
        text_count: int,
        page_count: int
    ) -> str:
        """
        Determine if PDF is image-heavy, text-heavy, or mixed.

        Args:
            image_percentage: Percentage of file that is images
            has_text: Whether text was found
            text_count: Number of text characters
            page_count: Number of pages

        Returns:
            PDF type string
        """
        chars_per_page = text_count / page_count if page_count > 0 else 0

        if image_percentage > 70:
            return "image-heavy"
        elif image_percentage < 20 and chars_per_page > 500:
            return "text-heavy"
        else:
            return "mixed"

    def _check_embedded_fonts(self, doc: fitz.Document) -> bool:
        """Check if document has embedded fonts."""
        try:
            for page in doc:
                fonts = page.get_fonts()
                if fonts:
                    return True
        except Exception:
            pass
        return False

    def _estimate_compression(
        self,
        file_size: int,
        image_percentage: float,
        images: List[ImageInfo],
        has_text: bool,
        has_embedded_fonts: bool
    ) -> Tuple[int, int]:
        """
        Estimate achievable compression range.

        Args:
            file_size: Original file size
            image_percentage: Percentage of file that is images
            images: List of image info
            has_text: Whether PDF has text
            has_embedded_fonts: Whether PDF has embedded fonts

        Returns:
            Tuple of (minimum achievable size, maximum achievable size)
        """
        # Base compression factors
        # Images can typically be compressed 50-90%
        # Text/vector content compresses less (10-30%)
        # Fonts can be subsetted for 20-50% savings

        image_fraction = image_percentage / 100
        non_image_fraction = 1 - image_fraction

        # Estimate image compression potential
        # JPEG images: 20-50% reduction with quality tuning
        # PNG images: 30-70% reduction converting to JPEG
        # Uncompressed: 70-90% reduction

        avg_image_reduction_min = 0.3  # Aggressive compression
        avg_image_reduction_max = 0.7  # Conservative compression

        # Check image formats for better estimation
        jpeg_count = sum(1 for img in images if img.compression.lower() in ['jpeg', 'jpg'])
        png_count = sum(1 for img in images if img.compression.lower() == 'png')

        if images:
            jpeg_ratio = jpeg_count / len(images)
            if jpeg_ratio > 0.8:
                # Mostly JPEG - less compression potential
                avg_image_reduction_min = 0.5
                avg_image_reduction_max = 0.8
            elif png_count / len(images) > 0.5:
                # Mostly PNG - more compression potential
                avg_image_reduction_min = 0.2
                avg_image_reduction_max = 0.5

        # Calculate estimated sizes
        image_size = file_size * image_fraction
        non_image_size = file_size * non_image_fraction

        # Non-image content compression (metadata removal, object dedup, etc.)
        non_image_reduction_min = 0.8  # 20% reduction max
        non_image_reduction_max = 0.95  # 5% reduction min

        if has_embedded_fonts:
            # Font subsetting can help
            non_image_reduction_min *= 0.9
            non_image_reduction_max *= 0.95

        min_size = int(
            image_size * avg_image_reduction_min +
            non_image_size * non_image_reduction_min
        )
        max_size = int(
            image_size * avg_image_reduction_max +
            non_image_size * non_image_reduction_max
        )

        # Ensure minimums
        min_size = max(min_size, int(file_size * 0.1))  # At least 10% of original
        max_size = max(max_size, min_size)

        return min_size, max_size

    def quick_analysis(self) -> dict:
        """
        Perform a quick analysis for preview purposes.

        Returns:
            Dictionary with basic stats
        """
        result = self.analyze()
        return {
            "current_size": result.file_size,
            "pages": result.page_count,
            "image_percentage": round(result.image_percentage, 1),
            "text_detected": result.has_text,
            "estimated_min_size": result.estimated_min_size,
            "estimated_max_size": result.estimated_max_size,
            "pdf_type": result.pdf_type,
        }
