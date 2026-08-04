from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tech_spend_command_center.demo import run_demo_pipeline
from tech_spend_command_center.manifest import build_manifest
from tech_spend_command_center.trusted import (
    ANALYTICAL_PRODUCERS,
    TrustedReportError,
    build_trusted_report,
)

RUN_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
NOW = "2026-08-04T12:00:00Z"


def _metric(
    mid: str,
    value: float,
    *,
    additivity: str = "additive",
    evidence_id: str = "evidence.finops-lite.test",
) -> dict:
    return {
        "id": mid,
        "name": mid,
        "value": value,
        "unknown_reason": None,
        "unit": "currency",
        "currency": "USD",
        "basis": "observed",
        "additivity": additivity,
        "period": {"start": "2026-07-01", "end": "2026-08-01", "timezone": "UTC"},
        "dimensions": {"scope": "test"},
        "formula": None,
        "input_metric_ids": [],
        "evidence_ids": [evidence_id],
        "quality_status": "valid",
    }


def _result(producer: str) -> dict:
    source_id = f"source.{producer}.test"
    evidence_id = f"evidence.{producer}.test"
    metrics = []
    if producer == "finops-lite":
        metrics = [
            _metric("metric.cloud.total", 100, evidence_id=evidence_id),
            _metric("metric.cloud.service.compute.cost", 60, evidence_id=evidence_id),
            _metric("metric.cloud.service.storage.cost", 40, evidence_id=evidence_id),
        ]
    elif producer == "ai-cost-lens":
        metrics = [
            _metric(
                "metric.ai.total-cost",
                20,
                additivity="non_additive",
                evidence_id=evidence_id,
            )
        ]
    elif producer == "saas-cost-analyzer":
        metrics = [_metric("metric.saas.crm.invoice-cost", 30, evidence_id=evidence_id)]
    return {
        "contract": "ccac/1.0.0",
        "document_type": "tool_result",
        "producer": {"name": producer, "version": "0.2.0"},
        "run_id": RUN_ID,
        "generated_at": NOW,
        "mode": "illustrative",
        "period": {"start": "2026-07-01", "end": "2026-08-01", "timezone": "UTC"},
        "inputs": [
            {
                "id": source_id,
                "source_type": "illustrative_fixture",
                "source_version": "1",
                "content_sha256": "a" * 64,
                "access": "illustrative_fixture",
                "data_classification": "public_illustrative",
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
                "description": "Illustrative test evidence.",
            }
        ],
        "extensions": {},
    }


def _opportunity(
    opportunity_id: str,
    producer: dict,
    *,
    group_id: str = "overlap.test",
    disposition: str = "none_known",
    status: str = "identified",
) -> dict:
    return {
        "id": opportunity_id,
        "producer": producer,
        "opportunity_type": "saas_reclaim",
        "title": "Review",
        "scope": {"application": "test"},
        "estimate": {
            "basis": "estimated",
            "period": "annual",
            "low": 0,
            "expected": 100,
            "high": 100,
            "currency": "USD",
            "formula": "reviewable seats * price",
        },
        "confidence": "low",
        "evidence_ids": ["evidence.saas-cost-analyzer.test"],
        "related_finding_ids": [],
        "related_opportunity_ids": [],
        "overlap": {
            "disposition": disposition,
            "group_id": group_id,
            "reason": "Explicit test overlap lineage.",
        },
        "review": {
            "required": True,
            "approval_required": True,
            "rollback_plan_required": True,
            "verification_required": True,
            "non_mutating_review_steps": ["Inspect the contract."],
        },
        "status": status,
    }


def _write_run(tmp_path: Path, mutate=None) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    paths = {}
    for producer in ANALYTICAL_PRODUCERS:
        value = _result(producer)
        if mutate:
            mutate(producer, value)
        path = tmp_path / f"{producer}.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        paths[producer] = path
    manifest_path = tmp_path / "manifest.json"
    manifest = build_manifest(
        paths, manifest_path=manifest_path, started_at=NOW, completed_at=NOW
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def test_complete_report_has_traceable_catalogs_and_no_invented_total(tmp_path: Path):
    report = build_trusted_report(_write_run(tmp_path), generated_at=NOW)
    assert report["status"] == "complete"
    assert len(report["included_producers"]) == 5
    assert len(report["producer_quality"]) == 5
    assert all(
        item["quality"]["status"] == "valid" for item in report["producer_quality"]
    )
    assert report["reconciliation"][0]["difference"] == 0
    assert "metric.cloud.total" in report["display"]["headline_metric_ids"]
    assert not any(
        metric["id"] == "metric.technology.total" for metric in report["metric_catalog"]
    )
    assert any(
        "different periods" in disclosure
        for disclosure in report["display"]["disclosures"]
    )


def test_partial_producer_quality_issues_are_preserved(tmp_path: Path):
    def mutate(producer, value):
        if producer == "saas-cost-analyzer":
            value["quality"] = {
                "status": "partial",
                "issues": [
                    {
                        "code": "quality.saas.activity",
                        "severity": "warning",
                        "message": "Activity evidence is stale.",
                    }
                ],
            }

    report = build_trusted_report(_write_run(tmp_path, mutate), generated_at=NOW)
    assert report["status"] == "complete"
    summary = next(
        item
        for item in report["producer_quality"]
        if item["producer"]["name"] == "saas-cost-analyzer"
    )
    assert summary["quality"]["status"] == "partial"
    assert summary["quality"]["issues"][0]["code"] == "quality.saas.activity"
    assert any(
        "producer results are partial" in disclosure
        for disclosure in report["display"]["disclosures"]
    )


def test_hash_tampering_fails_closed(tmp_path: Path):
    manifest_path = _write_run(tmp_path)
    target = tmp_path / "ai-cost-lens.json"
    value = json.loads(target.read_text())
    value["metrics"][0]["value"] = 999
    target.write_text(json.dumps(value))
    with pytest.raises(TrustedReportError, match="hash mismatch"):
        build_trusted_report(manifest_path)


def test_manifest_rejects_mixed_run_ids(tmp_path: Path):
    def mutate(producer, value):
        if producer == "recovery-economics":
            value["run_id"] = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

    with pytest.raises(TrustedReportError, match="run_ids do not match"):
        _write_run(tmp_path, mutate)


def test_manifest_rejects_mixed_modes(tmp_path: Path):
    def mutate(producer, value):
        if producer == "recovery-economics":
            value["mode"] = "real"

    with pytest.raises(TrustedReportError, match="modes do not match"):
        _write_run(tmp_path, mutate)


def test_verified_tool_metric_is_rejected(tmp_path: Path):
    def mutate(producer, value):
        if producer == "ai-cost-lens":
            value["metrics"][0]["basis"] = "verified"

    with pytest.raises(TrustedReportError, match="calls a tool-result metric verified"):
        build_trusted_report(_write_run(tmp_path, mutate))


def test_cross_producer_duplicate_metric_is_rejected(tmp_path: Path):
    def mutate(producer, value):
        if producer == "recovery-economics":
            value["metrics"] = [
                _metric(
                    "metric.ai.total-cost",
                    1,
                    evidence_id="evidence.recovery-economics.test",
                )
            ]

    with pytest.raises(TrustedReportError, match="cross-producer duplicate metric"):
        build_trusted_report(_write_run(tmp_path, mutate))


def test_potential_overlap_is_cataloged_but_excluded(tmp_path: Path):
    def mutate(producer, value):
        if producer != "saas-cost-analyzer":
            return
        value["opportunities"] = [
            {
                "id": "opportunity.saas.test",
                "producer": value["producer"],
                "opportunity_type": "saas_reclaim",
                "title": "Review",
                "scope": {"application": "test"},
                "estimate": {
                    "basis": "estimated",
                    "period": "annual",
                    "low": 0,
                    "expected": 100,
                    "high": 100,
                    "currency": "USD",
                    "formula": "reviewable seats * price",
                },
                "confidence": "low",
                "evidence_ids": ["evidence.saas-cost-analyzer.test"],
                "related_finding_ids": [],
                "related_opportunity_ids": [],
                "overlap": {
                    "disposition": "potential",
                    "group_id": "overlap.test",
                    "reason": "unresolved",
                },
                "review": {
                    "required": True,
                    "approval_required": True,
                    "rollback_plan_required": True,
                    "verification_required": True,
                    "non_mutating_review_steps": ["Inspect the contract."],
                },
                "status": "identified",
            }
        ]

    report = build_trusted_report(_write_run(tmp_path, mutate))
    aggregate = report["opportunity_aggregates"][0]
    assert aggregate["expected"] == 0
    assert aggregate["opportunity_ids"] == []
    assert aggregate["excluded_opportunity_ids"] == ["opportunity.saas.test"]


def test_duplicate_overlap_group_uses_documented_deterministic_precedence(
    tmp_path: Path,
):
    def mutate(producer, value):
        if producer == "saas-cost-analyzer":
            value["opportunities"] = [
                _opportunity("opportunity.saas.z", value["producer"]),
                _opportunity("opportunity.saas.a", value["producer"]),
            ]

    report = build_trusted_report(_write_run(tmp_path, mutate))
    aggregate = report["opportunity_aggregates"][0]
    assert aggregate["opportunity_ids"] == ["opportunity.saas.a"]
    assert aggregate["excluded_opportunity_ids"] == ["opportunity.saas.z"]
    assert aggregate["expected"] == 100
    assert "lexicographically first" in aggregate["inclusion_rule"]


def test_mutating_public_review_step_is_rejected(tmp_path: Path):
    def mutate(producer, value):
        if producer != "saas-cost-analyzer":
            return
        value["opportunities"] = [
            {
                "id": "opportunity.saas.test",
                "producer": value["producer"],
                "opportunity_type": "saas_reclaim",
                "title": "Review",
                "scope": {"application": "test"},
                "estimate": {
                    "basis": "estimated",
                    "period": "annual",
                    "low": 0,
                    "expected": 1,
                    "high": 1,
                    "currency": "USD",
                    "formula": "reviewable seats * price",
                },
                "confidence": "low",
                "review": {
                    "required": True,
                    "approval_required": True,
                    "rollback_plan_required": True,
                    "verification_required": True,
                    "non_mutating_review_steps": ["Delete the license."],
                },
                "evidence_ids": ["evidence.saas-cost-analyzer.test"],
                "related_finding_ids": [],
                "related_opportunity_ids": [],
                "overlap": {
                    "disposition": "none_known",
                    "group_id": "overlap.saas.test",
                    "reason": "No known overlap.",
                },
                "status": "identified",
            }
        ]

    with pytest.raises(TrustedReportError, match="mutating public review step"):
        build_trusted_report(_write_run(tmp_path, mutate))


def test_manifest_requires_exactly_one_of_all_five_producers(tmp_path: Path):
    manifest_path = _write_run(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    manifest["artifacts"] = manifest["artifacts"][:-1]
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(TrustedReportError, match="exactly one produced artifact"):
        build_trusted_report(manifest_path)

    manifest_path = _write_run(tmp_path / "duplicate")
    manifest = json.loads(manifest_path.read_text())
    manifest["artifacts"].append(dict(manifest["artifacts"][0]))
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(TrustedReportError, match="duplicate manifest artifact"):
        build_trusted_report(manifest_path)


def test_wrong_identity_and_unsupported_version_fail_closed(tmp_path: Path):
    def wrong_identity(producer, value):
        if producer == "finops-watchdog":
            value["producer"]["name"] = "finops-lite"

    with pytest.raises(TrustedReportError, match="canonical tool_result"):
        _write_run(tmp_path / "identity", wrong_identity)

    def unsupported(producer, value):
        if producer == "recovery-economics":
            value["producer"]["version"] = "0.3.0"

    with pytest.raises(TrustedReportError, match="not supported"):
        _write_run(tmp_path / "version", unsupported)


def test_currency_and_cloud_period_mismatches_fail_closed(tmp_path: Path):
    def mixed_currency(producer, value):
        if producer == "recovery-economics":
            value["metrics"] = [
                {
                    **_metric(
                        "metric.recovery.test",
                        1,
                        evidence_id="evidence.recovery-economics.test",
                    ),
                    "currency": "EUR",
                }
            ]

    with pytest.raises(TrustedReportError, match="incompatible currencies"):
        build_trusted_report(_write_run(tmp_path / "currency", mixed_currency))

    def mismatched_period(producer, value):
        if producer == "finops-lite":
            value["metrics"][1]["period"]["start"] = "2026-06-01"

    with pytest.raises(TrustedReportError, match="service periods"):
        build_trusted_report(_write_run(tmp_path / "period", mismatched_period))


def test_broken_source_and_metric_lineage_fail_closed(tmp_path: Path):
    def broken_source(producer, value):
        if producer == "ai-cost-lens":
            value["evidence"][0]["source_ids"] = ["source.missing"]

    with pytest.raises(TrustedReportError, match="unresolved source references"):
        _write_run(tmp_path / "source", broken_source)

    def broken_metric(producer, value):
        if producer == "ai-cost-lens":
            value["metrics"][0]["input_metric_ids"] = ["metric.missing"]

    with pytest.raises(TrustedReportError, match="unresolved metric inputs"):
        _write_run(tmp_path / "metric", broken_metric)


def test_cross_producer_evidence_ids_are_rejected(tmp_path: Path):
    def duplicate_evidence(producer, value):
        if producer == "recovery-economics":
            value["evidence"][0]["id"] = "evidence.finops-lite.test"

    with pytest.raises(TrustedReportError, match="duplicate evidence id"):
        build_trusted_report(
            _write_run(tmp_path / "duplicate-evidence", duplicate_evidence)
        )


def test_non_additive_cloud_components_are_rejected(tmp_path: Path):
    def mutate(producer, value):
        if producer == "finops-lite":
            value["metrics"][1]["additivity"] = "non_additive"

    with pytest.raises(TrustedReportError, match="requires additive metrics"):
        build_trusted_report(_write_run(tmp_path, mutate))


def test_unattributed_cost_cannot_become_an_opportunity(tmp_path: Path):
    def mutate(producer, value):
        if producer == "saas-cost-analyzer":
            opportunity = _opportunity(
                "opportunity.saas.unattributed", value["producer"]
            )
            opportunity["scope"]["classification"] = "unattributed_cost"
            value["opportunities"] = [opportunity]

    with pytest.raises(TrustedReportError, match="unattributed cost"):
        _write_run(tmp_path, mutate)


def test_real_mode_requires_local_confidential_sources(tmp_path: Path):
    def valid_real(_producer, value):
        value["mode"] = "real"
        value["inputs"][0]["access"] = "local_read_only"
        value["inputs"][0]["data_classification"] = "customer_confidential"

    report = build_trusted_report(_write_run(tmp_path / "valid", valid_real))
    assert report["mode"] == "real"
    assert not any(
        "illustrative" in disclosure.lower()
        for disclosure in report["display"]["disclosures"]
    )

    def invalid_real(_producer, value):
        value["mode"] = "real"

    with pytest.raises(TrustedReportError, match="incompatible with real mode"):
        _write_run(tmp_path / "invalid", invalid_real)


def _fake_runner(args):
    output = Path(args[args.index("--output") + 1])
    executable = Path(args[0]).name
    producer = {
        "finops-lite": "finops-lite",
        "finops-watchdog": "finops-watchdog",
        "recovery-economics": "recovery-economics",
        "ai-cost-lens": "ai-cost-lens",
        "saas-cost": "saas-cost-analyzer",
    }[executable]
    output.write_text(json.dumps(_result(producer)), encoding="utf-8")
    return subprocess.CompletedProcess(args, 0, "", "")


def test_demo_pipeline_is_atomic_and_deterministic(tmp_path: Path):
    resolver = lambda name: name
    first = tmp_path / "first"
    second = tmp_path / "second"
    report = run_demo_pipeline(first, resolver=resolver, runner=_fake_runner)
    run_demo_pipeline(second, resolver=resolver, runner=_fake_runner)
    assert report["status"] == "complete"
    assert sorted(path.name for path in first.iterdir()) == [
        "ai-cost-lens.json",
        "finops-lite.json",
        "finops-watchdog.json",
        "manifest.json",
        "recovery-economics.json",
        "report.json",
        "saas-cost-analyzer.json",
    ]
    assert (first / "report.json").read_bytes() == (second / "report.json").read_bytes()


def test_demo_pipeline_rejects_existing_target(tmp_path: Path):
    target = tmp_path / "exists"
    target.mkdir()
    with pytest.raises(TrustedReportError, match="already exists"):
        run_demo_pipeline(target, resolver=lambda name: name, runner=_fake_runner)


def test_demo_pipeline_lists_all_missing_commands(tmp_path: Path):
    with pytest.raises(TrustedReportError, match="finops-lite.*saas-cost"):
        run_demo_pipeline(
            tmp_path / "run", resolver=lambda name: None, runner=_fake_runner
        )
    assert not (tmp_path / "run").exists()


def test_demo_pipeline_failure_publishes_no_partial_directory(tmp_path: Path):
    def failing(args):
        if Path(args[0]).name == "recovery-economics":
            return subprocess.CompletedProcess(args, 9, "", "scenario failed")
        return _fake_runner(args)

    target = tmp_path / "run"
    with pytest.raises(TrustedReportError, match="scenario failed"):
        run_demo_pipeline(target, resolver=lambda name: name, runner=failing)
    assert not target.exists()


def test_demo_pipeline_timeout_publishes_no_partial_directory(tmp_path: Path):
    def timeout(args):
        raise subprocess.TimeoutExpired(args, 60)

    target = tmp_path / "run"
    with pytest.raises(TrustedReportError, match="60-second demo timeout"):
        run_demo_pipeline(target, resolver=lambda name: name, runner=timeout)
    assert not target.exists()
