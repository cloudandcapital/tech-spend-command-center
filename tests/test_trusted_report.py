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
        "producer": {
            "name": producer,
            "version": (
                "0.3.0"
                if producer == "finops-lite"
                else "0.4.0" if producer == "finops-watchdog" else "0.2.0"
            ),
        },
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


def _finding(finding_id: str, description: str) -> dict:
    return {
        "id": finding_id,
        "finding_type": "other",
        "title": "Review finding",
        "description": description,
        "severity": "medium",
        "status": "open",
        "metric_ids": ["metric.cloud.total"],
        "evidence_ids": ["evidence.finops-lite.test"],
        "first_observed_at": NOW,
        "last_observed_at": NOW,
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


def test_repeated_overlap_group_excludes_every_candidate(tmp_path: Path):
    def mutate(producer, value):
        if producer == "saas-cost-analyzer":
            value["opportunities"] = [
                {
                    **_opportunity("opportunity.saas.z", value["producer"]),
                    "status": "approved",
                    "confidence": "high",
                },
                {
                    **_opportunity("opportunity.saas.a", value["producer"]),
                    "status": "identified",
                    "confidence": "low",
                },
            ]

    report = build_trusted_report(_write_run(tmp_path, mutate))
    aggregate = report["opportunity_aggregates"][0]
    assert aggregate["opportunity_ids"] == []
    assert aggregate["excluded_opportunity_ids"] == [
        "opportunity.saas.a",
        "opportunity.saas.z",
    ]
    assert aggregate["expected"] == 0
    assert "no canonical selection or precedence" in aggregate["inclusion_rule"]


def test_repeated_overlap_group_is_global_across_periods(tmp_path: Path):
    def mutate(producer, value):
        if producer == "saas-cost-analyzer":
            annual = _opportunity("opportunity.saas.annual", value["producer"])
            monthly = _opportunity("opportunity.saas.monthly", value["producer"])
            monthly["estimate"]["period"] = "monthly"
            value["opportunities"] = [annual, monthly]

    report = build_trusted_report(_write_run(tmp_path, mutate))
    assert all(
        aggregate["opportunity_ids"] == [] and aggregate["excluded_opportunity_ids"]
        for aggregate in report["opportunity_aggregates"]
    )


def test_repeated_overlap_group_is_global_across_producers(tmp_path: Path):
    def mutate(producer, value):
        if producer in {"recovery-economics", "saas-cost-analyzer"}:
            opportunity = _opportunity(
                f"opportunity.{producer}.test", value["producer"]
            )
            opportunity["evidence_ids"] = [f"evidence.{producer}.test"]
            value["opportunities"] = [opportunity]

    report = build_trusted_report(_write_run(tmp_path, mutate))
    aggregate = report["opportunity_aggregates"][0]
    assert aggregate["opportunity_ids"] == []
    assert len(aggregate["excluded_opportunity_ids"]) == 2


def test_unique_and_groupless_none_known_opportunities_remain_eligible(tmp_path: Path):
    def mutate(producer, value):
        if producer == "saas-cost-analyzer":
            unique = _opportunity("opportunity.saas.unique", value["producer"])
            groupless = _opportunity("opportunity.saas.groupless", value["producer"])
            groupless["overlap"]["group_id"] = None
            value["opportunities"] = [unique, groupless]

    report = build_trusted_report(_write_run(tmp_path, mutate))
    aggregate = report["opportunity_aggregates"][0]
    assert aggregate["opportunity_ids"] == [
        "opportunity.saas.groupless",
        "opportunity.saas.unique",
    ]
    assert aggregate["expected"] == 200


def test_overlap_group_id_must_be_canonical(tmp_path: Path):
    def mutate(producer, value):
        if producer == "saas-cost-analyzer":
            opportunity = _opportunity("opportunity.saas.bad-group", value["producer"])
            opportunity["overlap"]["group_id"] = "Bad group"
            value["opportunities"] = [opportunity]

    with pytest.raises(TrustedReportError, match="group_id must be a canonical"):
        _write_run(tmp_path, mutate)


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


def test_cloud_command_in_review_step_is_rejected(tmp_path: Path):
    def mutate(producer, value):
        if producer == "saas-cost-analyzer":
            opportunity = _opportunity(
                "opportunity.saas.review-command", value["producer"]
            )
            opportunity["review"]["non_mutating_review_steps"] = [
                "aws ec2 stop-instances --instance-ids i-123"
            ]
            value["opportunities"] = [opportunity]

    with pytest.raises(TrustedReportError, match="mutating public review step"):
        _write_run(tmp_path, mutate)


@pytest.mark.parametrize(
    "steps",
    [
        "Delete the license.",
        {"step": "Inspect"},
        [["Inspect"]],
        None,
        [],
        [""],
        ["   "],
        [1],
    ],
)
def test_review_steps_require_nonempty_array_of_nonempty_strings(tmp_path: Path, steps):
    def mutate(producer, value):
        if producer == "saas-cost-analyzer":
            opportunity = _opportunity("opportunity.saas.steps", value["producer"])
            opportunity["review"]["non_mutating_review_steps"] = steps
            value["opportunities"] = [opportunity]

    with pytest.raises(TrustedReportError, match="nonempty array of nonempty strings"):
        _write_run(tmp_path, mutate)


@pytest.mark.parametrize(
    "step",
    [
        "After reviewing the roster, delete the license.",
        "Confirm the owner, then revoke the seat.",
        "Review the deployment and then scale it to zero.",
    ],
)
def test_review_step_detects_mutation_after_introductory_language(
    tmp_path: Path, step: str
):
    def mutate(producer, value):
        if producer == "saas-cost-analyzer":
            opportunity = _opportunity("opportunity.saas.steps", value["producer"])
            opportunity["review"]["non_mutating_review_steps"] = [step]
            value["opportunities"] = [opportunity]

    with pytest.raises(TrustedReportError, match="mutating public review step"):
        _write_run(tmp_path, mutate)


@pytest.mark.parametrize(
    "command",
    [
        "aws ec2 terminate-instances --instance-ids i-123",
        "aws s3 rm s3://example-bucket --recursive",
        "az vm deallocate --name example",
        "gcloud compute instances delete example",
        "kubectl apply -f deployment.yaml",
        "terraform destroy -auto-approve",
        "curl -X POST https://api.example.test/change",
        "http PUT https://api.example.test/change",
        "DELETE https://api.example.test/resource/1",
    ],
)
def test_mutating_commands_in_public_findings_are_rejected(
    tmp_path: Path, command: str
):
    def mutate(producer, value):
        if producer == "finops-lite":
            value["findings"] = [_finding("finding.cloud.command", command)]

    with pytest.raises(TrustedReportError, match="mutating public command"):
        _write_run(tmp_path, mutate)


def test_mutating_command_in_public_opportunity_text_is_rejected(tmp_path: Path):
    def mutate(producer, value):
        if producer == "saas-cost-analyzer":
            opportunity = _opportunity("opportunity.saas.command", value["producer"])
            opportunity["title"] = "Run kubectl scale deployment app --replicas=0"
            value["opportunities"] = [opportunity]

    with pytest.raises(TrustedReportError, match="mutating public command"):
        _write_run(tmp_path, mutate)


def test_benign_update_and_create_prose_remains_accepted(tmp_path: Path):
    def mutate(producer, value):
        if producer == "finops-lite":
            value["findings"] = [
                _finding(
                    "finding.cloud.benign",
                    "Create a review record before deciding whether an update is appropriate.",
                )
            ]
        if producer == "saas-cost-analyzer":
            opportunity = _opportunity("opportunity.saas.benign", value["producer"])
            opportunity["title"] = (
                "Review the proposed update and create an approval record"
            )
            opportunity["review"]["non_mutating_review_steps"] = [
                "Confirm that any future change requires separate approval."
            ]
            value["opportunities"] = [opportunity]

    report = build_trusted_report(_write_run(tmp_path, mutate))
    assert report["status"] == "complete"


def test_manifest_requires_exactly_one_of_all_five_producers(tmp_path: Path):
    manifest_path = _write_run(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    manifest["artifacts"] = manifest["artifacts"][:-1]
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(TrustedReportError, match="exactly one produced artifact"):
        build_trusted_report(manifest_path)


@pytest.mark.parametrize("status", ["failed", "partial", None])
def test_trusted_report_requires_complete_manifest_status(
    tmp_path: Path, status: str | None
):
    manifest_path = _write_run(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    manifest["status"] = status
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(TrustedReportError, match="status must be complete"):
        build_trusted_report(manifest_path)


def test_trusted_report_rejects_manifest_errors(tmp_path: Path):
    manifest_path = _write_run(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    manifest["errors"] = [
        {"code": "quality.test", "severity": "error", "message": "bad"}
    ]
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(TrustedReportError, match="errors must be an empty array"):
        build_trusted_report(manifest_path)


@pytest.mark.parametrize(
    "field,value",
    [
        ("started_at", None),
        ("completed_at", None),
        ("started_at", "2026-08-04T12:00:00"),
        ("completed_at", "not-a-time"),
    ],
)
def test_trusted_report_rejects_missing_naive_or_invalid_manifest_timestamps(
    tmp_path: Path, field: str, value: str | None
):
    manifest_path = _write_run(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    if value is None:
        manifest.pop(field)
    else:
        manifest[field] = value
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(TrustedReportError, match="timezone-aware RFC3339"):
        build_trusted_report(manifest_path)


def test_trusted_report_rejects_reversed_manifest_timestamps(tmp_path: Path):
    manifest_path = _write_run(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    manifest["started_at"] = "2026-08-04T13:00:00Z"
    manifest["completed_at"] = "2026-08-04T12:00:00Z"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(TrustedReportError, match="cannot be before"):
        build_trusted_report(manifest_path)


def test_manifest_artifact_metadata_is_strict(tmp_path: Path):
    manifest_path = _write_run(tmp_path / "type")
    manifest = json.loads(manifest_path.read_text())
    manifest["artifacts"][0]["document_type"] = "trusted_report"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(TrustedReportError, match="document_type must be tool_result"):
        build_trusted_report(manifest_path)

    manifest_path = _write_run(tmp_path / "version")
    manifest = json.loads(manifest_path.read_text())
    manifest["artifacts"][0]["producer"]["version"] = "0.2.1"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(TrustedReportError, match="versions do not match"):
        build_trusted_report(manifest_path)

    manifest_path = _write_run(tmp_path / "structure")
    manifest = json.loads(manifest_path.read_text())
    manifest["artifacts"][0].pop("content_sha256")
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(TrustedReportError, match="structurally invalid"):
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

    with pytest.raises(TrustedReportError, match="unsupported"):
        _write_run(tmp_path / "version", unsupported)


@pytest.mark.parametrize(
    "version",
    [
        "0.2.bad",
        "0.2.0junk",
        "0.2.",
        "00.2.0",
        "0.2.0-alpha.1",
        "0.2.0+build.1",
        "0.20.0",
        "0.3.0",
    ],
)
def test_producer_version_requires_canonical_bare_compatible_release(
    tmp_path: Path, version: str
):
    def mutate(producer, value):
        if producer == "recovery-economics":
            value["producer"]["version"] = version

    with pytest.raises(TrustedReportError, match="unsupported"):
        _write_run(tmp_path, mutate)


@pytest.mark.parametrize(
    "version",
    [
        f"0.4.{'9' * 65}",
        f"{'9' * 22}.{'8' * 22}.{'7' * 22}",
    ],
)
def test_over_limit_versions_fail_with_controlled_trusted_error(
    tmp_path: Path, version: str
):
    def mutate(producer, value):
        if producer == "finops-watchdog":
            value["producer"]["version"] = version

    with pytest.raises(
        TrustedReportError,
        match="finops-watchdog version is unsupported by Tech Spend Command Center 0.2",
    ):
        _write_run(tmp_path, mutate)


@pytest.mark.parametrize("version", ["0.4.0", "0.4.1", "0.4.999"])
def test_watchdog_0_4_versions_are_accepted(tmp_path: Path, version: str):
    def mutate(producer, value):
        if producer == "finops-watchdog":
            value["producer"]["version"] = version

    report = build_trusted_report(_write_run(tmp_path, mutate))
    watchdog = next(
        item
        for item in report["included_producers"]
        if item["name"] == "finops-watchdog"
    )
    assert watchdog["version"] == version


@pytest.mark.parametrize(
    "version", ["0.2.0", "0.2.99", "0.3.0", "0.3.99", "0.5.0", "0.5.1"]
)
def test_unsupported_watchdog_versions_fail_closed(tmp_path: Path, version: str):
    def mutate(producer, value):
        if producer == "finops-watchdog":
            value["producer"]["version"] = version

    with pytest.raises(TrustedReportError, match="unsupported"):
        _write_run(tmp_path, mutate)


@pytest.mark.parametrize("version", ["0.3.0", "0.3.1", "0.3.999"])
def test_finops_lite_0_3_versions_are_accepted(tmp_path: Path, version: str):
    def mutate(producer, value):
        if producer == "finops-lite":
            value["producer"]["version"] = version

    report = build_trusted_report(_write_run(tmp_path, mutate))
    finops_lite = next(
        item for item in report["included_producers"] if item["name"] == "finops-lite"
    )
    assert finops_lite["version"] == version


@pytest.mark.parametrize(
    "version",
    [
        "0.2.0",
        "0.2.999",
        "0.4.0",
        "0.3.0-alpha.1",
        "0.3.0+build.1",
        "00.3.0",
        "0.3",
        "0.3.0.1",
        "0.3.bad",
        f"0.3.{'9' * 65}",
    ],
)
def test_unsupported_finops_lite_versions_fail_closed(tmp_path: Path, version: str):
    def mutate(producer, value):
        if producer == "finops-lite":
            value["producer"]["version"] = version

    with pytest.raises(TrustedReportError, match="unsupported"):
        _write_run(tmp_path, mutate)


@pytest.mark.parametrize(
    "producer",
    [
        "recovery-economics",
        "ai-cost-lens",
        "saas-cost-analyzer",
    ],
)
@pytest.mark.parametrize("version", ["0.2.0", "0.2.1", "0.2.999"])
def test_other_producer_0_2_versions_are_accepted(
    tmp_path: Path, producer: str, version: str
):
    def mutate(name, value):
        if name == producer:
            value["producer"]["version"] = version

    report = build_trusted_report(_write_run(tmp_path, mutate))
    included = next(
        item for item in report["included_producers"] if item["name"] == producer
    )
    assert included["version"] == version


@pytest.mark.parametrize(
    "producer",
    [
        "recovery-economics",
        "ai-cost-lens",
        "saas-cost-analyzer",
    ],
)
@pytest.mark.parametrize("version", ["0.1.99", "0.3.0", "1.2.0"])
def test_unsupported_versions_for_other_producers_fail_closed(
    tmp_path: Path, producer: str, version: str
):
    def mutate(name, value):
        if name == producer:
            value["producer"]["version"] = version

    with pytest.raises(TrustedReportError, match="unsupported"):
        _write_run(tmp_path, mutate)


def test_contract_version_is_independent_of_application_version(tmp_path: Path):
    def mutate(producer, value):
        if producer == "finops-watchdog":
            value["producer"]["version"] = "0.4.1"
            value["contract"] = "ccac/2.0.0"

    with pytest.raises(TrustedReportError, match="canonical tool_result"):
        _write_run(tmp_path, mutate)


def test_malformed_producer_objects_raise_trusted_error(tmp_path: Path):
    def mutate(producer, value):
        if producer == "recovery-economics":
            value["producer"] = "not-an-object"

    with pytest.raises(TrustedReportError, match="producer must be an object"):
        _write_run(tmp_path, mutate)


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


def test_every_present_currency_is_validated(tmp_path: Path):
    def mutate(producer, value):
        if producer == "ai-cost-lens":
            value["metrics"][0]["unit"] = "requests"
            value["metrics"][0]["currency"] = "usd"

    with pytest.raises(TrustedReportError, match="three-letter ISO currency"):
        _write_run(tmp_path, mutate)


@pytest.mark.parametrize("report_id", ["Report.Bad", "bad id", "a" * 161, ""])
def test_report_id_must_be_canonical(tmp_path: Path, report_id: str):
    with pytest.raises(TrustedReportError, match="report_id"):
        build_trusted_report(_write_run(tmp_path), report_id=report_id)


def test_generated_at_must_be_timezone_aware(tmp_path: Path):
    with pytest.raises(TrustedReportError, match="timezone-aware RFC3339"):
        build_trusted_report(_write_run(tmp_path), generated_at="2026-08-04T12:00:00")


def test_invalid_cloud_total_fails_closed(tmp_path: Path):
    def mutate(producer, value):
        if producer == "finops-lite":
            value["metrics"][0]["quality_status"] = "invalid"

    with pytest.raises(TrustedReportError, match="cloud.total is invalid"):
        build_trusted_report(_write_run(tmp_path, mutate))


def test_invalid_cloud_service_metric_fails_closed(tmp_path: Path):
    def mutate(producer, value):
        if producer == "finops-lite":
            value["metrics"][1]["quality_status"] = "invalid"

    with pytest.raises(TrustedReportError, match="invalid cloud service metric"):
        build_trusted_report(_write_run(tmp_path, mutate))


def test_invalid_proposed_headline_is_catalog_only(tmp_path: Path):
    def mutate(producer, value):
        if producer == "ai-cost-lens":
            value["metrics"][0]["quality_status"] = "invalid"

    report = build_trusted_report(_write_run(tmp_path, mutate))
    assert report["status"] == "complete"
    assert "metric.ai.total-cost" not in report["display"]["headline_metric_ids"]
    assert "metric.ai.total-cost" not in report["display"]["section_metric_ids"].get(
        "ai-cost-lens", []
    )
    assert any(
        metric["id"] == "metric.ai.total-cost" for metric in report["metric_catalog"]
    )
    assert any(
        "audit only" in disclosure for disclosure in report["display"]["disclosures"]
    )


def test_broken_source_and_metric_lineage_fail_closed(tmp_path: Path):
    def broken_source(producer, value):
        if producer == "ai-cost-lens":
            value["evidence"][0]["source_ids"] = ["source.missing"]

    with pytest.raises(TrustedReportError, match="unresolved references"):
        _write_run(tmp_path / "source", broken_source)

    def broken_metric(producer, value):
        if producer == "ai-cost-lens":
            value["metrics"][0]["input_metric_ids"] = ["metric.missing"]

    with pytest.raises(TrustedReportError, match="unresolved references"):
        _write_run(tmp_path / "metric", broken_metric)


@pytest.mark.parametrize("source_ids", [[], None])
def test_evidence_requires_at_least_one_source_reference(
    tmp_path: Path, source_ids: list[str] | None
):
    def mutate(producer, value):
        if producer == "ai-cost-lens":
            if source_ids is None:
                value["evidence"][0].pop("source_ids")
            else:
                value["evidence"][0]["source_ids"] = source_ids

    with pytest.raises(TrustedReportError, match="array of canonical ids"):
        _write_run(tmp_path, mutate)


@pytest.mark.parametrize(
    "reference_field",
    [
        "evidence.source_ids",
        "metric.evidence_ids",
        "metric.input_metric_ids",
        "finding.metric_ids",
        "finding.evidence_ids",
        "opportunity.evidence_ids",
        "opportunity.related_finding_ids",
        "opportunity.related_opportunity_ids",
    ],
)
def test_reference_fields_reject_scalar_strings_that_match_existing_ids(
    tmp_path: Path, reference_field: str
):
    def mutate(producer, value):
        if producer != "saas-cost-analyzer":
            return
        finding = {
            **_finding("finding.saas.test", "Review the supplied evidence."),
            "metric_ids": ["metric.saas.crm.invoice-cost"],
            "evidence_ids": ["evidence.saas-cost-analyzer.test"],
        }
        first = _opportunity("opportunity.saas.first", value["producer"])
        second = _opportunity("opportunity.saas.second", value["producer"])
        first["related_finding_ids"] = ["finding.saas.test"]
        first["related_opportunity_ids"] = ["opportunity.saas.second"]
        value["findings"] = [finding]
        value["opportunities"] = [first, second]
        targets = {
            "evidence.source_ids": (
                value["evidence"][0],
                "source_ids",
                "source.saas-cost-analyzer.test",
            ),
            "metric.evidence_ids": (
                value["metrics"][0],
                "evidence_ids",
                "evidence.saas-cost-analyzer.test",
            ),
            "metric.input_metric_ids": (
                value["metrics"][0],
                "input_metric_ids",
                "metric.saas.crm.invoice-cost",
            ),
            "finding.metric_ids": (
                finding,
                "metric_ids",
                "metric.saas.crm.invoice-cost",
            ),
            "finding.evidence_ids": (
                finding,
                "evidence_ids",
                "evidence.saas-cost-analyzer.test",
            ),
            "opportunity.evidence_ids": (
                first,
                "evidence_ids",
                "evidence.saas-cost-analyzer.test",
            ),
            "opportunity.related_finding_ids": (
                first,
                "related_finding_ids",
                "finding.saas.test",
            ),
            "opportunity.related_opportunity_ids": (
                first,
                "related_opportunity_ids",
                "opportunity.saas.second",
            ),
        }
        target, key, scalar = targets[reference_field]
        target[key] = scalar

    with pytest.raises(TrustedReportError, match="array of canonical ids"):
        _write_run(tmp_path, mutate)


def test_reference_fields_reject_duplicate_ids(tmp_path: Path):
    def mutate(producer, value):
        if producer == "ai-cost-lens":
            evidence_id = "evidence.ai-cost-lens.test"
            value["metrics"][0]["evidence_ids"] = [evidence_id, evidence_id]

    with pytest.raises(TrustedReportError, match="duplicate ids"):
        _write_run(tmp_path, mutate)


def test_invalid_metric_cannot_reenter_display_or_aggregates_through_lineage(
    tmp_path: Path,
):
    def mutate(producer, value):
        if producer == "ai-cost-lens":
            value["metrics"][0]["quality_status"] = "invalid"
            finding = {
                **_finding("finding.ai.invalid", "Review invalid AI data."),
                "metric_ids": ["metric.ai.total-cost"],
                "evidence_ids": ["evidence.ai-cost-lens.test"],
            }
            opportunity = _opportunity("opportunity.ai.invalid", value["producer"])
            opportunity["evidence_ids"] = ["evidence.ai-cost-lens.test"]
            opportunity["related_finding_ids"] = ["finding.ai.invalid"]
            value["findings"] = [finding]
            value["opportunities"] = [opportunity]

    report = build_trusted_report(_write_run(tmp_path, mutate))
    assert "finding.ai.invalid" not in report["display"]["finding_ids"]
    assert any(
        finding["id"] == "finding.ai.invalid" for finding in report["finding_catalog"]
    )
    aggregate = report["opportunity_aggregates"][0]
    assert "opportunity.ai.invalid" not in aggregate["opportunity_ids"]
    assert "opportunity.ai.invalid" in aggregate["excluded_opportunity_ids"]
    assert any(
        "invalid metrics remain audit-only" in disclosure
        for disclosure in report["display"]["disclosures"]
    )


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
