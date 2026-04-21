"""Tech Spend Command Center CLI — unified executive summary across the FinOps pipeline."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import click

from .parsers.inputs import parse_ai, parse_cloud, parse_resilience, parse_saas, parse_watchdog
from .report.builder import build_report
from .report.renderers import render_html, render_json, render_markdown

EXIT_SUCCESS = 0
EXIT_USAGE_ERROR = 2
EXIT_FILE_NOT_FOUND = 3
EXIT_INTERNAL_ERROR = 5

VALID_FORMATS = ("markdown", "json", "html")


class InputFileError(Exception):
    pass


@click.group()
def cli() -> None:
    """Tech Spend Command Center — unified Cloud + AI + SaaS executive summary."""


@cli.command("report")
@click.option(
    "--cloud",
    "cloud_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=None,
    help="Path to FinOps Lite JSON output.",
)
@click.option(
    "--watchdog",
    "watchdog_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=None,
    help="Path to FinOps Watchdog JSON output.",
)
@click.option(
    "--resilience",
    "resilience_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=None,
    help="Path to Recovery Economics JSON or CSV output.",
)
@click.option(
    "--ai",
    "ai_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=None,
    help="Path to AI Cost Lens JSON output.",
)
@click.option(
    "--saas",
    "saas_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=None,
    help="Path to SaaS Cost Analyzer JSON output.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(VALID_FORMATS, case_sensitive=False),
    default="markdown",
    show_default=True,
    help="Output format: markdown, json, or html.",
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=None,
    help="Write report to this file instead of stdout.",
)
@click.pass_context
def report(
    ctx: click.Context,
    cloud_path: Optional[Path],
    watchdog_path: Optional[Path],
    resilience_path: Optional[Path],
    ai_path: Optional[Path],
    saas_path: Optional[Path],
    output_format: str,
    output_path: Optional[Path],
) -> None:
    """Produce a unified executive tech-spend report from pipeline tool outputs.

    All inputs are optional — report on whatever is provided. At least one
    input must be supplied.
    """
    paths = [cloud_path, watchdog_path, resilience_path, ai_path, saas_path]
    if not any(paths):
        click.echo(
            "Error: at least one input must be provided "
            "(--cloud, --watchdog, --resilience, --ai, or --saas).",
            err=True,
        )
        ctx.exit(EXIT_USAGE_ERROR)
        return

    try:
        cloud = _parse_input(cloud_path, parse_cloud, "cloud")
        watchdog = _parse_input(watchdog_path, parse_watchdog, "watchdog")
        resilience = _parse_input(resilience_path, parse_resilience, "resilience")
        ai = _parse_input(ai_path, parse_ai, "ai")
        saas = _parse_input(saas_path, parse_saas, "saas")
    except FileNotFoundError as exc:
        click.echo(f"Error: {exc}", err=True)
        ctx.exit(EXIT_FILE_NOT_FOUND)
        return
    except (ValueError, KeyError, TypeError) as exc:
        click.echo(f"Error parsing input: {exc}", err=True)
        ctx.exit(EXIT_INTERNAL_ERROR)
        return
    except Exception as exc:
        click.echo(f"Internal error: {exc}", err=True)
        ctx.exit(EXIT_INTERNAL_ERROR)
        return

    try:
        report_data = build_report(
            cloud=cloud,
            watchdog=watchdog,
            resilience=resilience,
            ai=ai,
            saas=saas,
        )

        fmt = output_format.lower()
        if fmt == "json":
            content = render_json(report_data)
        elif fmt == "html":
            content = render_html(report_data)
        else:
            content = render_markdown(report_data)
    except Exception as exc:
        click.echo(f"Internal error building report: {exc}", err=True)
        ctx.exit(EXIT_INTERNAL_ERROR)
        return

    if output_path is not None:
        try:
            output_path.write_text(content, encoding="utf-8")
        except OSError as exc:
            click.echo(f"Error writing output file: {exc}", err=True)
            ctx.exit(EXIT_INTERNAL_ERROR)
            return
    else:
        sys.stdout.write(content)


def _parse_input(path, parser_fn, label):
    """Return parsed data or None if path is None. Raise FileNotFoundError if path missing."""
    if path is None:
        return None
    if not path.exists():
        raise FileNotFoundError(f"File not found for --{label}: {path}")
    return parser_fn(path)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
