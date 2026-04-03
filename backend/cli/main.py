#!/usr/bin/env python3
"""
Classic Car Analysis CLI

Command-line interface for processing classic car videos and generating summaries.
"""

from pathlib import Path
from typing import Optional

import typer
from app.config import get_settings
from app.services.agent_service import AgentService
from app.services.downloader import VideoDownloader
from app.services.video_service import VideoService
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.table import Table

app = typer.Typer(
    name="car-analysis",
    help="AI-powered classic car video analysis tool",
    add_completion=False
)

console = Console()


@app.command()
def process(
    video_path: Path = typer.Argument(..., help="Path to video file"),
    output_dir: Optional[Path] = typer.Option(
        None, "--output", "-o",
        help="Output directory for processed files"
    ),
    model_size: str = typer.Option(
        "medium", "--model", "-m",
        help="Whisper model size (tiny, base, small, medium, large)"
    ),
    skip_summary: bool = typer.Option(
        False, "--skip-summary",
        help="Skip the AI summary generation step"
    )
):
    """
    Process a video file and generate analysis summary.

    This command extracts audio, transcribes it, and generates an AI summary
    of the classic car details mentioned in the video.
    """
    if not video_path.exists():
        console.print(f"[red]Error: Video file not found: {video_path}[/red]")
        raise typer.Exit(1)

    settings = get_settings()

    if output_dir:
        settings.data_dir = output_dir

    settings.whisper_model_size = model_size
    settings.ensure_directories()

    video_service = VideoService()

    console.print(Panel(f"Processing: [bold]{video_path.name}[/bold]"))

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console
    ) as progress:
        task = progress.add_task("Processing video...", total=100)

        def update_progress(step, pct):
            step_names = {
                "extracting_audio": "Extracting audio",
                "transcribing": "Transcribing audio",
                "saving_transcript": "Saving transcript",
                "creating_subtitles": "Creating subtitles",
                "adding_subtitles": "Adding subtitles",
                "extracting_frames": "Extracting frames",
                "complete": "Video processing complete"
            }
            progress.update(task, completed=pct, description=step_names.get(step, step))

        result = video_service.process_video(str(video_path), update_progress)

    console.print("[green]Video processing complete![/green]")
    console.print(f"  Transcript: {result.transcript_json_path}")

    if not skip_summary:
        console.print("\n[bold]Generating AI summary...[/bold]")

        agent_service = AgentService()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Analyzing transcript...", total=None)

            agent_service.process_transcript(result.transcript_json_path)

        transcript_name = Path(result.transcript_json_path).name
        summary = agent_service.get_summary(transcript_name)
        cost = agent_service.get_cost(transcript_name)
        vehicle_info = agent_service.extract_vehicle_info(transcript_name)

        table = Table(title="Vehicle Information")
        table.add_column("Field", style="cyan")
        table.add_column("Value", style="green")
        table.add_row("Make", vehicle_info.get("make") or "-")
        table.add_row("Model", vehicle_info.get("model") or "-")
        table.add_row("Year", vehicle_info.get("year") or "-")
        console.print(table)

        console.print("\n[bold]Summary:[/bold]")
        console.print(Panel(summary or "No summary generated"))
        console.print(f"\n[dim]Processing cost: ${cost:.6f}[/dim]")

        output_path = agent_service.save_summary(transcript_name, str(settings.results_dir))
        console.print(f"[green]Summary saved to: {output_path}[/green]")


@app.command()
def summarize(
    transcript_path: Path = typer.Argument(..., help="Path to transcript JSON file"),
    output_dir: Optional[Path] = typer.Option(
        None, "--output", "-o",
        help="Output directory for summary file"
    )
):
    """
    Generate summary from an existing transcript file.

    Use this if you already have a transcript JSON and just want to run
    the AI analysis.
    """
    if not transcript_path.exists():
        console.print(f"[red]Error: Transcript file not found: {transcript_path}[/red]")
        raise typer.Exit(1)

    settings = get_settings()
    if output_dir:
        settings.results_dir = output_dir

    agent_service = AgentService()

    console.print(Panel(f"Analyzing: [bold]{transcript_path.name}[/bold]"))

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        progress.add_task("Processing transcript...", total=None)
        agent_service.process_transcript(str(transcript_path))

    transcript_name = transcript_path.name
    summary = agent_service.get_summary(transcript_name)
    cost = agent_service.get_cost(transcript_name)
    vehicle_info = agent_service.extract_vehicle_info(transcript_name)

    table = Table(title="Vehicle Information")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Make", vehicle_info.get("make") or "-")
    table.add_row("Model", vehicle_info.get("model") or "-")
    table.add_row("Year", vehicle_info.get("year") or "-")
    console.print(table)

    console.print("\n[bold]Summary:[/bold]")
    console.print(Panel(summary or "No summary generated"))
    console.print(f"\n[dim]Processing cost: ${cost:.6f}[/dim]")

    output_path = agent_service.save_summary(transcript_name, str(settings.results_dir))
    console.print(f"[green]Summary saved to: {output_path}[/green]")


@app.command()
def download(
    url: str = typer.Argument(..., help="YouTube or video URL"),
    output_dir: Optional[Path] = typer.Option(
        None, "--output", "-o",
        help="Output directory for downloaded video"
    ),
    process_video: bool = typer.Option(
        True, "--process/--no-process",
        help="Process the video after downloading"
    )
):
    """
    Download a video from URL and optionally process it.

    Supports YouTube and many other video platforms via yt-dlp.
    """
    settings = get_settings()
    if output_dir:
        settings.videos_dir = output_dir
    settings.ensure_directories()

    downloader = VideoDownloader(str(settings.videos_dir))

    console.print(Panel(f"Downloading: [bold]{url}[/bold]"))

    import uuid
    job_id = str(uuid.uuid4())[:8]

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console
    ) as progress:
        task = progress.add_task("Downloading...", total=100)

        def update_progress(step, pct):
            if step == "downloading":
                progress.update(task, completed=pct, description=f"Downloading: {pct}%")
            elif step == "download_complete":
                progress.update(task, completed=100, description="Download complete")

        video_path, title = downloader.download(url, job_id, update_progress)

    console.print(f"[green]Downloaded: {title}[/green]")
    console.print(f"  Path: {video_path}")

    if process_video:
        console.print("\n[bold]Processing video...[/bold]")
        process(Path(video_path))


@app.command()
def list_transcripts(
    directory: Optional[Path] = typer.Argument(
        None, help="Directory containing transcripts"
    )
):
    """
    List available transcript files.
    """
    settings = get_settings()
    transcript_dir = directory or settings.transcripts_dir

    if not Path(transcript_dir).exists():
        console.print(f"[yellow]Transcript directory not found: {transcript_dir}[/yellow]")
        raise typer.Exit(1)

    transcripts = list(Path(transcript_dir).glob("*.json"))

    if not transcripts:
        console.print("[yellow]No transcript files found.[/yellow]")
        return

    table = Table(title="Available Transcripts")
    table.add_column("Filename", style="cyan")
    table.add_column("Size", style="green")
    table.add_column("Modified", style="dim")

    for t in sorted(transcripts):
        stat = t.stat()
        size = f"{stat.st_size / 1024:.1f} KB"
        from datetime import datetime
        modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
        table.add_row(t.name, size, modified)

    console.print(table)


@app.command()
def config():
    """
    Show current configuration settings.
    """
    settings = get_settings()

    table = Table(title="Configuration")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Data Directory", str(settings.data_dir))
    table.add_row("Agent Prompts", str(settings.agent_prompts_dir))
    table.add_row("Whisper Model", settings.whisper_model_size)
    table.add_row("Frame Interval", f"{settings.frame_extract_interval}s")
    table.add_row("Max Upload Size", f"{settings.max_upload_size_mb} MB")
    table.add_row("API Key Set", "Yes" if settings.openai_api_key else "No")

    console.print(table)


def main():
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
