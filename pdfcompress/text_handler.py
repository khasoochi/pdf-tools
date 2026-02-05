"""Text extraction and removal module for Smart PDF Compressor."""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple, Union

import fitz  # PyMuPDF


@dataclass
class TextBlock:
    """A block of text from a PDF page."""
    page_number: int
    text: str
    bbox: Tuple[float, float, float, float]  # x0, y0, x1, y1


@dataclass
class TextExtractionResult:
    """Result of text extraction."""
    success: bool
    total_characters: int
    total_pages: int
    pages_with_text: int
    text_content: str
    text_blocks: List[TextBlock]
    output_path: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "success": self.success,
            "total_characters": self.total_characters,
            "total_pages": self.total_pages,
            "pages_with_text": self.pages_with_text,
            "output_path": self.output_path,
            "error": self.error,
        }


@dataclass
class TextRemovalResult:
    """Result of text removal from PDF."""
    success: bool
    input_path: str
    output_path: str
    original_size: int
    new_size: int
    text_removed: bool
    pages_processed: int
    error: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "success": self.success,
            "input_path": self.input_path,
            "output_path": self.output_path,
            "original_size": self.original_size,
            "new_size": self.new_size,
            "text_removed": self.text_removed,
            "pages_processed": self.pages_processed,
            "error": self.error,
        }


class TextHandler:
    """
    Handles text extraction and removal from PDFs.

    Features:
    - Extract all text to a .txt file
    - Remove text layer from PDF (keeping images/graphics)
    - Preserve document structure during extraction
    """

    def __init__(self, pdf_path: Union[str, Path]):
        """
        Initialize text handler.

        Args:
            pdf_path: Path to the PDF file
        """
        self.pdf_path = Path(pdf_path)
        if not self.pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    def extract_text(
        self,
        output_path: Optional[Union[str, Path]] = None,
        include_page_markers: bool = True,
    ) -> TextExtractionResult:
        """
        Extract all text from PDF.

        Args:
            output_path: Path for output text file (optional)
            include_page_markers: Whether to include page number markers

        Returns:
            TextExtractionResult with extracted text
        """
        try:
            doc = fitz.open(self.pdf_path)
        except Exception as e:
            return TextExtractionResult(
                success=False,
                total_characters=0,
                total_pages=0,
                pages_with_text=0,
                text_content="",
                text_blocks=[],
                error=f"Failed to open PDF: {str(e)}",
            )

        try:
            all_text = []
            text_blocks = []
            pages_with_text = 0
            total_pages = len(doc)

            for page_num, page in enumerate(doc):
                page_text = page.get_text("text")

                if page_text.strip():
                    pages_with_text += 1

                    if include_page_markers:
                        all_text.append(f"\n{'='*50}")
                        all_text.append(f"Page {page_num + 1}")
                        all_text.append(f"{'='*50}\n")

                    all_text.append(page_text)

                    # Get text blocks with positions
                    blocks = page.get_text("dict")["blocks"]
                    for block in blocks:
                        if block.get("type") == 0:  # Text block
                            block_text = ""
                            for line in block.get("lines", []):
                                for span in line.get("spans", []):
                                    block_text += span.get("text", "")
                                block_text += "\n"

                            if block_text.strip():
                                text_blocks.append(TextBlock(
                                    page_number=page_num + 1,
                                    text=block_text.strip(),
                                    bbox=tuple(block["bbox"]),
                                ))

            doc.close()

            full_text = "\n".join(all_text)
            total_characters = len(full_text.replace("\n", "").replace(" ", ""))

            # Save to file if output path provided
            saved_path = None
            if output_path:
                output_path = Path(output_path)
                output_path.write_text(full_text, encoding="utf-8")
                saved_path = str(output_path)

            return TextExtractionResult(
                success=True,
                total_characters=total_characters,
                total_pages=total_pages,
                pages_with_text=pages_with_text,
                text_content=full_text,
                text_blocks=text_blocks,
                output_path=saved_path,
            )

        except Exception as e:
            doc.close()
            return TextExtractionResult(
                success=False,
                total_characters=0,
                total_pages=0,
                pages_with_text=0,
                text_content="",
                text_blocks=[],
                error=f"Text extraction failed: {str(e)}",
            )

    def remove_text(
        self,
        output_path: Union[str, Path],
        keep_images: bool = True,
    ) -> TextRemovalResult:
        """
        Remove text layer from PDF.

        This creates a PDF with images/graphics preserved but text removed.
        Useful for sharing documents visually without searchable text.

        Args:
            output_path: Path for output PDF
            keep_images: Whether to preserve images (default True)

        Returns:
            TextRemovalResult with operation details
        """
        output_path = Path(output_path)
        original_size = self.pdf_path.stat().st_size

        try:
            doc = fitz.open(self.pdf_path)
        except Exception as e:
            return TextRemovalResult(
                success=False,
                input_path=str(self.pdf_path),
                output_path=str(output_path),
                original_size=original_size,
                new_size=original_size,
                text_removed=False,
                pages_processed=0,
                error=f"Failed to open PDF: {str(e)}",
            )

        try:
            pages_processed = 0

            for page in doc:
                # Get all text instances and redact them
                # This removes text while keeping the visual layout

                # Method 1: Remove text by redacting text blocks
                text_dict = page.get_text("dict")
                for block in text_dict["blocks"]:
                    if block.get("type") == 0:  # Text block
                        rect = fitz.Rect(block["bbox"])
                        # Add redaction annotation (invisible - just removes text)
                        page.add_redact_annot(rect, fill=None)

                # Apply redactions
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE if keep_images else fitz.PDF_REDACT_IMAGE_REMOVE)

                pages_processed += 1

            # Save the modified PDF
            doc.save(
                output_path,
                garbage=4,
                deflate=True,
                clean=True,
            )

            new_size = output_path.stat().st_size
            doc.close()

            return TextRemovalResult(
                success=True,
                input_path=str(self.pdf_path),
                output_path=str(output_path),
                original_size=original_size,
                new_size=new_size,
                text_removed=True,
                pages_processed=pages_processed,
            )

        except Exception as e:
            doc.close()
            return TextRemovalResult(
                success=False,
                input_path=str(self.pdf_path),
                output_path=str(output_path),
                original_size=original_size,
                new_size=original_size,
                text_removed=False,
                pages_processed=0,
                error=f"Text removal failed: {str(e)}",
            )

    def extract_and_remove(
        self,
        text_output_path: Union[str, Path],
        pdf_output_path: Union[str, Path],
        include_page_markers: bool = True,
    ) -> Tuple[TextExtractionResult, TextRemovalResult]:
        """
        Extract text and remove it from PDF in one operation.

        Args:
            text_output_path: Path for extracted text file
            pdf_output_path: Path for PDF without text
            include_page_markers: Whether to include page markers in text

        Returns:
            Tuple of (TextExtractionResult, TextRemovalResult)
        """
        # First extract text
        extraction_result = self.extract_text(
            output_path=text_output_path,
            include_page_markers=include_page_markers,
        )

        # Then remove text from PDF
        removal_result = self.remove_text(output_path=pdf_output_path)

        return extraction_result, removal_result

    def has_text(self) -> bool:
        """
        Quick check if PDF contains any text.

        Returns:
            True if PDF contains text, False otherwise
        """
        try:
            doc = fitz.open(self.pdf_path)
            for page in doc:
                text = page.get_text().strip()
                if text:
                    doc.close()
                    return True
            doc.close()
            return False
        except Exception:
            return False

    def get_text_stats(self) -> dict:
        """
        Get quick statistics about text in the PDF.

        Returns:
            Dictionary with text statistics
        """
        try:
            doc = fitz.open(self.pdf_path)
            total_chars = 0
            pages_with_text = 0

            for page in doc:
                text = page.get_text().strip()
                if text:
                    pages_with_text += 1
                    total_chars += len(text)

            doc.close()

            return {
                "has_text": total_chars > 0,
                "total_characters": total_chars,
                "total_pages": len(doc),
                "pages_with_text": pages_with_text,
            }
        except Exception as e:
            return {
                "has_text": False,
                "total_characters": 0,
                "total_pages": 0,
                "pages_with_text": 0,
                "error": str(e),
            }
