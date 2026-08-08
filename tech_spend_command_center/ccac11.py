"""Fail-closed CCAC 1.1 canonical-scope reconciliation."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from ccac import validate_document, validate_run_directory

from . import __version__
from .trusted import (
    ANALYTICAL_PRODUCERS,
    REQUIRED_PRODUCERS,
    TrustedReportError,
    _timestamp,
)

CONTRACT = "ccac/1.1.0"
VERSIONS = {
    "finops-lite": "0.4.0",
    "finops-watchdog": "0.5.0",
    "recovery-economics": "0.3.0",
    "ai-cost-lens": "0.3.0",
    "saas-cost-analyzer": "0.3.0",
}
SCOPES = {
    "finops-lite": ("metric.tech-spend.scope.cloud", "cloud", "cloud_provider_billing"),
    "ai-cost-lens": (
        "metric.tech-spend.scope.direct_ai",
        "direct_ai",
        "direct_ai_vendor",
    ),
    "saas-cost-analyzer": (
        "metric.tech-spend.scope.saas",
        "saas",
        "saas_invoice_or_entitlement",
    ),
}
EXPECTED_BASIS = {
    "finops-lite": "observed",
    "ai-cost-lens": "calculated",
    "saas-cost-analyzer": "calculated",
}
EXPECTED_CROSS_SCOPE = {
    "finops-lite": {"provider_billed_ai": "included", "direct_ai_vendor": "excluded"},
    "ai-cost-lens": {"provider_billed_ai": "excluded", "direct_ai_vendor": "included"},
    "saas-cost-analyzer": {
        "provider_billed_ai": "excluded",
        "direct_ai_vendor": "excluded",
    },
}
TOTAL_INPUTS = [value[0] for value in SCOPES.values()]


def _decimal(value: Any, field: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TrustedReportError(f"{field} must be a finite non-negative JSON number")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise TrustedReportError(
            f"{field} must be a finite non-negative JSON number"
        ) from exc
    if not result.is_finite() or result < 0:
        raise TrustedReportError(f"{field} must be a finite non-negative JSON number")
    return result


def _read(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        document = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TrustedReportError(f"unable to read {label}: {exc}") from exc
    if not isinstance(document, dict):
        raise TrustedReportError(f"{label} must contain a JSON object")
    return document, raw


def _require_ccac(document: dict[str, Any], label: str) -> None:
    issues = validate_document(document)
    if issues:
        first = issues[0]
        raise TrustedReportError(
            f"{label} fails released CCAC 0.2.0 validation: "
            f"{first.code} at {first.path}: {first.message}"
        )


def _safe_artifact_path(base: Path, relative_value: Any, label: str) -> Path:
    if not isinstance(relative_value, str):
        raise TrustedReportError(f"{label} relative_path must be a string")
    relative = Path(relative_value)
    if relative.is_absolute() or ".." in relative.parts:
        raise TrustedReportError(f"unsafe relative_path for {label}")
    path = (base / relative).resolve()
    if path.parent != base:
        raise TrustedReportError(
            f"{label} artifact must be directly inside the run directory"
        )
    return path


def _require_period(value: Any, field: str) -> None:
    if not isinstance(value, dict) or set(value) != {"start", "end", "timezone"}:
        raise TrustedReportError(f"{field} must be an exact half-open UTC period")
    try:
        start = date.fromisoformat(value["start"])
        end = date.fromisoformat(value["end"])
    except (TypeError, ValueError) as exc:
        raise TrustedReportError(f"{field} contains invalid dates") from exc
    if start >= end or value["timezone"] != "UTC":
        raise TrustedReportError(f"{field} must be a nonempty half-open UTC period")


def _require_temporal_fields(document: dict[str, Any], name: str) -> None:
    _timestamp(document.get("generated_at"), f"{name}.generated_at")
    _require_period(document.get("period"), f"{name}.period")
    for index, metric in enumerate(document.get("metrics", [])):
        _require_period(metric.get("period"), f"{name}.metrics[{index}].period")
    for index, evidence in enumerate(document.get("evidence", [])):
        observed_at = evidence.get("observed_at")
        if observed_at is not None:
            _timestamp(observed_at, f"{name}.evidence[{index}].observed_at")
    for index, finding in enumerate(document.get("findings", [])):
        _timestamp(
            finding.get("first_observed_at"),
            f"{name}.findings[{index}].first_observed_at",
        )
        _timestamp(
            finding.get("last_observed_at"),
            f"{name}.findings[{index}].last_observed_at",
        )


def load_producers(
    paths: dict[str, Path],
) -> tuple[dict[str, dict[str, Any]], dict[str, str], str, str]:
    if set(paths) != set(ANALYTICAL_PRODUCERS):
        raise TrustedReportError("exactly five canonical producer paths are required")
    documents: dict[str, dict[str, Any]] = {}
    hashes: dict[str, str] = {}
    run_id = mode = None
    for name in ANALYTICAL_PRODUCERS:
        document, raw = _read(paths[name], f"{name} artifact")
        _require_ccac(document, f"{name} artifact")
        _require_temporal_fields(document, name)
        producer = document.get("producer")
        if (
            document.get("contract") != CONTRACT
            or document.get("document_type") != "tool_result"
            or not isinstance(producer, dict)
            or producer.get("name") != name
            or producer.get("version") != VERSIONS[name]
        ):
            raise TrustedReportError(
                f"{name} must be an exact supported {CONTRACT} tool_result"
            )
        try:
            current_run = str(uuid.UUID(str(document.get("run_id"))))
        except (ValueError, TypeError) as exc:
            raise TrustedReportError(f"{name} run_id is invalid") from exc
        current_mode = document.get("mode")
        if current_mode not in {"illustrative", "real"}:
            raise TrustedReportError(f"{name} mode is invalid")
        if run_id is None:
            run_id, mode = current_run, current_mode
        elif (current_run, current_mode) != (run_id, mode):
            raise TrustedReportError("producer run_id and mode must match exactly")
        for field in ("inputs", "metrics", "findings", "opportunities", "evidence"):
            if not isinstance(document.get(field), list):
                raise TrustedReportError(f"{name}.{field} must be an array")
        documents[name] = document
        hashes[name] = hashlib.sha256(raw).hexdigest()
    assert run_id is not None and mode is not None
    return documents, hashes, run_id, mode


def load_preliminary_manifest(
    manifest_path: Path,
) -> tuple[dict[str, Path], str]:
    """Validate a producer-only CCAC 1.1 manifest before trusting its paths."""
    manifest, raw = _read(manifest_path, "preliminary manifest")
    _require_ccac(manifest, "preliminary manifest")
    if (
        manifest.get("contract") != CONTRACT
        or manifest.get("document_type") != "pipeline_manifest"
        or manifest.get("status") != "complete"
        or manifest.get("errors") != []
        or tuple(manifest.get("required_producers", [])) != REQUIRED_PRODUCERS
    ):
        raise TrustedReportError(
            "preliminary manifest must declare one complete CCAC 1.1 run"
        )
    started_at = _timestamp(manifest.get("started_at"), "manifest.started_at")
    completed_at = _timestamp(manifest.get("completed_at"), "manifest.completed_at")
    if datetime.fromisoformat(
        completed_at.replace("Z", "+00:00")
    ) < datetime.fromisoformat(started_at.replace("Z", "+00:00")):
        raise TrustedReportError(
            "preliminary manifest completed_at precedes started_at"
        )
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != len(ANALYTICAL_PRODUCERS):
        raise TrustedReportError(
            "preliminary manifest must contain exactly five producer artifacts"
        )
    base = manifest_path.resolve().parent
    paths: dict[str, Path] = {}
    seen_paths: set[Path] = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise TrustedReportError("preliminary manifest artifact must be an object")
        producer = artifact.get("producer")
        name = producer.get("name") if isinstance(producer, dict) else None
        if name not in ANALYTICAL_PRODUCERS or name in paths:
            raise TrustedReportError(
                "preliminary manifest requires exactly one artifact per analytical producer"
            )
        if (
            artifact.get("document_type") != "tool_result"
            or artifact.get("status") != "produced"
            or artifact.get("contract_valid") is not True
            or producer.get("version") != VERSIONS[name]
        ):
            raise TrustedReportError(
                f"preliminary manifest metadata is invalid for {name}"
            )
        path = _safe_artifact_path(base, artifact.get("relative_path"), name)
        if path in seen_paths:
            raise TrustedReportError(
                "preliminary manifest contains a duplicate artifact path"
            )
        seen_paths.add(path)
        document, artifact_raw = _read(path, f"{name} artifact")
        digest = hashlib.sha256(artifact_raw).hexdigest()
        if digest != artifact.get("content_sha256"):
            raise TrustedReportError(f"artifact hash mismatch for {name}")
        _require_ccac(document, f"{name} artifact")
        _require_temporal_fields(document, name)
        if (
            document.get("contract") != CONTRACT
            or document.get("document_type") != "tool_result"
            or document.get("run_id") != manifest.get("run_id")
            or document.get("mode") != manifest.get("mode")
            or document.get("producer") != producer
        ):
            raise TrustedReportError(
                f"manifest and document metadata mismatch for {name}"
            )
        paths[name] = path
    if set(paths) != set(ANALYTICAL_PRODUCERS):
        raise TrustedReportError(
            "preliminary manifest producer inventory is incomplete"
        )
    return paths, hashlib.sha256(raw).hexdigest()


def _unique_catalog(
    documents: dict[str, dict[str, Any]], field: str
) -> list[dict[str, Any]]:
    result = [
        deepcopy(item)
        for name in ANALYTICAL_PRODUCERS
        for item in documents[name][field]
    ]
    ids = [item.get("id") for item in result if isinstance(item, dict)]
    if len(ids) != len(result) or any(
        not isinstance(item, str) or not item for item in ids
    ):
        raise TrustedReportError(f"{field} contains an invalid identity")
    if len(ids) != len(set(ids)):
        raise TrustedReportError(f"cross-producer duplicate {field} id")
    return result


def _canonical_scopes(
    documents: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], Decimal, Decimal]:
    all_metrics = [
        (name, item)
        for name in ANALYTICAL_PRODUCERS
        for item in documents[name]["metrics"]
    ]
    candidates = [
        (name, item)
        for name, item in all_metrics
        if isinstance(item, dict)
        and isinstance(item.get("accounting_boundary"), dict)
        and item["accounting_boundary"].get("relationship") == "canonical_scope_spend"
    ]
    if any(
        item.get("metric_role") == "technology_spend_total"
        for _, item in all_metrics
        if isinstance(item, dict)
    ):
        raise TrustedReportError(
            "only the Command Center may publish technology_spend_total"
        )
    if len(candidates) != 3:
        raise TrustedReportError(
            "CCAC 1.1 requires exactly three canonical scope metrics"
        )
    scopes: list[dict[str, Any]] = []
    values: list[Decimal] = []
    units: list[Decimal] = []
    expected_period = documents["finops-lite"].get("period")
    for owner, (metric_id, scope, channel) in SCOPES.items():
        matches = [
            (producer, metric)
            for producer, metric in candidates
            if metric.get("id") == metric_id
        ]
        if len(matches) != 1 or matches[0][0] != owner:
            raise TrustedReportError(
                f"{metric_id} must appear exactly once from {owner}"
            )
        metric = matches[0][1]
        boundary = metric["accounting_boundary"]
        required = {
            "scope": scope,
            "canonical_owner": owner,
            "source_channel": channel,
            "cost_basis": "net_cost",
            "coverage": "complete",
            "total_eligible": True,
        }
        if any(boundary.get(key) != value for key, value in required.items()):
            raise TrustedReportError(
                f"{metric_id} accounting boundary is not total-eligible canonical {scope}"
            )
        if boundary.get("overlap", {}).get("disposition") != "resolved":
            raise TrustedReportError(
                f"{metric_id} billing-channel overlap must be resolved"
            )
        if (
            metric.get("unit") != "currency"
            or metric.get("currency") != "USD"
            or metric.get("basis") != EXPECTED_BASIS[owner]
            or metric.get("additivity") != "additive"
            or metric.get("quality_status") != "valid"
        ):
            raise TrustedReportError(
                f"{metric_id} has incompatible unit, currency, additivity, or quality"
            )
        if boundary.get("cross_scope_treatments") != EXPECTED_CROSS_SCOPE[owner]:
            raise TrustedReportError(
                f"{metric_id} cross-scope billing treatment is incompatible"
            )
        if metric.get("period") != expected_period:
            raise TrustedReportError(
                f"{metric_id} period must match the canonical report period"
            )
        evidence_ids = metric.get("evidence_ids")
        known_evidence = {item.get("id") for item in documents[owner]["evidence"]}
        if (
            not isinstance(evidence_ids, list)
            or not evidence_ids
            or not set(evidence_ids).issubset(known_evidence)
        ):
            raise TrustedReportError(
                f"{metric_id} must have resolved producer evidence"
            )
        values.append(_decimal(metric.get("value"), f"{metric_id}.value"))
        unit = _decimal(
            boundary.get("currency_minor_unit"), f"{metric_id}.currency_minor_unit"
        )
        if unit <= 0 or unit > Decimal("0.01"):
            raise TrustedReportError(f"{metric_id} currency minor unit is invalid")
        units.append(unit)
        scopes.append(deepcopy(metric))
    if documents["finops-watchdog"]["quality"].get("status") == "failed":
        raise TrustedReportError(
            "finops-watchdog may not be failed in a complete report"
        )
    if documents["recovery-economics"]["quality"].get("status") not in {
        "valid",
        "partial",
    }:
        raise TrustedReportError("recovery-economics quality is invalid")
    if len(set(units)) != 1:
        raise TrustedReportError(
            "canonical scopes must declare one common currency minor unit"
        )
    return scopes, sum(values, Decimal("0")), units[0]


def build_report(
    paths: dict[str, Path], *, generated_at: str, manifest_sha256: str
) -> dict[str, Any]:
    documents, hashes, run_id, mode = load_producers(paths)
    metrics = _unique_catalog(documents, "metrics")
    findings = _unique_catalog(documents, "findings")
    opportunities = _unique_catalog(documents, "opportunities")
    evidence = _unique_catalog(documents, "evidence")
    known_metric_ids = {item["id"] for item in metrics}
    known_finding_ids = {item["id"] for item in findings}
    known_evidence_ids = {item["id"] for item in evidence}
    for item in metrics:
        if not set(item.get("input_metric_ids", [])).issubset(
            known_metric_ids
        ) or not set(item.get("evidence_ids", [])).issubset(known_evidence_ids):
            raise TrustedReportError(f"broken metric lineage for {item['id']}")
    for item in findings:
        if not set(item.get("metric_ids", [])).issubset(known_metric_ids) or not set(
            item.get("evidence_ids", [])
        ).issubset(known_evidence_ids):
            raise TrustedReportError(f"broken finding lineage for {item['id']}")
    for item in opportunities:
        if not set(item.get("related_finding_ids", [])).issubset(known_finding_ids):
            raise TrustedReportError(f"broken opportunity lineage for {item['id']}")
    scopes, total, tolerance = _canonical_scopes(documents)
    period = scopes[0]["period"]
    total_metric = {
        "id": "metric.tech-spend.total",
        "name": "Technology Spend",
        "value": float(total),
        "unknown_reason": None,
        "unit": "currency",
        "currency": "USD",
        "basis": "calculated",
        "additivity": "additive",
        "period": deepcopy(period),
        "dimensions": {},
        "formula": "cloud + direct_ai + saas",
        "input_metric_ids": TOTAL_INPUTS,
        "evidence_ids": sorted(
            {item for metric in scopes for item in metric["evidence_ids"]}
        ),
        "quality_status": "valid",
        "metric_role": "technology_spend_total",
    }
    metrics.append(total_metric)
    section_ids = {
        name: [
            item["id"]
            for item in documents[name]["metrics"]
            if item.get("quality_status") != "invalid"
        ]
        for name in ANALYTICAL_PRODUCERS
    }
    section_ids["technology-spend"] = TOTAL_INPUTS
    disclosures = [
        (
            "All data in this report is illustrative; no customer systems or live accounts are connected."
            if mode == "illustrative"
            else "This report uses declared producer inputs; review source provenance before decisions."
        ),
        "Technology Spend contains Cloud, direct AI, and SaaS canonical scopes only.",
        "FinOps Watchdog and Recovery Economics are diagnostic-only and add no spend.",
        "This report is analysis, not verified savings or automated remediation.",
        "Cloud Cost Guard is not connected, and Lumen is not grounded in this report.",
    ]
    report = {
        "contract": CONTRACT,
        "document_type": "trusted_report",
        "producer": {"name": "tech-spend-command-center", "version": __version__},
        "report_id": "report.tech-spend.trusted",
        "run_id": run_id,
        "generated_at": _timestamp(generated_at),
        "mode": mode,
        "status": "complete",
        "period": deepcopy(period),
        "included_producers": [
            deepcopy(documents[name]["producer"]) for name in ANALYTICAL_PRODUCERS
        ],
        "omitted_producers": [],
        "producer_quality": [
            {
                "producer": deepcopy(documents[name]["producer"]),
                "quality": deepcopy(documents[name]["quality"]),
            }
            for name in ANALYTICAL_PRODUCERS
        ],
        "metric_catalog": metrics,
        "finding_catalog": findings,
        "opportunity_catalog": opportunities,
        "opportunity_aggregates": [],
        "display": {
            "headline_metric_ids": ["metric.tech-spend.total"],
            "section_metric_ids": section_ids,
            "finding_ids": [item["id"] for item in findings],
            "opportunity_aggregate_ids": [],
            "disclosures": disclosures,
        },
        "reconciliation": [
            {
                "id": "reconciliation.tech-spend",
                "reconciliation_type": "technology_spend_total",
                "assertion": "Canonical Cloud, direct-AI, and SaaS scopes sum exactly to Technology Spend.",
                "input_metric_ids": TOTAL_INPUTS,
                "output_metric_id": "metric.tech-spend.total",
                "difference": 0.0,
                "tolerance": float(tolerance),
                "status": "passed",
            }
        ],
        "provenance": {"manifest_sha256": manifest_sha256, "artifact_sha256s": hashes},
    }
    _require_ccac(report, "trusted report")
    return report


def build_report_from_manifest(
    manifest_path: Path, *, generated_at: str, report_id: str
) -> dict[str, Any]:
    paths, preliminary_hash = load_preliminary_manifest(manifest_path)
    report = build_report(
        paths, generated_at=generated_at, manifest_sha256=preliminary_hash
    )
    report["report_id"] = report_id
    _require_ccac(report, "trusted report")
    return report


def build_manifest(
    paths: dict[str, Path],
    *,
    manifest_path: Path,
    started_at: str,
    completed_at: str,
    report_path: Path | None = None,
) -> dict[str, Any]:
    documents, hashes, run_id, mode = load_producers(paths)
    base = manifest_path.resolve().parent
    artifacts = []
    for name in ANALYTICAL_PRODUCERS:
        relative = Path(os.path.relpath(paths[name].resolve(), base))
        if ".." in relative.parts:
            raise TrustedReportError(
                f"{name} artifact must be inside the manifest directory"
            )
        artifacts.append(
            {
                "producer": deepcopy(documents[name]["producer"]),
                "document_type": "tool_result",
                "relative_path": relative.as_posix(),
                "content_sha256": hashes[name],
                "status": "produced",
                "contract_valid": True,
                "omission_reason": None,
            }
        )
    if report_path is not None:
        report, raw = _read(report_path, "trusted report")
        _require_ccac(report, "trusted report")
        relative = Path(os.path.relpath(report_path.resolve(), base))
        if (
            ".." in relative.parts
            or report.get("contract") != CONTRACT
            or report.get("document_type") != "trusted_report"
            or report.get("run_id") != run_id
        ):
            raise TrustedReportError(
                "trusted report does not belong to this CCAC 1.1 run"
            )
        artifacts.append(
            {
                "producer": deepcopy(report["producer"]),
                "document_type": "trusted_report",
                "relative_path": relative.as_posix(),
                "content_sha256": hashlib.sha256(raw).hexdigest(),
                "status": "produced",
                "contract_valid": True,
                "omission_reason": None,
            }
        )
    start = _timestamp(started_at)
    completed = _timestamp(completed_at)
    if datetime.fromisoformat(
        completed.replace("Z", "+00:00")
    ) < datetime.fromisoformat(start.replace("Z", "+00:00")):
        raise TrustedReportError("completed_at cannot be before started_at")
    manifest = {
        "contract": CONTRACT,
        "document_type": "pipeline_manifest",
        "run_id": run_id,
        "mode": mode,
        "started_at": start,
        "completed_at": completed,
        "status": "complete",
        "required_producers": list(REQUIRED_PRODUCERS),
        "artifacts": artifacts,
        "errors": [],
    }
    _require_ccac(manifest, "pipeline manifest")
    return manifest


def validate_complete_run(
    run_directory: Path,
) -> tuple[dict[str, Any], dict[str, Path]]:
    """Validate all seven files and exact report correspondence."""
    directory = run_directory.resolve()
    issues = validate_run_directory(directory)
    if issues:
        first = issues[0]
        raise TrustedReportError(
            "complete run fails released CCAC 0.2.0 validation: "
            f"{first.code} at {first.path}: {first.message}"
        )
    manifest, _ = _read(directory / "manifest.json", "manifest.json")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 6:
        raise TrustedReportError(
            "complete run manifest must contain exactly six artifacts"
        )
    producer_paths: dict[str, Path] = {}
    report_path: Path | None = None
    expected_paths = {directory / "manifest.json"}
    seen_paths: set[Path] = set()
    for artifact in artifacts:
        producer = artifact.get("producer", {}).get("name")
        path = _safe_artifact_path(
            directory, artifact.get("relative_path"), str(producer)
        )
        if path in seen_paths:
            raise TrustedReportError(
                "complete run manifest contains a duplicate artifact path"
            )
        seen_paths.add(path)
        expected_paths.add(path)
        if artifact.get("document_type") == "tool_result":
            producer_paths[producer] = path
        elif (
            producer == "tech-spend-command-center"
            and artifact.get("document_type") == "trusted_report"
        ):
            report_path = path
    if set(producer_paths) != set(ANALYTICAL_PRODUCERS) or report_path is None:
        raise TrustedReportError(
            "complete run inventory must contain five producers and one trusted report"
        )
    actual_paths = {path.resolve() for path in directory.rglob("*.json")}
    if actual_paths != {path.resolve() for path in expected_paths}:
        raise TrustedReportError(
            "complete run contains missing or unexpected JSON artifacts"
        )
    stored_report, _ = _read(report_path, "report.json")
    expected_report = build_report(
        producer_paths,
        generated_at=stored_report.get("generated_at"),
        manifest_sha256=stored_report.get("provenance", {}).get("manifest_sha256"),
    )
    expected_report["report_id"] = stored_report.get("report_id")
    _require_ccac(expected_report, "recomputed trusted report")
    if stored_report != expected_report:
        raise TrustedReportError(
            "report.json does not correspond exactly to the validated producers and reconciliation"
        )
    return stored_report, producer_paths
