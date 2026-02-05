"""
Smart PDF Compressor

A local-first PDF optimization tool that compresses PDFs to a user-defined
target size while preserving maximum visual clarity.
"""

__version__ = "1.0.0"
__author__ = "Smart PDF Compressor Team"

from .analyzer import PDFAnalyzer, AnalysisResult
from .compressor import PDFCompressor, CompressionResult
from .text_handler import TextHandler

__all__ = [
    "PDFAnalyzer",
    "AnalysisResult",
    "PDFCompressor",
    "CompressionResult",
    "TextHandler",
]
