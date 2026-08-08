from __future__ import annotations

import hashlib
import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

from tech_spend_command_center.ccac11 import (
    EXPECTED_CROSS_SCOPE,
    SCOPES,
    VERSIONS,
    build_manifest,
    build_report,
    build_report_from_manifest,
    validate_complete_run,
)
from tech_spend_command_center.demo import run_demo_pipeline
from tech_spend_command_center.trusted import ANALYTICAL_PRODUCERS, TrustedReportError

RUN_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
PERIOD = {"start": "2026-07-01", "end": "2026-07-22", "timezone": "UTC"}
VALUES = {"finops-lite": 2194.0, "ai-cost-lens": 8.2825, "saas-cost-analyzer": 736.77}


def document(name: str) -> dict:
    evidence_id = f"evidence.{name}.demo"
    source_id = f"source.{name}.demo"
    metrics = []
    if name in SCOPES:
        metric_id, scope, channel = SCOPES[name]
        metrics.append(
            {
                "id": metric_id,
                "name": scope,
                "value": VALUES[name],
                "unknown_reason": None,
                "unit": "currency",
                "currency": "USD",
                "basis": "calculated" if scope != "cloud" else "observed",
                "additivity": "additive",
                "period": PERIOD,
                "dimensions": {},
                "formula": None if scope == "cloud" else "illustrative allocation",
                "input_metric_ids": [],
                "evidence_ids": [evidence_id],
                "quality_status": "valid",
                "accounting_boundary": {
                    "relationship": "canonical_scope_spend",
                    "scope": scope,
                    "canonical_owner": name,
                    "source_channel": channel,
                    "cost_basis": "net_cost",
                    "coverage": "complete",
                    "total_eligible": True,
                    "eligibility_reason": "Complete deterministic fixture.",
                    "currency_minor_unit": 0.01,
                    "allocation_of_metric_id": None,
                    "inclusion_rules": ["Declared channel only."],
                    "exclusion_rules": ["Other channels."],
                    "overlap": {
                        "disposition": "resolved",
                        "treatment": "Explicit channel.",
                    },
                    "cross_scope_treatments": EXPECTED_CROSS_SCOPE[name],
                    "component_treatments": {
                        "credits": "included",
                        "taxes": "included",
                        "adjustments": "included",
                        "shared_services": "included",
                    },
                },
            }
        )
    return {
        "contract": "ccac/1.1.0",
        "document_type": "tool_result",
        "producer": {"name": name, "version": VERSIONS[name]},
        "run_id": RUN_ID,
        "generated_at": "2026-08-04T12:00:00Z",
        "mode": "illustrative",
        "period": PERIOD,
        "inputs": [
            {
                "id": source_id,
                "source_type": "illustrative_fixture",
                "source_version": "1",
                "adapter_version": None,
                "content_sha256": "a" * 64,
                "access": "illustrative_fixture",
                "data_classification": "public_illustrative",
                "lossy_mapping": False,
                "mapping_notes": [],
            }
        ],
        "quality": {"status": "valid", "issues": []},
        "metrics": metrics,
        "findings": [],
        "opportunities": [],
        "evidence": [
            {
                "id": evidence_id,
                "kind": "other",
                "source_ids": [source_id],
                "description": "Demo evidence.",
                "locator": None,
                "observed_at": "2026-08-04T12:00:00Z",
                "content_sha256": None,
            }
        ],
        "extensions": {},
    }


@pytest.fixture
def paths(tmp_path: Path) -> dict[str, Path]:
    result = {}
    for name in ANALYTICAL_PRODUCERS:
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(document(name), indent=2) + "\n", encoding="utf-8")
        result[name] = path
    return result


def rewrite(path: Path, mutate) -> None:
    payload = json.loads(path.read_text())
    mutate(payload)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def preliminary(paths: dict[str, Path], directory: Path) -> Path:
    manifest_path = directory / "manifest.json"
    write_json(
        manifest_path,
        build_manifest(
            paths,
            manifest_path=manifest_path,
            started_at="2026-08-04T12:00:00Z",
            completed_at="2026-08-04T12:00:00Z",
        ),
    )
    return manifest_path


def complete_run(paths: dict[str, Path], directory: Path) -> Path:
    manifest_path = preliminary(paths, directory)
    report_path = directory / "report.json"
    write_json(
        report_path,
        build_report_from_manifest(
            manifest_path,
            generated_at="2026-08-04T12:00:00Z",
            report_id="report.tech-spend.trusted",
        ),
    )
    write_json(
        manifest_path,
        build_manifest(
            paths,
            manifest_path=manifest_path,
            started_at="2026-08-04T12:00:00Z",
            completed_at="2026-08-04T12:00:00Z",
            report_path=report_path,
        ),
    )
    return manifest_path


def test_exact_decimal_total_and_typed_reconciliation(paths):
    report = build_report(
        paths, generated_at="2026-08-04T12:00:00Z", manifest_sha256="a" * 64
    )
    total = next(
        item
        for item in report["metric_catalog"]
        if item["id"] == "metric.tech-spend.total"
    )
    assert total["value"] == 2939.0525
    assert total["input_metric_ids"] == [item[0] for item in SCOPES.values()]
    assert report["reconciliation"] == [
        {
            "id": "reconciliation.tech-spend",
            "reconciliation_type": "technology_spend_total",
            "assertion": "Canonical Cloud, direct-AI, and SaaS scopes sum exactly to Technology Spend.",
            "input_metric_ids": total["input_metric_ids"],
            "output_metric_id": "metric.tech-spend.total",
            "difference": 0.0,
            "tolerance": 0.01,
            "status": "passed",
        }
    ]


@pytest.mark.parametrize("producer", ["finops-watchdog", "recovery-economics"])
def test_diagnostic_producer_cannot_publish_canonical_scope(paths, producer):
    payload = document("finops-lite")["metrics"][0]
    rewrite(paths[producer], lambda item: item["metrics"].append(payload))
    with pytest.raises(TrustedReportError):
        build_report(
            paths, generated_at="2026-08-04T12:00:00Z", manifest_sha256="a" * 64
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("currency", "EUR"),
        ("unit", "count"),
        ("additivity", "non_additive"),
        ("quality_status", "invalid"),
    ],
)
def test_scope_compatibility_fails_closed(paths, field, value):
    rewrite(
        paths["ai-cost-lens"], lambda item: item["metrics"][0].__setitem__(field, value)
    )
    with pytest.raises(TrustedReportError):
        build_report(
            paths, generated_at="2026-08-04T12:00:00Z", manifest_sha256="a" * 64
        )


@pytest.mark.parametrize("value", [True, -1, float("nan"), float("inf")])
def test_invalid_financial_values_fail_closed(paths, value):
    rewrite(
        paths["ai-cost-lens"],
        lambda item: item["metrics"][0].__setitem__("value", value),
    )
    with pytest.raises(TrustedReportError):
        build_report(
            paths, generated_at="2026-08-04T12:00:00Z", manifest_sha256="a" * 64
        )


def test_mixed_contract_and_unsupported_version_fail(paths):
    rewrite(
        paths["finops-lite"], lambda item: item.__setitem__("contract", "ccac/1.0.0")
    )
    with pytest.raises(TrustedReportError):
        build_report(
            paths, generated_at="2026-08-04T12:00:00Z", manifest_sha256="a" * 64
        )
    rewrite(
        paths["finops-lite"],
        lambda item: (
            item.__setitem__("contract", "ccac/1.1.0"),
            item["producer"].__setitem__("version", "9.9.9"),
        ),
    )
    with pytest.raises(TrustedReportError):
        build_report(
            paths, generated_at="2026-08-04T12:00:00Z", manifest_sha256="a" * 64
        )


def test_manifest_includes_report_without_circular_hash(paths, tmp_path):
    preliminary = build_manifest(
        paths,
        manifest_path=tmp_path / "manifest.json",
        started_at="2026-08-04T12:00:00Z",
        completed_at="2026-08-04T12:00:00Z",
    )
    raw = (json.dumps(preliminary, indent=2) + "\n").encode()
    report = build_report(
        paths,
        generated_at="2026-08-04T12:00:00Z",
        manifest_sha256=hashlib.sha256(raw).hexdigest(),
    )
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    final = build_manifest(
        paths,
        manifest_path=tmp_path / "manifest.json",
        started_at="2026-08-04T12:00:00Z",
        completed_at="2026-08-04T12:00:00Z",
        report_path=report_path,
    )
    assert len(final["artifacts"]) == 6
    assert final["artifacts"][-1]["document_type"] == "trusted_report"
    assert (
        final["artifacts"][-1]["content_sha256"]
        == hashlib.sha256(report_path.read_bytes()).hexdigest()
    )


def test_duplicate_catalog_identity_fails(paths):
    metric = deepcopy(document("finops-lite")["metrics"][0])
    rewrite(paths["finops-watchdog"], lambda item: item["metrics"].append(metric))
    with pytest.raises(TrustedReportError):
        build_report(
            paths, generated_at="2026-08-04T12:00:00Z", manifest_sha256="a" * 64
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda item: item.__setitem__("quality", []),
        lambda item: item.__setitem__(
            "period", {"start": "2026-07-22", "end": "2026-07-01", "timezone": "UTC"}
        ),
        lambda item: item.__setitem__("generated_at", "not-a-timestamp"),
        lambda item: item["evidence"][0].__setitem__("source_ids", ["source.missing"]),
        lambda item: item["metrics"][0].__setitem__(
            "evidence_ids", [item["evidence"][0]["id"], item["evidence"][0]["id"]]
        ),
        lambda item: item.__setitem__("findings", [{}]),
        lambda item: item.__setitem__("opportunities", [{}]),
        lambda item: item.__setitem__("inputs", {}),
    ],
    ids=[
        "quality",
        "period",
        "timestamp",
        "evidence-lineage",
        "duplicate-reference",
        "finding",
        "opportunity",
        "inputs-array",
    ],
)
def test_full_released_validation_rejects_malformed_producer(paths, mutation):
    rewrite(paths["finops-lite"], mutation)
    with pytest.raises(TrustedReportError):
        build_report(
            paths, generated_at="2026-08-04T12:00:00Z", manifest_sha256="a" * 64
        )


def test_preliminary_manifest_hash_mismatch_fails(paths, tmp_path):
    manifest_path = preliminary(paths, tmp_path)
    rewrite(
        manifest_path,
        lambda item: item["artifacts"][0].__setitem__("content_sha256", "0" * 64),
    )
    with pytest.raises(TrustedReportError, match="hash mismatch"):
        build_report_from_manifest(
            manifest_path,
            generated_at="2026-08-04T12:00:00Z",
            report_id="report.tech-spend.trusted",
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda item: item["artifacts"][0].__setitem__(
            "relative_path", "../escape.json"
        ),
        lambda item: item["artifacts"][1].__setitem__(
            "relative_path", item["artifacts"][0]["relative_path"]
        ),
        lambda item: item["artifacts"].pop(),
        lambda item: item["artifacts"].append(deepcopy(item["artifacts"][0])),
        lambda item: item["artifacts"][0].__setitem__("contract_valid", False),
        lambda item: item.__setitem__("status", "partial"),
        lambda item: item.__setitem__("status", "failed"),
        lambda item: item.__setitem__(
            "errors", [{"code": "run.failed", "severity": "error", "message": "failed"}]
        ),
    ],
    ids=[
        "unsafe-path",
        "duplicate-path",
        "missing-producer",
        "duplicate-producer",
        "false-contract-valid",
        "partial",
        "failed",
        "errors",
    ],
)
def test_preliminary_manifest_integrity_fails_closed(paths, tmp_path, mutation):
    manifest_path = preliminary(paths, tmp_path)
    rewrite(manifest_path, mutation)
    with pytest.raises(TrustedReportError):
        build_report_from_manifest(
            manifest_path,
            generated_at="2026-08-04T12:00:00Z",
            report_id="report.tech-spend.trusted",
        )


def test_complete_run_rejects_tampered_report(paths, tmp_path):
    complete_run(paths, tmp_path)
    rewrite(
        tmp_path / "report.json",
        lambda item: next(
            metric
            for metric in item["metric_catalog"]
            if metric["id"] == "metric.tech-spend.total"
        ).__setitem__("value", 1),
    )
    with pytest.raises(TrustedReportError, match="complete run fails"):
        validate_complete_run(tmp_path)


def test_complete_run_rejects_report_manifest_metadata_mismatch(paths, tmp_path):
    manifest_path = complete_run(paths, tmp_path)
    rewrite(
        manifest_path,
        lambda item: item["artifacts"][-1]["producer"].__setitem__("version", "9.9.9"),
    )
    with pytest.raises(TrustedReportError, match="complete run fails"):
        validate_complete_run(tmp_path)


def test_complete_run_rejects_unexpected_json(paths, tmp_path):
    complete_run(paths, tmp_path)
    write_json(tmp_path / "unexpected.json", {})
    with pytest.raises(TrustedReportError, match="unexpected JSON"):
        validate_complete_run(tmp_path)


def test_complete_run_validates_exact_correspondence(paths, tmp_path):
    complete_run(paths, tmp_path)
    report, validated_paths = validate_complete_run(tmp_path)
    total = next(
        metric
        for metric in report["metric_catalog"]
        if metric["id"] == "metric.tech-spend.total"
    )
    assert total["value"] == 2939.0525
    assert set(validated_paths) == set(ANALYTICAL_PRODUCERS)


def test_atomic_demo_does_not_publish_contract_invalid_output(tmp_path):
    executable_names = {
        "finops-lite": "finops-lite",
        "finops-watchdog": "finops-watchdog",
        "recovery-economics": "recovery-economics",
        "ai-cost-lens": "ai-cost-lens",
        "saas-cost": "saas-cost-analyzer",
    }

    def runner(command):
        executable = Path(command[0]).name
        payload = document(executable_names[executable])
        if executable == "finops-watchdog":
            payload["quality"] = []
        output = Path(command[command.index("--output") + 1])
        write_json(output, payload)
        return subprocess.CompletedProcess(command, 0, "", "")

    target = tmp_path / "published"
    with pytest.raises(TrustedReportError, match="released CCAC 0.2.0 validation"):
        run_demo_pipeline(
            target,
            contract_version="1.1.0",
            resolver=lambda name: f"/bin/{name}",
            runner=runner,
        )
    assert not target.exists()
