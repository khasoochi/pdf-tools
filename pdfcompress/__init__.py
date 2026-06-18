"""
Smart PDF Compressor

A local-first PDF optimization tool with hybrid compression engines.
Compresses PDFs to a user-defined target size while preserving maximum visual clarity.

Features:
- Ghostscript engine for fast, high-quality compression (when available)
- Optimized PyMuPDF engine with image caching and parallel processing
- pikepdf post-processor for additional structure optimization
- Automatic engine selection based on availability
"""

__version__ = "2.0.0"
__author__ = "Smart PDF Compressor Team"

from .analyzer import PDFAnalyzer, AnalysisResult
from .compressor import PDFCompressor, CompressionResult, compress_pdf
from .text_handler import TextHandler

# Engine exports for advanced users
from .engines import CompressionEngine, EngineResult
from .engines.ghostscript import GhostscriptEngine
from .engines.pymupdf_optimized import OptimizedPyMuPDFEngine
from .engines.pikepdf_engine import PikepdfEngine

__all__ = [
    # Core classes
    "PDFAnalyzer",
    "AnalysisResult",
    "PDFCompressor",
    "CompressionResult",
    "compress_pdf",
    "TextHandler",
    # Engine classes
    "CompressionEngine",
    "EngineResult",
    "GhostscriptEngine",
    "OptimizedPyMuPDFEngine",
    "PikepdfEngine",
]
