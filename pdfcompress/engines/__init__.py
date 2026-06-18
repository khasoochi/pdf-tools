"""Compression engine abstraction for PDF optimization."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional


@dataclass
class EngineResult:
    """Result from a compression engine."""
    success: bool
    compressed_size: int
    quality_estimate: str
    method_used: str
    error: Optional[str] = None


class CompressionEngine(ABC):
    """Abstract base class for compression engines."""

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this engine is available on the system."""
        pass

    @abstractmethod
    def compress(
        self,
        input_path: Path,
        output_path: Path,
        target_size: int,
        quality_preset: str,
        progress_callback: Optional[Callable[[str, int], None]] = None
    ) -> EngineResult:
        """
        Perform compression.

        Args:
            input_path: Path to input PDF
            output_path: Path for compressed output
            target_size: Target file size in bytes
            quality_preset: One of "strict", "balanced", "high_clarity"
            progress_callback: Optional callback for progress updates

        Returns:
            EngineResult with compression outcome
        """
        pass

    @abstractmethod
    def get_name(self) -> str:
        """Return engine name for logging."""
        pass
