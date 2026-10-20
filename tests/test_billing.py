"""Explicit partial reports preserve the complete pipeline's existing policy."""

import hashlib
from decimal import Decimal
from pathlib import Path

import pytest
from ccac import validate_document, validate_run_directory
from finops_lite.ccac_json import dumps_exact, loads_exact

from tech_spend_command_center.billing import run_billing_pipeline, validate_billing_run
from tech_spend_command_center.ccac11 import load_producers
from tech_spend_command_center.trusted import TrustedReportError

IDENTITY = dict(
    run_id="7e5f2340-60aa-46e6-a7dd-66ed33854d03", generated_at="2026-10-20T00:00:00Z"
)


@pytest.fixture
def bundle():
    source = Path(__file__).resolve().parents[1] / "examples/billing-current.csv"
    return run_billing_pipeline(
        dict(**IDENTITY, current=[dict(name=source.name, text=source.read_text())])
    )


def write(directory, bundle):
    for name, text in bundle["files"].items():
        (directory / name).write_text(text)


def test_partial_run_passes_released_ccac_without_filling_missing_producers(
    tmp_path, bundle
):
    write(tmp_path, bundle)
    report, manifest = validate_billing_run(tmp_path)
    assert validate_run_directory(tmp_path) == []
    assert report["status"] == manifest["status"] == "partial"
    assert len(report["omitted_producers"]) == 3
    assert {item["name"] for item in report["included_producers"]} == {
        "finops-lite",
        "finops-watchdog",
    }
    assert {name for name in bundle["files"]} == {
        "finops-lite.json",
        "finops-watchdog.json",
        "report.json",
        "source-manifest.json",
        "manifest.json",
    }
    metric = next(
        item
        for item in report["metric_catalog"]
        if item["id"] == "metric.tech-spend.scope.cloud"
    )
    assert metric["value"] == Decimal("1310.125")
    assert metric["accounting_boundary"]["total_eligible"] is False
    assert not any(
        item.get("metric_role") == "technology_spend_total"
        for item in report["metric_catalog"]
    )
    assert validate_document(report) == []


def test_presentation_keeps_exact_producer_values_and_references(bundle):
    view = bundle["presentation"]
    assert view["current"]["net"] == "1310.125"
    assert view["current"]["metric_ids"]["net"] == "metric.tech-spend.scope.cloud"
    assert view["comparison"] is None
    assert view["pipeline"]["watchdog"]["anomalies_detected"] == 0
    report = loads_exact(bundle["files"]["report.json"])
    producer = loads_exact(bundle["files"]["finops-lite.json"])
    for metric in producer["metrics"]:
        assert metric in report["metric_catalog"]
    for finding in producer["findings"]:
        assert finding in report["finding_catalog"]


@pytest.mark.parametrize("mutation", ["hash", "missing", "omitted"])
def test_hash_changes_missing_artifacts_and_omitted_scope_substitution_fail(
    tmp_path, bundle, mutation
):
    write(tmp_path, bundle)
    if mutation == "hash":
        (tmp_path / "finops-lite.json").write_text(
            bundle["files"]["finops-lite.json"] + " "
        )
    if mutation == "missing":
        (tmp_path / "finops-watchdog.json").unlink()
    if mutation == "omitted":
        (tmp_path / "ai-cost-lens.json").write_text(bundle["files"]["finops-lite.json"])
    with pytest.raises((TrustedReportError, OSError)):
        validate_billing_run(tmp_path)


def test_rehashed_report_must_still_match_producer_catalogs(tmp_path, bundle):
    write(tmp_path, bundle)
    report = loads_exact(bundle["files"]["report.json"])
    next(item for item in report["metric_catalog"] if item["id"].endswith(".charges"))[
        "value"
    ] += 1
    text = dumps_exact(report)
    (tmp_path / "report.json").write_text(text)
    manifest = loads_exact(bundle["files"]["manifest.json"])
    next(
        item for item in manifest["artifacts"] if item["relative_path"] == "report.json"
    )["content_sha256"] = hashlib.sha256(text.encode()).hexdigest()
    (tmp_path / "manifest.json").write_text(dumps_exact(manifest))
    with pytest.raises(TrustedReportError):
        validate_billing_run(tmp_path)


def test_default_complete_report_still_requires_all_five_producers(tmp_path, bundle):
    write(tmp_path, bundle)
    paths = {
        name: tmp_path / (name + ".json") for name in ["finops-lite", "finops-watchdog"]
    }
    with pytest.raises(TrustedReportError):
        load_producers(paths)
