#!/usr/bin/env python3
"""
Smart PDF Compressor - CLI Interface

Compress PDFs to a target size while preserving maximum visual clarity.

Usage:
    pdfcompress input.pdf --target 5MB --output output.pdf
    pdfcompress input.pdf --target 800KB --tolerance strict --extract-text
    pdfcompress *.pdf --target 2MB --batch
"""

import json
import sys
from pathlib import Path
from typing import List, Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TimeRemainingColumn,
)
from rich.table import Table

from pdfcompress import PDFAnalyzer, PDFCompressor, TextHandler
from pdfcompress.utils import format_size, get_output_path, parse_size

console = Console()


def create_progress_bar():
    """Create a rich progress bar."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        console=console,
    )


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """Smart PDF Compressor - Compress PDFs to a target size."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@cli.command()
@click.argument("input_file", type=click.Path(exists=True))
@click.option(
    "--target", "-t",
    required=True,
    help="Target file size (e.g., 5MB, 800KB, 1.5GB)",
)
@click.option(
    "--output", "-o",
    type=click.Path(),
    help="Output file path (default: input_compressed.pdf)",
)
@click.option(
    "--tolerance",
    type=click.Choice(["strict", "balanced", "high_clarity"]),
    default="balanced",
    help="Compression tolerance (default: balanced)",
)
@click.option(
    "--extract-text", "-e",
    is_flag=True,
    help="Extract text to a separate .txt file",
)
@click.option(
    "--remove-text", "-r",
    is_flag=True,
    help="Remove text layer from the PDF",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    help="Enable verbose output",
)
@click.option(
    "--json-output", "-j",
    is_flag=True,
    help="Output results as JSON",
)
def compress(
    input_file: str,
    target: str,
    output: Optional[str],
    tolerance: str,
    extract_text: bool,
    remove_text: bool,
    verbose: bool,
    json_output: bool,
):
    """Compress a PDF file to a target size."""
    input_path = Path(input_file)
    target_bytes = parse_size(target)
    output_path = get_output_path(input_path, output)

    results = {}

    if not json_output:
        console.print(Panel(
            f"[bold blue]Smart PDF Compressor[/bold blue]\n"
            f"Input: {input_path.name}\n"
            f"Target: {format_size(target_bytes)}",
            title="Compression Job",
        ))

    # Progress callback for non-JSON output
    current_task = [None]

    def progress_callback(stage: str, percentage: int):
        if not json_output and current_task[0]:
            current_task[0].update(description=stage, completed=percentage)

    with create_progress_bar() as progress:
        if not json_output:
            task = progress.add_task("Initializing...", total=100)
            current_task[0] = progress.tasks[task]

        # Create compressor
        compressor = PDFCompressor(
            input_path,
            target_bytes,
            tolerance=tolerance,
            progress_callback=progress_callback if not json_output else None,
        )

        # Run compression
        result = compressor.compress(output_path)

        if not json_output:
            progress.update(task, completed=100, description="Complete")

    results["compression"] = result.to_dict()

    # Handle text extraction
    if extract_text:
        text_output = output_path.with_suffix(".txt")
        handler = TextHandler(input_path)
        text_result = handler.extract_text(text_output)
        results["text_extraction"] = text_result.to_dict()

        if not json_output and text_result.success:
            console.print(f"[green]Text extracted to: {text_output}[/green]")

    # Handle text removal
    if remove_text:
        notext_output = output_path.with_stem(output_path.stem + "_notext")
        handler = TextHandler(input_path)
        removal_result = handler.remove_text(notext_output)
        results["text_removal"] = removal_result.to_dict()

        if not json_output and removal_result.success:
            console.print(f"[green]Text-free PDF saved to: {notext_output}[/green]")

    # Output results
    if json_output:
        click.echo(json.dumps(results, indent=2))
    else:
        # Display results table
        table = Table(title="Compression Results")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Original Size", format_size(result.original_size))
        table.add_row("Compressed Size", format_size(result.compressed_size))
        table.add_row("Reduction", f"{result.compression_ratio * 100:.1f}%")
        table.add_row("Target Size", format_size(result.target_size))
        table.add_row("Target Achieved", "Yes" if result.target_achieved else "No")
        table.add_row("Quality", result.quality_estimate)
        table.add_row("Pages Processed", str(result.pages_processed))
        table.add_row("Images Processed", str(result.images_processed))

        console.print(table)

        if result.success:
            console.print(f"\n[bold green]Saved to: {output_path}[/bold green]")
        else:
            console.print(f"\n[bold red]Error: {result.error}[/bold red]")
            sys.exit(1)


@cli.command()
@click.argument("input_files", nargs=-1, type=click.Path(exists=True))
@click.option(
    "--target", "-t",
    required=True,
    help="Target file size (e.g., 5MB, 800KB)",
)
@click.option(
    "--output-dir", "-d",
    type=click.Path(),
    help="Output directory (default: same as input)",
)
@click.option(
    "--tolerance",
    type=click.Choice(["strict", "balanced", "high_clarity"]),
    default="balanced",
    help="Compression tolerance",
)
@click.option(
    "--json-output", "-j",
    is_flag=True,
    help="Output results as JSON",
)
def batch(
    input_files: tuple,
    target: str,
    output_dir: Optional[str],
    tolerance: str,
    json_output: bool,
):
    """Batch compress multiple PDF files."""
    if not input_files:
        console.print("[red]No input files specified[/red]")
        sys.exit(1)

    target_bytes = parse_size(target)
    output_directory = Path(output_dir) if output_dir else None

    if output_directory:
        output_directory.mkdir(parents=True, exist_ok=True)

    results = []
    success_count = 0
    fail_count = 0

    with create_progress_bar() as progress:
        overall_task = progress.add_task(
            f"Processing {len(input_files)} files...",
            total=len(input_files)
        )

        for input_file in input_files:
            input_path = Path(input_file)

            if output_directory:
                output_path = output_directory / f"{input_path.stem}_compressed.pdf"
            else:
                output_path = get_output_path(input_path, None)

            compressor = PDFCompressor(input_path, target_bytes, tolerance=tolerance)
            result = compressor.compress(output_path)

            if result.success:
                success_count += 1
            else:
                fail_count += 1

            results.append(result.to_dict())
            progress.update(overall_task, advance=1)

    if json_output:
        click.echo(json.dumps({
            "total": len(input_files),
            "success": success_count,
            "failed": fail_count,
            "results": results,
        }, indent=2))
    else:
        console.print(f"\n[bold]Batch Complete[/bold]")
        console.print(f"[green]Success: {success_count}[/green]")
        if fail_count > 0:
            console.print(f"[red]Failed: {fail_count}[/red]")


@cli.command()
@click.argument("input_file", type=click.Path(exists=True))
@click.option(
    "--json-output", "-j",
    is_flag=True,
    help="Output as JSON",
)
def analyze(input_file: str, json_output: bool):
    """Analyze a PDF file and show compression potential."""
    input_path = Path(input_file)

    analyzer = PDFAnalyzer(input_path)
    result = analyzer.analyze()

    if json_output:
        click.echo(json.dumps(result.to_dict(), indent=2))
    else:
        if result.error:
            console.print(f"[red]Error: {result.error}[/red]")
            sys.exit(1)

        table = Table(title=f"PDF Analysis: {input_path.name}")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Current Size", format_size(result.file_size))
        table.add_row("Pages", str(result.page_count))
        table.add_row("PDF Type", result.pdf_type)
        table.add_row("Image %", f"{result.image_percentage:.1f}%")
        table.add_row("Text Detected", "Yes" if result.has_text else "No")
        table.add_row("Image Count", str(result.image_count))
        table.add_row("Embedded Fonts", "Yes" if result.has_embedded_fonts else "No")
        table.add_row(
            "Est. Min Size",
            f"{format_size(result.estimated_min_size)} - {format_size(result.estimated_max_size)}"
        )

        console.print(table)


@cli.command("extract-text")
@click.argument("input_file", type=click.Path(exists=True))
@click.option(
    "--output", "-o",
    type=click.Path(),
    help="Output text file path",
)
@click.option(
    "--no-page-markers",
    is_flag=True,
    help="Don't include page number markers",
)
def extract_text_cmd(input_file: str, output: Optional[str], no_page_markers: bool):
    """Extract text from a PDF file."""
    input_path = Path(input_file)
    output_path = Path(output) if output else input_path.with_suffix(".txt")

    handler = TextHandler(input_path)
    result = handler.extract_text(
        output_path=output_path,
        include_page_markers=not no_page_markers,
    )

    if result.success:
        console.print(f"[green]Text extracted successfully![/green]")
        console.print(f"Characters: {result.total_characters}")
        console.print(f"Pages with text: {result.pages_with_text}/{result.total_pages}")
        console.print(f"Saved to: {output_path}")
    else:
        console.print(f"[red]Error: {result.error}[/red]")
        sys.exit(1)


@cli.command("remove-text")
@click.argument("input_file", type=click.Path(exists=True))
@click.option(
    "--output", "-o",
    type=click.Path(),
    help="Output PDF file path",
)
def remove_text_cmd(input_file: str, output: Optional[str]):
    """Remove text layer from a PDF file."""
    input_path = Path(input_file)
    output_path = Path(output) if output else input_path.with_stem(input_path.stem + "_notext")

    handler = TextHandler(input_path)
    result = handler.remove_text(output_path)

    if result.success:
        console.print(f"[green]Text removed successfully![/green]")
        console.print(f"Original size: {format_size(result.original_size)}")
        console.print(f"New size: {format_size(result.new_size)}")
        console.print(f"Saved to: {output_path}")
    else:
        console.print(f"[red]Error: {result.error}[/red]")
        sys.exit(1)


def main():
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
