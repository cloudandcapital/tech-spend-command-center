"""Atomic one-command illustrative pipeline orchestration."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Callable, Sequence

from .manifest import build_manifest
from .trusted import TrustedReportError, build_trusted_report

DEMO_RUN_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
DEMO_GENERATED_AT = "2026-08-04T12:00:00Z"
EXECUTABLES = (
    "finops-lite",
    "finops-watchdog",
    "recovery-economics",
    "ai-cost-lens",
    "saas-cost",
)


def resolve_executable(name: str) -> str | None:
    """Find sibling console scripts even when the virtual environment is not activated."""
    # Do not resolve the interpreter symlink: its parent is the venv's script directory.
    scripts = Path(sys.executable).absolute().parent
    for candidate in (scripts / name, scripts / f"{name}.exe"):
        if candidate.is_file():
            return str(candidate)
    return shutil.which(name)


def _default_run(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args), text=True, capture_output=True, check=False, timeout=60
    )


def run_demo_pipeline(
    output_dir: Path,
    *,
    run_id: str = DEMO_RUN_ID,
    generated_at: str = DEMO_GENERATED_AT,
    contract_version: str = "1.0.0",
    resolver: Callable[[str], str | None] = resolve_executable,
    runner: Callable[[Sequence[str]], subprocess.CompletedProcess[str]] = _default_run,
) -> dict:
    """Run five installed producers and publish artifacts only after validation."""
    if contract_version not in {"1.0.0", "1.1.0"}:
        raise TrustedReportError(
            f"unsupported CCAC contract version: {contract_version}"
        )
    target = output_dir.resolve()
    if target.exists():
        raise TrustedReportError(
            f"output directory already exists: {target}; choose a new path"
        )
    try:
        run_id = str(uuid.UUID(run_id))
    except (ValueError, TypeError) as exc:
        raise TrustedReportError("run_id must be a UUID") from exc
    resolved = {name: resolver(name) for name in EXECUTABLES}
    missing = [name for name, path in resolved.items() if path is None]
    if missing:
        raise TrustedReportError(
            f"missing installed producer commands: {', '.join(missing)}"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{target.name}.staging-", dir=target.parent
    ) as staging_raw:
        staging = Path(staging_raw)
        paths = {
            "finops-lite": staging / "finops-lite.json",
            "finops-watchdog": staging / "finops-watchdog.json",
            "recovery-economics": staging / "recovery-economics.json",
            "ai-cost-lens": staging / "ai-cost-lens.json",
            "saas-cost-analyzer": staging / "saas-cost-analyzer.json",
        }
        commands = [
            [
                resolved["finops-lite"],
                "ccac",
                "--demo",
                "--run-id",
                run_id,
                "--generated-at",
                generated_at,
                "--output",
                str(paths["finops-lite"]),
            ],
            [
                resolved["finops-watchdog"],
                "ccac",
                "--input",
                str(paths["finops-lite"]),
                "--generated-at",
                generated_at,
                "--output",
                str(paths["finops-watchdog"]),
            ],
            [
                resolved["recovery-economics"],
                "ccac",
                "--demo",
                "--run-id",
                run_id,
                "--generated-at",
                generated_at,
                "--output",
                str(paths["recovery-economics"]),
            ],
            [
                resolved["ai-cost-lens"],
                "ccac",
                "--demo",
                "--run-id",
                run_id,
                "--generated-at",
                generated_at,
                "--output",
                str(paths["ai-cost-lens"]),
            ],
            [
                resolved["saas-cost"],
                "ccac",
                "--demo",
                "--run-id",
                run_id,
                "--generated-at",
                generated_at,
                "--output",
                str(paths["saas-cost-analyzer"]),
            ],
        ]
        if contract_version == "1.1.0":
            for command in commands:
                command[2:2] = ["--contract-version", "1.1.0"]
            recovery = commands[2]
            recovery[2:2] = [
                "--period-start",
                "2026-07-01",
                "--period-end",
                "2026-07-22",
            ]
        for command in commands:
            try:
                result = runner([str(item) for item in command])
            except subprocess.TimeoutExpired as exc:
                raise TrustedReportError(
                    f"{Path(str(command[0])).name} exceeded the 60-second demo timeout"
                ) from exc
            except OSError as exc:
                raise TrustedReportError(
                    f"unable to execute {Path(str(command[0])).name}: {exc}"
                ) from exc
            if result.returncode != 0:
                name = Path(str(command[0])).name
                detail = (
                    result.stderr or result.stdout or "no diagnostic output"
                ).strip()
                raise TrustedReportError(
                    f"{name} failed with exit {result.returncode}: {detail}"
                )
        manifest_path = staging / "manifest.json"
        manifest = build_manifest(
            paths,
            manifest_path=manifest_path,
            started_at=generated_at,
            completed_at=generated_at,
            contract_version=contract_version,
        )
        manifest_path.write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        report_path = staging / "report.json"
        if contract_version == "1.1.0":
            from .ccac11 import build_manifest as build_manifest_1_1
            from .ccac11 import build_report_from_manifest, validate_complete_run

            report = build_report_from_manifest(
                manifest_path,
                generated_at=generated_at,
                report_id="report.tech-spend.trusted",
            )
        else:
            report = build_trusted_report(manifest_path, generated_at=generated_at)
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        if contract_version == "1.1.0":
            manifest = build_manifest_1_1(
                paths,
                manifest_path=manifest_path,
                started_at=generated_at,
                completed_at=generated_at,
                report_path=report_path,
            )
            manifest_path.write_text(
                json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
            )
            validate_complete_run(staging)
        staging.rename(target)
    return report
