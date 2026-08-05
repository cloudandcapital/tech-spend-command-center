from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from tech_spend_command_center.cli import cli
from tech_spend_command_center.manifest import build_manifest
from tech_spend_command_center.summary import summarize_run, validate_run_directory
from tech_spend_command_center.trusted import TrustedReportError, build_trusted_report
from tests.test_trusted_report import (
    ANALYTICAL_PRODUCERS,
    NOW,
    _finding,
    _opportunity,
    _write_run,
)


def _complete_run(tmp_path: Path, mutate=None) -> Path:
    manifest_path = _write_run(tmp_path, mutate)
    report = build_trusted_report(manifest_path, generated_at=NOW)
    (tmp_path / "report.json").write_text(json.dumps(report), encoding="utf-8")
    return tmp_path


def _rewrite_manifest_and_report(run: Path) -> None:
    paths = {name: run / f"{name}.json" for name in ANALYTICAL_PRODUCERS}
    manifest_path = run / "manifest.json"
    manifest = build_manifest(
        paths, manifest_path=manifest_path, started_at=NOW, completed_at=NOW
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    report = build_trusted_report(manifest_path, generated_at=NOW)
    (run / "report.json").write_text(json.dumps(report), encoding="utf-8")


def _illustrative_run(tmp_path: Path) -> Path:
    def mutate(producer, value):
        if producer == "finops-lite":
            value["findings"] = [
                _finding("finding.cloud.review", "Review canonical evidence.")
            ]
        if producer == "saas-cost-analyzer":
            value["opportunities"] = [
                _opportunity("opportunity.saas.review", value["producer"])
            ]

    return _complete_run(tmp_path, mutate)


def test_summary_is_exact_deterministic_plain_text(tmp_path: Path):
    run = _illustrative_run(tmp_path)
    first = summarize_run(run)
    second = summarize_run(run)
    assert first == second
    assert first.startswith("Cloud & Capital Trusted Report\nMode: ILLUSTRATIVE\n")
    assert (
        "ILLUSTRATIVE DATA — NO CUSTOMER SYSTEMS OR LIVE CLOUD ACCOUNTS CONNECTED"
        in first
    )
    assert "Included producers: 5" in first
    assert "Cataloged metrics: 5" in first
    assert "Displayed findings: 1" in first
    assert "Cataloged opportunities: 1" in first
    assert "USD 0–100 (annual)" in first
    assert "not realized savings; not verified savings" in first
    assert "No total technology-spend figure is created." in first
    assert "Cloud Cost Guard is not connected." in first
    assert "\x1b" not in first


def test_cli_writes_plain_summary_to_stdout_without_files(tmp_path: Path):
    run = _illustrative_run(tmp_path / "run")
    before = {path: path.read_bytes() for path in run.rglob("*") if path.is_file()}
    result = CliRunner().invoke(cli, ["summarize", str(run)], color=True)
    after = {path: path.read_bytes() for path in run.rglob("*") if path.is_file()}
    assert result.exit_code == 0
    assert result.output == summarize_run(run)
    assert "\x1b" not in result.output
    assert before == after


@pytest.mark.parametrize(
    "case, message",
    [
        ("missing-directory", "run directory not found"),
        ("file", "run path must be a directory"),
        ("missing-manifest", "missing manifest.json"),
        ("missing-report", "missing report.json"),
        ("missing-producer", "file not found"),
        ("extra-json", "artifact set is inconsistent"),
    ],
)
def test_incomplete_or_non_directory_inputs_fail_closed(tmp_path: Path, case, message):
    if case == "missing-directory":
        target = tmp_path / "absent"
    elif case == "file":
        target = tmp_path / "report.json"
        target.write_text("{}", encoding="utf-8")
    else:
        target = _complete_run(tmp_path / "run")
        if case == "missing-manifest":
            (target / "manifest.json").unlink()
        elif case == "missing-report":
            (target / "report.json").unlink()
        elif case == "missing-producer":
            (target / "finops-watchdog.json").unlink()
        else:
            (target / "duplicate.json").write_text(
                (target / "finops-lite.json").read_text(), encoding="utf-8"
            )
    with pytest.raises(TrustedReportError, match=message):
        validate_run_directory(target)


def test_altered_artifact_and_incorrect_manifest_hash_fail_closed(tmp_path: Path):
    run = _complete_run(tmp_path / "bytes")
    with (run / "finops-watchdog.json").open("a", encoding="utf-8") as stream:
        stream.write(" ")
    with pytest.raises(TrustedReportError, match="artifact hash mismatch"):
        validate_run_directory(run)

    run = _complete_run(tmp_path / "hash")
    manifest_path = run / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["artifacts"][0]["content_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(TrustedReportError, match="artifact hash mismatch"):
        validate_run_directory(run)


@pytest.mark.parametrize(
    "field,value",
    [
        ("run_id", "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
        ("mode", "real"),
        ("contract", "ccac/9.9.9"),
        ("document_type", "other"),
    ],
)
def test_report_must_correspond_exactly_to_validated_run(tmp_path: Path, field, value):
    run = _complete_run(tmp_path)
    report_path = run / "report.json"
    report = json.loads(report_path.read_text())
    report[field] = value
    report_path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(TrustedReportError, match="does not correspond exactly"):
        validate_run_directory(run)


def test_manifest_duplicate_producer_and_unsupported_version_fail_closed(
    tmp_path: Path,
):
    run = _complete_run(tmp_path / "duplicate")
    manifest_path = run / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["artifacts"].append(dict(manifest["artifacts"][0]))
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(TrustedReportError, match="duplicate manifest artifact"):
        validate_run_directory(run)

    run = _complete_run(tmp_path / "version")
    producer_path = run / "finops-watchdog.json"
    producer = json.loads(producer_path.read_text())
    producer["producer"]["version"] = "0.3.0"
    producer_path.write_text(json.dumps(producer), encoding="utf-8")
    manifest_path = run / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    row = next(
        item
        for item in manifest["artifacts"]
        if item["producer"]["name"] == "finops-watchdog"
    )
    row["producer"]["version"] = "0.3.0"
    row["content_sha256"] = hashlib.sha256(producer_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(TrustedReportError, match="unsupported"):
        validate_run_directory(run)


def test_missing_display_reference_and_broken_report_references_fail_closed(
    tmp_path: Path,
):
    run = _complete_run(tmp_path)
    report_path = run / "report.json"
    report = json.loads(report_path.read_text())
    report["display"]["headline_metric_ids"].append("metric.missing")
    report_path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(TrustedReportError, match="does not correspond exactly"):
        validate_run_directory(run)


@pytest.mark.parametrize("bad_value", ["12", True, float("nan"), float("inf")])
def test_invalid_financial_values_remain_controlled_trust_errors(
    tmp_path: Path, bad_value
):
    def mutate(producer, value):
        if producer == "finops-lite":
            value["metrics"][0]["value"] = bad_value

    with pytest.raises(TrustedReportError, match="non-finite or non-numeric"):
        _complete_run(tmp_path, mutate)


def test_unknown_value_requires_reason_and_is_preserved(tmp_path: Path):
    def valid_unknown(producer, value):
        if producer == "ai-cost-lens":
            metric = value["metrics"][0]
            metric["value"] = None
            metric["basis"] = "unknown"
            metric["unknown_reason"] = "Price evidence unavailable"

    run = _complete_run(tmp_path / "valid", valid_unknown)
    assert "unknown — Price evidence unavailable" in summarize_run(run)

    def invalid_unknown(producer, value):
        if producer == "ai-cost-lens":
            metric = value["metrics"][0]
            metric["value"] = None
            metric["basis"] = "unknown"
            metric["unknown_reason"] = None

    with pytest.raises(TrustedReportError, match="unexplained unknown"):
        _complete_run(tmp_path / "invalid", invalid_unknown)


def test_valid_real_mode_run_is_summarized_without_illustrative_banner(tmp_path: Path):
    def real_mode(_producer, value):
        value["mode"] = "real"
        for source in value["inputs"]:
            source["access"] = "local_read_only"
            source["data_classification"] = "customer_confidential"

    rendered = summarize_run(_complete_run(tmp_path, real_mode))
    assert "Mode: REAL" in rendered
    assert "ILLUSTRATIVE DATA" not in rendered


@pytest.mark.parametrize(
    "field", ["title", "description", "finding_type", "status", "severity"]
)
def test_rendered_strings_reject_controls(tmp_path: Path, field):
    def injection(producer, value):
        if producer == "finops-lite":
            finding = _finding("finding.cloud.review", "Safe context")
            finding[field] = "Review\x1b[2Jterminal"
            value["findings"] = [finding]

    run = _complete_run(tmp_path, injection)
    with pytest.raises(TrustedReportError, match="terminal-control"):
        summarize_run(run)


def test_rendered_strings_bound_long_text(tmp_path: Path):
    def long_text(producer, value):
        if producer == "finops-lite":
            finding = _finding("finding.cloud.review", "x" * 10_000)
            value["findings"] = [finding]

    rendered = summarize_run(_complete_run(tmp_path / "long", long_text))
    assert "x" * 240 not in rendered
    assert "x" * 239 + "…" in rendered


def test_cli_returns_controlled_nonzero_error(tmp_path: Path):
    result = CliRunner().invoke(cli, ["summarize", str(tmp_path / "missing")])
    assert result.exit_code == 4
    assert result.output.startswith(
        "Summary validation failed: run directory not found"
    )
    assert "Traceback" not in result.output
