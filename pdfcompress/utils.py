"""Utility functions for PDF compression."""

import re
from pathlib import Path
from typing import Union


def parse_size(size_str: str) -> int:
    """
    Parse a human-readable size string to bytes.

    Args:
        size_str: Size string like "5MB", "800KB", "1.5GB"

    Returns:
        Size in bytes

    Raises:
        ValueError: If the size string is invalid
    """
    size_str = size_str.strip().upper()

    # Pattern: number (with optional decimal) followed by unit
    match = re.match(r'^([\d.]+)\s*(B|KB|MB|GB|K|M|G)?$', size_str)
    if not match:
        raise ValueError(f"Invalid size format: {size_str}. Use formats like '5MB', '800KB', '1.5GB'")

    value = float(match.group(1))
    unit = match.group(2) or 'B'

    multipliers = {
        'B': 1,
        'K': 1024,
        'KB': 1024,
        'M': 1024 * 1024,
        'MB': 1024 * 1024,
        'G': 1024 * 1024 * 1024,
        'GB': 1024 * 1024 * 1024,
    }

    return int(value * multipliers[unit])


def format_size(size_bytes: int) -> str:
    """
    Format bytes to human-readable string.

    Args:
        size_bytes: Size in bytes

    Returns:
        Human-readable size string
    """
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def calculate_compression_ratio(original_size: int, compressed_size: int) -> float:
    """
    Calculate compression ratio.

    Args:
        original_size: Original file size in bytes
        compressed_size: Compressed file size in bytes

    Returns:
        Compression ratio (e.g., 0.65 means 65% reduction)
    """
    if original_size == 0:
        return 0.0
    return 1 - (compressed_size / original_size)


def get_output_path(
    input_path: Union[str, Path],
    output_path: Union[str, Path, None],
    suffix: str = "_compressed"
) -> Path:
    """
    Determine output file path.

    Args:
        input_path: Input file path
        output_path: Explicit output path or None
        suffix: Suffix to add if no output path specified

    Returns:
        Output file path
    """
    input_path = Path(input_path)

    if output_path:
        return Path(output_path)

    stem = input_path.stem
    return input_path.parent / f"{stem}{suffix}.pdf"


def estimate_quality_score(
    original_size: int,
    compressed_size: int,
    image_percentage: float,
    compression_level: int
) -> str:
    """
    Estimate quality score based on compression parameters.

    Args:
        original_size: Original file size
        compressed_size: Compressed file size
        image_percentage: Percentage of PDF that is images (0-100)
        compression_level: Compression level used (0-100)

    Returns:
        Quality rating string
    """
    ratio = compressed_size / original_size if original_size > 0 else 1.0

    # Higher ratio = less compression = better quality
    if ratio > 0.7:
        return "Excellent"
    elif ratio > 0.5:
        return "Good"
    elif ratio > 0.3:
        return "Fair"
    else:
        # Heavy compression on image-heavy PDFs may still be acceptable
        if image_percentage > 70 and compression_level < 50:
            return "Acceptable"
        return "Reduced"
