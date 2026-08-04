"""Tech Spend Command Center CLI — unified executive summary across the FinOps pipeline."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import click

from .demo import DEMO_GENERATED_AT, DEMO_RUN_ID, run_demo_pipeline
from .manifest import build_manifest
from .parsers.inputs import (
    parse_ai,
    parse_cloud,
    parse_resilience,
    parse_saas,
    parse_watchdog,
)
from .report.builder import build_report
from .report.renderers import render_html, render_json, render_markdown
from .trusted import TrustedReportError, build_trusted_report

EXIT_SUCCESS = 0
EXIT_USAGE_ERROR = 2
EXIT_FILE_NOT_FOUND = 3
EXIT_INTERNAL_ERROR = 5

VALID_FORMATS = ("markdown", "json", "html")


class InputFileError(Exception):
    pass


@click.group()
@click.version_option(package_name="tech-spend-command-center")
def cli() -> None:
    """Tech Spend Command Center — unified Cloud + AI + SaaS executive summary."""


@cli.command("demo-pipeline")
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path, file_okay=False),
    required=True,
    help="New directory to publish only after the full demo validates.",
)
@click.option("--run-id", default=DEMO_RUN_ID, show_default=True)
@click.option("--generated-at", default=DEMO_GENERATED_AT, show_default=True)
@click.pass_context
def demo_pipeline(
    ctx: click.Context, output_dir: Path, run_id: str, generated_at: str
) -> None:
    """Run all five installed illustrative producers and build report.json atomically."""
    try:
        report = run_demo_pipeline(output_dir, run_id=run_id, generated_at=generated_at)
        opportunity_count = len(report["opportunity_catalog"])
        click.echo(f"Demo pipeline complete: {output_dir.resolve()}")
        click.echo(
            f"Validated {len(report['included_producers'])} producers, {len(report['metric_catalog'])} metrics, {len(report['finding_catalog'])} findings, and {opportunity_count} {'opportunity' if opportunity_count == 1 else 'opportunities'}."
        )
        click.echo(f"Trusted report: {(output_dir.resolve() / 'report.json')}")
    except TrustedReportError as exc:
        click.echo(f"Demo pipeline failed: {exc}", err=True)
        ctx.exit(4)


@cli.command("manifest")
@click.option(
    "--finops-lite",
    "finops_lite",
    type=click.Path(path_type=Path, dir_okay=False),
    required=True,
)
@click.option(
    "--finops-watchdog",
    "finops_watchdog",
    type=click.Path(path_type=Path, dir_okay=False),
    required=True,
)
@click.option(
    "--recovery-economics",
    "recovery_economics",
    type=click.Path(path_type=Path, dir_okay=False),
    required=True,
)
@click.option(
    "--ai-cost-lens",
    "ai_cost_lens",
    type=click.Path(path_type=Path, dir_okay=False),
    required=True,
)
@click.option(
    "--saas-cost-analyzer",
    "saas_cost_analyzer",
    type=click.Path(path_type=Path, dir_okay=False),
    required=True,
)
@click.option("--started-at", required=True, help="RFC3339 pipeline start timestamp.")
@click.option(
    "--completed-at", required=True, help="RFC3339 pipeline completion timestamp."
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(path_type=Path, dir_okay=False),
    required=True,
)
@click.pass_context
def manifest(
    ctx: click.Context,
    finops_lite: Path,
    finops_watchdog: Path,
    recovery_economics: Path,
    ai_cost_lens: Path,
    saas_cost_analyzer: Path,
    started_at: str,
    completed_at: str,
    output_path: Path,
) -> None:
    """Hash five same-run tool results and write a pipeline manifest."""
    try:
        paths = {
            "finops-lite": finops_lite,
            "finops-watchdog": finops_watchdog,
            "recovery-economics": recovery_economics,
            "ai-cost-lens": ai_cost_lens,
            "saas-cost-analyzer": saas_cost_analyzer,
        }
        content = (
            json.dumps(
                build_manifest(
                    paths,
                    manifest_path=output_path,
                    started_at=started_at,
                    completed_at=completed_at,
                ),
                indent=2,
            )
            + "\n"
        )
        output_path.write_text(content, encoding="utf-8")
    except TrustedReportError as exc:
        click.echo(f"Manifest validation failed: {exc}", err=True)
        ctx.exit(4)
    except OSError as exc:
        click.echo(f"File error: {exc}", err=True)
        ctx.exit(EXIT_FILE_NOT_FOUND)


@cli.command("trusted-report")
@click.option(
    "--manifest",
    "manifest_path",
    type=click.Path(path_type=Path, dir_okay=False),
    required=True,
    help="CCAC 1.0 pipeline manifest whose paths are resolved relative to the manifest.",
)
@click.option("--generated-at", default=None, help="Optional RFC3339 report timestamp.")
@click.option("--report-id", default="report.tech-spend.trusted", show_default=True)
@click.option(
    "--output",
    "output_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=None,
    help="Write trusted_report JSON; default is stdout.",
)
@click.pass_context
def trusted_report(
    ctx: click.Context,
    manifest_path: Path,
    generated_at: str | None,
    report_id: str,
    output_path: Path | None,
) -> None:
    """Validate five canonical producer artifacts and emit one trusted_report."""
    try:
        content = (
            json.dumps(
                build_trusted_report(
                    manifest_path, generated_at=generated_at, report_id=report_id
                ),
                indent=2,
            )
            + "\n"
        )
        if output_path is None:
            click.echo(content, nl=False)
        else:
            output_path.write_text(content, encoding="utf-8")
    except TrustedReportError as exc:
        click.echo(f"Trust validation failed: {exc}", err=True)
        ctx.exit(4)
    except OSError as exc:
        click.echo(f"File error: {exc}", err=True)
        ctx.exit(EXIT_FILE_NOT_FOUND)


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
