"""Manifest-controlled aggregation of CCAC tool results into a trusted report."""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__

CONTRACT = "ccac/1.0.0"
ANALYTICAL_PRODUCERS = (
    "finops-lite",
    "finops-watchdog",
    "recovery-economics",
    "ai-cost-lens",
    "saas-cost-analyzer",
)
REQUIRED_PRODUCERS = ANALYTICAL_PRODUCERS + ("tech-spend-command-center",)
MUTATING_COMMAND = re.compile(
    r"\b(delete|terminate|release|stop-instances|start-instances|resize|update|create|patch|remove|destroy)\b",
    re.I,
)
ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[._:-][a-z0-9]+)*$")
SUPPORTED_VERSION = re.compile(r"^0\.2(?:\.|$)")
METRIC_BASES = {"observed", "calculated", "allocated", "estimated", "unknown"}
ADDITIVITY = {"additive", "non_additive", "semi_additive", "ratio"}
OPPORTUNITY_STATUSES = {
    "identified",
    "under_review",
    "approved",
    "rejected",
    "implemented_pending_verification",
    "closed",
}
INCLUDED_OPPORTUNITY_STATUSES = {"identified", "under_review", "approved"}


class TrustedReportError(ValueError):
    pass


def _load(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except FileNotFoundError as exc:
        raise TrustedReportError(f"file not found: {path}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TrustedReportError(f"unable to read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise TrustedReportError(f"JSON root must be an object: {path}")
    return value, raw


def _timestamp(value: str | None) -> str:
    try:
        parsed = (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            if value
            else datetime.now(timezone.utc)
        )
    except ValueError as exc:
        raise TrustedReportError("generated_at must be RFC3339") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (
        parsed.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _ids(items: Any, field: str) -> set[str]:
    if not isinstance(items, list):
        raise TrustedReportError(f"{field} must be an array")
    values = []
    for index, item in enumerate(items):
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("id"), str)
            or not item["id"]
            or not ID_PATTERN.fullmatch(item["id"])
        ):
            raise TrustedReportError(f"{field}[{index}] requires an id")
        values.append(item["id"])
    if len(values) != len(set(values)):
        raise TrustedReportError(f"{field} contains duplicate ids")
    return set(values)


def _period(value: Any, field: str) -> tuple[str, str, str]:
    if not isinstance(value, dict):
        raise TrustedReportError(f"{field} must be an object")
    if set(value) - {"start", "end", "timezone"}:
        raise TrustedReportError(f"{field} contains unsupported fields")
    try:
        start = date.fromisoformat(value["start"])
        end = date.fromisoformat(value["end"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TrustedReportError(
            f"{field} requires valid ISO start and end dates"
        ) from exc
    if start >= end:
        raise TrustedReportError(f"{field} must have start before end")
    timezone_name = value.get("timezone", "UTC")
    if timezone_name != "UTC":
        raise TrustedReportError(f"{field} timezone must be UTC")
    return start.isoformat(), end.isoformat(), timezone_name


def _currency(value: Any, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z]{3}", value):
        raise TrustedReportError(f"{field} must be a three-letter ISO currency")
    return value


def _validate_result(
    document: dict[str, Any], producer: str, run_id: str, mode: str
) -> None:
    if (
        document.get("contract") != CONTRACT
        or document.get("document_type") != "tool_result"
    ):
        raise TrustedReportError(f"{producer} artifact is not a {CONTRACT} tool_result")
    if document.get("producer", {}).get("name") != producer:
        raise TrustedReportError(
            f"artifact declared as {producer} has a different producer identity"
        )
    version = document.get("producer", {}).get("version")
    if not isinstance(version, str) or not SUPPORTED_VERSION.match(version):
        raise TrustedReportError(f"{producer} version is not supported by v0.2")
    if document.get("run_id") != run_id:
        raise TrustedReportError(f"{producer} run_id does not match the manifest")
    if document.get("mode") != mode:
        raise TrustedReportError(f"{producer} mode does not match the manifest")
    if not isinstance(document.get("generated_at"), str):
        raise TrustedReportError(f"{producer} generated_at is required")
    _timestamp(document["generated_at"])
    _period(document.get("period"), f"{producer}.period")
    if document.get("quality", {}).get("status") not in {"valid", "partial"}:
        raise TrustedReportError(f"{producer} result quality is not usable")
    metric_ids = _ids(document.get("metrics"), f"{producer}.metrics")
    finding_ids = _ids(document.get("findings"), f"{producer}.findings")
    opportunity_ids = _ids(document.get("opportunities"), f"{producer}.opportunities")
    evidence_ids = _ids(document.get("evidence"), f"{producer}.evidence")
    source_ids = _ids(document.get("inputs"), f"{producer}.inputs")
    expected_access = (
        "illustrative_fixture" if mode == "illustrative" else "local_read_only"
    )
    expected_classification = (
        "public_illustrative" if mode == "illustrative" else "customer_confidential"
    )
    for source in document["inputs"]:
        if not source.get("source_type") or not source.get("source_version"):
            raise TrustedReportError(f"{source['id']} requires source lineage")
        if source.get("access") != expected_access:
            raise TrustedReportError(
                f"{source['id']} access is incompatible with {mode} mode"
            )
        if source.get("data_classification") != expected_classification:
            raise TrustedReportError(
                f"{source['id']} classification is incompatible with {mode} mode"
            )
        digest = source.get("content_sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise TrustedReportError(f"{source['id']} requires a SHA-256 content hash")
    for evidence in document["evidence"]:
        if not evidence.get("description"):
            raise TrustedReportError(f"{evidence['id']} requires a description")
        if not set(evidence.get("source_ids", [])).issubset(source_ids):
            raise TrustedReportError(
                f"{evidence['id']} has unresolved source references"
            )
    for metric in document["metrics"]:
        value = metric.get("value")
        if value is not None and (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
        ):
            raise TrustedReportError(
                f"{metric['id']} has a non-finite or non-numeric value"
            )
        basis = metric.get("basis")
        if basis == "verified":
            raise TrustedReportError(
                f"{metric['id']} calls a tool-result metric verified"
            )
        if basis not in METRIC_BASES:
            raise TrustedReportError(f"{metric['id']} has an unsupported basis")
        if metric.get("additivity") not in ADDITIVITY:
            raise TrustedReportError(f"{metric['id']} has unsupported additivity")
        if metric.get("quality_status") not in {"valid", "partial", "invalid"}:
            raise TrustedReportError(f"{metric['id']} has invalid quality status")
        _period(metric.get("period"), f"{metric['id']}.period")
        if metric.get("unit") == "currency":
            _currency(metric.get("currency"), f"{metric['id']}.currency")
        if basis in {"calculated", "allocated", "estimated"} and not metric.get(
            "formula"
        ):
            raise TrustedReportError(f"{metric['id']} requires a formula")
        if value is None and (
            metric.get("basis") != "unknown" or not metric.get("unknown_reason")
        ):
            raise TrustedReportError(f"{metric['id']} has an unexplained unknown value")
        if not metric.get("evidence_ids") or not set(
            metric.get("evidence_ids", [])
        ).issubset(evidence_ids):
            raise TrustedReportError(
                f"{metric['id']} has unresolved evidence references"
            )
        if not set(metric.get("input_metric_ids", [])).issubset(metric_ids):
            raise TrustedReportError(f"{metric['id']} has unresolved metric inputs")
    for finding in document["findings"]:
        if (
            not finding.get("metric_ids")
            or not finding.get("evidence_ids")
            or not set(finding.get("metric_ids", [])).issubset(metric_ids)
            or not set(finding.get("evidence_ids", [])).issubset(evidence_ids)
        ):
            raise TrustedReportError(f"{finding['id']} has unresolved references")
    for opportunity in document["opportunities"]:
        if opportunity.get("producer", {}).get("name") != producer:
            raise TrustedReportError(
                f"{opportunity['id']} producer does not match its tool result"
            )
        estimate = opportunity.get("estimate", {})
        values = (estimate.get("low"), estimate.get("expected"), estimate.get("high"))
        if (
            not all(
                isinstance(item, (int, float))
                and not isinstance(item, bool)
                and math.isfinite(item)
                for item in values
            )
            or not values[0] <= values[1] <= values[2]
            or values[0] < 0
        ):
            raise TrustedReportError(
                f"{opportunity['id']} has an invalid estimate range"
            )
        if estimate.get("basis") != "estimated" or not estimate.get("formula"):
            raise TrustedReportError(
                f"{opportunity['id']} must remain a formula-backed estimate"
            )
        if estimate.get("period") not in {"monthly", "annual", "one_time"}:
            raise TrustedReportError(f"{opportunity['id']} has an invalid period")
        _currency(estimate.get("currency"), f"{opportunity['id']}.estimate.currency")
        if opportunity.get("confidence") not in {"low", "medium", "high"}:
            raise TrustedReportError(f"{opportunity['id']} has invalid confidence")
        if opportunity.get("status") not in OPPORTUNITY_STATUSES:
            raise TrustedReportError(f"{opportunity['id']} has invalid status")
        overlap = opportunity.get("overlap", {})
        if overlap.get("disposition") not in {
            "independent",
            "exclusive",
            "nested",
            "potential",
            "none_known",
        } or not overlap.get("reason"):
            raise TrustedReportError(f"{opportunity['id']} has invalid overlap lineage")
        if overlap.get("disposition") != "none_known" and not overlap.get("group_id"):
            raise TrustedReportError(
                f"{opportunity['id']} overlap requires a deterministic group id"
            )
        if opportunity.get("scope", {}).get("classification") == "unattributed_cost":
            raise TrustedReportError(
                f"{opportunity['id']} classifies unattributed cost as an opportunity"
            )
        review = opportunity.get("review", {})
        if not all(
            review.get(key) is True
            for key in (
                "required",
                "approval_required",
                "rollback_plan_required",
                "verification_required",
            )
        ):
            raise TrustedReportError(f"{opportunity['id']} is not review-first")
        if not review.get("non_mutating_review_steps"):
            raise TrustedReportError(
                f"{opportunity['id']} requires non-mutating review steps"
            )
        if any(
            MUTATING_COMMAND.search(step)
            for step in review.get("non_mutating_review_steps", [])
        ):
            raise TrustedReportError(
                f"{opportunity['id']} contains a mutating public review step"
            )
        if (
            not opportunity.get("evidence_ids")
            or not set(opportunity.get("evidence_ids", [])).issubset(evidence_ids)
            or not set(opportunity.get("related_finding_ids", [])).issubset(finding_ids)
            or not set(opportunity.get("related_opportunity_ids", [])).issubset(
                opportunity_ids
            )
        ):
            raise TrustedReportError(f"{opportunity['id']} has unresolved references")


def _select_opportunities(opportunities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in opportunities:
        estimate = item["estimate"]
        grouped[(estimate["period"], estimate["currency"])].append(item)
    aggregates = []
    for (period_name, currency), candidates in sorted(grouped.items()):
        included, excluded = [], []
        included_groups: set[str] = set()
        for item in sorted(candidates, key=lambda row: row["id"]):
            disposition = item.get("overlap", {}).get("disposition")
            group_id = item.get("overlap", {}).get("group_id")
            if (
                disposition in {"independent", "none_known"}
                and item.get("status") in INCLUDED_OPPORTUNITY_STATUSES
                and (not group_id or group_id not in included_groups)
            ):
                included.append(item)
                if group_id:
                    included_groups.add(group_id)
            else:
                excluded.append(item)
        aggregates.append(
            {
                "id": f"aggregate.opportunities.{period_name}.{currency.lower()}",
                "label": f"Overlap-safe {period_name} estimated opportunity range",
                "opportunity_ids": [item["id"] for item in included],
                "excluded_opportunity_ids": [item["id"] for item in excluded],
                "period": period_name,
                "low": round(sum(item["estimate"]["low"] for item in included), 2),
                "expected": round(
                    sum(item["estimate"]["expected"] for item in included), 2
                ),
                "high": round(sum(item["estimate"]["high"] for item in included), 2),
                "currency": currency,
                "inclusion_rule": "Include only identified, under-review, or approved opportunities with independent or none-known overlap disposition, at most once per deterministic overlap group; if a group repeats, the lexicographically first opportunity ID takes precedence. Exclude rejected, closed, implemented-pending-verification, potential, nested, exclusive, and remaining duplicate-group entries; estimates are not verified savings.",
            }
        )
    return aggregates


def build_trusted_report(
    manifest_path: Path,
    *,
    generated_at: str | None = None,
    report_id: str = "report.tech-spend.trusted",
) -> dict[str, Any]:
    manifest, manifest_raw = _load(manifest_path)
    if (
        manifest.get("contract") != CONTRACT
        or manifest.get("document_type") != "pipeline_manifest"
    ):
        raise TrustedReportError(f"manifest must be a {CONTRACT} pipeline_manifest")
    if tuple(manifest.get("required_producers", [])) != REQUIRED_PRODUCERS:
        raise TrustedReportError(
            "manifest required_producers must contain the six canonical producers in order"
        )
    try:
        run_id = str(uuid.UUID(str(manifest.get("run_id"))))
    except (ValueError, TypeError) as exc:
        raise TrustedReportError("manifest run_id must be a UUID") from exc
    mode = manifest.get("mode")
    if mode not in {"illustrative", "real"}:
        raise TrustedReportError("manifest mode must be illustrative or real")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise TrustedReportError("manifest artifacts must be an array")
    base = manifest_path.resolve().parent
    results: dict[str, dict[str, Any]] = {}
    artifact_hashes: dict[str, str] = {}
    seen_manifest_producers: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise TrustedReportError("manifest artifact must be an object")
        producer = artifact.get("producer", {}).get("name")
        if producer not in ANALYTICAL_PRODUCERS:
            raise TrustedReportError(
                f"unsupported manifest artifact producer: {producer}"
            )
        if producer in seen_manifest_producers:
            raise TrustedReportError(f"duplicate manifest artifact for {producer}")
        seen_manifest_producers.add(producer)
        if (
            artifact.get("status") != "produced"
            or artifact.get("contract_valid") is not True
        ):
            raise TrustedReportError(
                f"{producer} artifact must be produced and contract-valid"
            )
        relative = artifact.get("relative_path")
        if (
            not isinstance(relative, str)
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
        ):
            raise TrustedReportError(f"unsafe relative_path for {producer}")
        path = (base / relative).resolve()
        if base not in path.parents:
            raise TrustedReportError(
                f"artifact path escapes manifest directory for {producer}"
            )
        document, raw = _load(path)
        digest = hashlib.sha256(raw).hexdigest()
        if digest != artifact.get("content_sha256"):
            raise TrustedReportError(f"artifact hash mismatch for {producer}")
        _validate_result(document, producer, run_id, mode)
        results[producer] = document
        artifact_hashes[producer] = digest
    if set(results) != set(ANALYTICAL_PRODUCERS) or len(artifacts) != len(
        ANALYTICAL_PRODUCERS
    ):
        missing = sorted(set(ANALYTICAL_PRODUCERS) - set(results))
        raise TrustedReportError(
            f"manifest must contain exactly one produced artifact for each analytical producer; missing={missing}"
        )
    metrics = [
        item
        for name in ANALYTICAL_PRODUCERS
        if name in results
        for item in results[name]["metrics"]
    ]
    findings = [
        item
        for name in ANALYTICAL_PRODUCERS
        if name in results
        for item in results[name]["findings"]
    ]
    opportunities = [
        item
        for name in ANALYTICAL_PRODUCERS
        if name in results
        for item in results[name]["opportunities"]
    ]
    for catalog, label in (
        (metrics, "metric"),
        (findings, "finding"),
        (opportunities, "opportunity"),
    ):
        ids = [item["id"] for item in catalog]
        if len(ids) != len(set(ids)):
            raise TrustedReportError(f"cross-producer duplicate {label} id")
    currencies = {
        item.get("currency") for item in metrics if item.get("currency") is not None
    } | {item["estimate"]["currency"] for item in opportunities}
    if len(currencies) > 1:
        raise TrustedReportError(
            f"producer outputs contain incompatible currencies: {sorted(currencies)}"
        )
    for key, label in (("inputs", "source"), ("evidence", "evidence")):
        all_ids = [
            item["id"] for document in results.values() for item in document[key]
        ]
        if len(all_ids) != len(set(all_ids)):
            raise TrustedReportError(f"cross-producer duplicate {label} id")
    periods = [document["period"] for document in results.values()]
    period = {
        "start": min(item["start"] for item in periods),
        "end": max(item["end"] for item in periods),
        "timezone": "UTC",
    }
    metric_map = {item["id"]: item for item in metrics}
    cloud_total = metric_map.get("metric.cloud.total")
    cloud_services = [
        item
        for item in metrics
        if item["id"].startswith("metric.cloud.service.")
        and item["id"].endswith(".cost")
        and ".day." not in item["id"]
    ]
    if not cloud_total or not cloud_services:
        raise TrustedReportError(
            "FinOps Lite cloud total and complete service metrics are required for report reconciliation"
        )
    if cloud_total.get("additivity") != "additive" or any(
        item.get("additivity") != "additive" for item in cloud_services
    ):
        raise TrustedReportError(
            "FinOps Lite cloud reconciliation requires additive metrics"
        )
    service_sum = round(sum(item["value"] for item in cloud_services), 6)
    if any(item["period"] != cloud_total["period"] for item in cloud_services):
        raise TrustedReportError(
            "FinOps Lite service periods do not match metric.cloud.total"
        )
    if any(
        item.get("currency") != cloud_total.get("currency") for item in cloud_services
    ):
        raise TrustedReportError(
            "FinOps Lite service currencies do not match metric.cloud.total"
        )
    difference = round(service_sum - cloud_total["value"], 6)
    if abs(difference) > 0.01:
        raise TrustedReportError(
            "cloud service metrics do not reconcile to metric.cloud.total"
        )
    reconciliation = [
        {
            "id": "reconciliation.report.cloud-services",
            "assertion": "Complete FinOps Lite service costs sum to the observed cloud total.",
            "input_metric_ids": [item["id"] for item in cloud_services],
            "output_metric_id": "metric.cloud.total",
            "difference": difference,
            "tolerance": 0.01,
            "status": "passed",
        }
    ]
    section_ids: dict[str, list[str]] = defaultdict(list)
    for metric in metrics:
        producer = next(
            name
            for name, document in results.items()
            if any(row["id"] == metric["id"] for row in document["metrics"])
        )
        section_ids[producer].append(metric["id"])
    headline = [
        item
        for item in ("metric.cloud.total", "metric.ai.total-cost")
        if item in metric_map
    ]
    headline.extend(
        item["id"] for item in metrics if item["id"].endswith(".invoice-cost")
    )
    disclosures = [
        "Every displayed number references a canonical producer metric; the Command Center does not invent savings, anomalies, or forecasts.",
        "Metrics with different periods or accounting boundaries are not added into a single technology-spend total.",
        "Opportunity ranges are estimates, not verified savings; potential, nested, and exclusive overlaps are excluded from aggregates.",
        "AI costs with potential cloud-billing overlap and modeled resilience exposure remain non-additive at the executive boundary.",
    ]
    if mode == "illustrative":
        disclosures.insert(
            0,
            "All data in this report is illustrative and does not describe a real customer environment.",
        )
    if any(
        document.get("quality", {}).get("status") == "partial"
        for document in results.values()
    ):
        disclosures.append(
            "One or more producer results are partial; inspect their quality issues before decisions."
        )
    aggregates = _select_opportunities(opportunities)
    producer_quality = [
        {"producer": results[name]["producer"], "quality": results[name]["quality"]}
        for name in ANALYTICAL_PRODUCERS
        if name in results
    ]
    return {
        "contract": CONTRACT,
        "document_type": "trusted_report",
        "producer": {"name": "tech-spend-command-center", "version": __version__},
        "report_id": report_id,
        "run_id": run_id,
        "generated_at": _timestamp(generated_at),
        "mode": mode,
        "status": "complete",
        "period": period,
        "included_producers": [
            results[name]["producer"]
            for name in ANALYTICAL_PRODUCERS
            if name in results
        ],
        "omitted_producers": [],
        "producer_quality": producer_quality,
        "metric_catalog": metrics,
        "finding_catalog": findings,
        "opportunity_catalog": opportunities,
        "opportunity_aggregates": aggregates,
        "display": {
            "headline_metric_ids": headline,
            "section_metric_ids": dict(section_ids),
            "finding_ids": [
                item["id"]
                for item in sorted(
                    findings,
                    key=lambda row: {
                        "critical": 0,
                        "high": 1,
                        "medium": 2,
                        "low": 3,
                        "info": 4,
                    }.get(row.get("severity"), 9),
                )
            ],
            "opportunity_aggregate_ids": [item["id"] for item in aggregates],
            "disclosures": disclosures,
        },
        "reconciliation": reconciliation,
        "provenance": {
            "manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
            "artifact_sha256s": artifact_hashes,
        },
    }
