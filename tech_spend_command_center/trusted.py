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
ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[._:-][a-z0-9]+)*$")
MAX_PRODUCER_VERSION_LENGTH = 64
BARE_RELEASE_VERSION = re.compile(
    r"(?:0|[1-9][0-9]*)\." r"(?:0|[1-9][0-9]*)\." r"(?:0|[1-9][0-9]*)"
)
PRODUCER_VERSION_POLICY = {
    "finops-lite": ((0, 3, 0), (0, 4, 0)),
    "finops-watchdog": ((0, 4, 0), (0, 5, 0)),
    "recovery-economics": ((0, 2, 0), (0, 3, 0)),
    "ai-cost-lens": ((0, 2, 0), (0, 3, 0)),
    "saas-cost-analyzer": ((0, 2, 0), (0, 3, 0)),
}
RFC3339_PATTERN = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})"
)
COMMAND_MUTATION_PATTERNS = (
    re.compile(
        r"\baws\s+(?:[a-z0-9_-]+\s+){0,4}(?:delete(?:-[a-z0-9_-]+)?|terminate(?:-[a-z0-9_-]+)?|stop(?:-[a-z0-9_-]+)?|modify(?:-[a-z0-9_-]+)?|rm)\b",
        re.I,
    ),
    re.compile(
        r"\baz\s+(?:[a-z0-9_-]+\s+){0,4}(?:delete|update|create|stop|deallocate)\b",
        re.I,
    ),
    re.compile(
        r"\bgcloud\s+(?:[a-z0-9_-]+\s+){0,5}(?:delete|update|create|start|stop)\b",
        re.I,
    ),
    re.compile(
        r"\bkubectl\s+(?:--?\S+\s+)*(?:apply|delete|patch|scale|replace)\b", re.I
    ),
    re.compile(r"\bterraform\s+(?:apply|destroy)\b", re.I),
    re.compile(
        r"\bcurl\b[^\n]*(?:-X|--request)\s*(?:POST|PUT|PATCH|DELETE)\b",
        re.I,
    ),
    re.compile(r"\bhttp(?:ie)?\s+(?:POST|PUT|PATCH|DELETE)\s+https?://\S+", re.I),
    re.compile(r"\b(?:POST|PUT|PATCH|DELETE)\s+https?://\S+", re.I),
)
REVIEW_MUTATION_INSTRUCTION = re.compile(
    r"(?:^|[,;:]\s*|\b(?:and\s+)?then\s+)(?:please\s+)?(?:delete|terminate|stop|modify|update|create|apply|remove|destroy|cancel|revoke|resize|scale|replace|deallocate)\b",
    re.I,
)
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


def _timestamp(value: str | None, field: str = "generated_at") -> str:
    if value is None:
        return (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
    if not isinstance(value, str) or not RFC3339_PATTERN.fullmatch(value):
        raise TrustedReportError(f"{field} must be timezone-aware RFC3339")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise TrustedReportError(f"{field} must be timezone-aware RFC3339") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TrustedReportError(f"{field} must be timezone-aware RFC3339")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _ids(items: Any, field: str) -> set[str]:
    if not isinstance(items, list):
        raise TrustedReportError(f"{field} must be an array")
    values = []
    for index, item in enumerate(items):
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("id"), str)
            or not item["id"]
            or not _valid_id(item["id"])
        ):
            raise TrustedReportError(f"{field}[{index}] requires an id")
        values.append(item["id"])
    if len(values) != len(set(values)):
        raise TrustedReportError(f"{field} contains duplicate ids")
    return set(values)


def _valid_id(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= 160
        and bool(ID_PATTERN.fullmatch(value))
    )


def _reference_ids(
    value: Any, field: str, known_ids: set[str], *, nonempty: bool = False
) -> list[str]:
    if not isinstance(value, list):
        raise TrustedReportError(f"{field} must be an array of canonical ids")
    if nonempty and not value:
        raise TrustedReportError(f"{field} must be a nonempty array of canonical ids")
    if any(not _valid_id(item) for item in value):
        raise TrustedReportError(f"{field} must contain only canonical ids")
    if len(value) != len(set(value)):
        raise TrustedReportError(f"{field} must not contain duplicate ids")
    if not set(value).issubset(known_ids):
        raise TrustedReportError(f"{field} contains unresolved references")
    return value


def _review_steps(value: Any, field: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(step, str) or not step.strip() for step in value)
    ):
        raise TrustedReportError(
            f"{field} must be a nonempty array of nonempty strings"
        )
    return value


def _producer(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TrustedReportError(f"{field} must be an object")
    if set(value) - {"name", "version", "commit"}:
        raise TrustedReportError(f"{field} contains unsupported fields")
    if not isinstance(value.get("name"), str) or not isinstance(
        value.get("version"), str
    ):
        raise TrustedReportError(f"{field} requires name and version strings")
    commit = value.get("commit")
    if commit is not None and (
        not isinstance(commit, str) or not re.fullmatch(r"[a-f0-9]{7,40}", commit)
    ):
        raise TrustedReportError(f"{field}.commit is invalid")
    return value


def _supported_producer_version(producer: str, version: str) -> bool:
    """Check a canonical bare MAJOR.MINOR.PATCH release against policy."""
    if len(version) > MAX_PRODUCER_VERSION_LENGTH or not BARE_RELEASE_VERSION.fullmatch(
        version
    ):
        return False
    bounds = PRODUCER_VERSION_POLICY.get(producer)
    if bounds is None:
        return False
    try:
        parsed = tuple(int(part) for part in version.split("."))
    except (ValueError, OverflowError):
        return False
    minimum, maximum = bounds
    return minimum <= parsed < maximum


def _validate_present_currencies(value: Any, field: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "currency" and item is not None:
                _currency(item, f"{field}.currency")
            else:
                _validate_present_currencies(item, f"{field}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _validate_present_currencies(item, f"{field}[{index}]")


def _contains_mutating_command(value: Any) -> bool:
    if isinstance(value, str):
        return any(pattern.search(value) for pattern in COMMAND_MUTATION_PATTERNS)
    if isinstance(value, dict):
        return any(_contains_mutating_command(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_mutating_command(item) for item in value)
    return False


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
    producer_value = _producer(document.get("producer"), f"{producer}.producer")
    if producer_value["name"] != producer:
        raise TrustedReportError(
            f"artifact declared as {producer} has a different producer identity"
        )
    version = producer_value["version"]
    if not _supported_producer_version(producer, version):
        raise TrustedReportError(
            f"{producer} version is unsupported by the current Tech Spend Command Center release"
        )
    if document.get("run_id") != run_id:
        raise TrustedReportError(f"{producer} run_id does not match the manifest")
    if document.get("mode") != mode:
        raise TrustedReportError(f"{producer} mode does not match the manifest")
    if not isinstance(document.get("generated_at"), str):
        raise TrustedReportError(f"{producer} generated_at is required")
    _timestamp(document["generated_at"], f"{producer}.generated_at")
    _period(document.get("period"), f"{producer}.period")
    _validate_present_currencies(document, producer)
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
        _reference_ids(
            evidence.get("source_ids"),
            f"{evidence['id']}.source_ids",
            source_ids,
            nonempty=True,
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
        _reference_ids(
            metric.get("evidence_ids"),
            f"{metric['id']}.evidence_ids",
            evidence_ids,
            nonempty=True,
        )
        _reference_ids(
            metric.get("input_metric_ids"),
            f"{metric['id']}.input_metric_ids",
            metric_ids,
        )
    for finding in document["findings"]:
        _reference_ids(
            finding.get("metric_ids"),
            f"{finding['id']}.metric_ids",
            metric_ids,
            nonempty=True,
        )
        _reference_ids(
            finding.get("evidence_ids"),
            f"{finding['id']}.evidence_ids",
            evidence_ids,
            nonempty=True,
        )
        if mode == "illustrative" and _contains_mutating_command(finding):
            raise TrustedReportError(
                f"{finding['id']} contains a mutating public command"
            )
    for opportunity in document["opportunities"]:
        opportunity_producer = _producer(
            opportunity.get("producer"), f"{opportunity['id']}.producer"
        )
        if opportunity_producer["name"] != producer:
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
        if overlap.get("group_id") is not None and not _valid_id(
            overlap.get("group_id")
        ):
            raise TrustedReportError(
                f"{opportunity['id']} overlap group_id must be a canonical CCAC id"
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
        review_steps = _review_steps(
            review.get("non_mutating_review_steps"),
            f"{opportunity['id']}.review.non_mutating_review_steps",
        )
        if any(
            REVIEW_MUTATION_INSTRUCTION.search(step) or _contains_mutating_command(step)
            for step in review_steps
        ):
            raise TrustedReportError(
                f"{opportunity['id']} contains a mutating public review step"
            )
        _reference_ids(
            opportunity.get("evidence_ids"),
            f"{opportunity['id']}.evidence_ids",
            evidence_ids,
            nonempty=True,
        )
        _reference_ids(
            opportunity.get("related_finding_ids"),
            f"{opportunity['id']}.related_finding_ids",
            finding_ids,
        )
        _reference_ids(
            opportunity.get("related_opportunity_ids"),
            f"{opportunity['id']}.related_opportunity_ids",
            opportunity_ids,
        )
        if mode == "illustrative" and _contains_mutating_command(opportunity):
            raise TrustedReportError(
                f"{opportunity['id']} contains a mutating public command"
            )


def _select_opportunities(
    opportunities: list[dict[str, Any]], *, trust_excluded_ids: set[str]
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    eligible_group_counts: dict[str, int] = defaultdict(int)
    for item in opportunities:
        estimate = item["estimate"]
        grouped[(estimate["period"], estimate["currency"])].append(item)
        disposition = item.get("overlap", {}).get("disposition")
        group_id = item.get("overlap", {}).get("group_id")
        if (
            disposition in {"independent", "none_known"}
            and item.get("status") in INCLUDED_OPPORTUNITY_STATUSES
            and group_id
        ):
            eligible_group_counts[group_id] += 1
    aggregates = []
    for (period_name, currency), candidates in sorted(grouped.items()):
        included, excluded = [], []
        for item in sorted(candidates, key=lambda row: row["id"]):
            disposition = item.get("overlap", {}).get("disposition")
            group_id = item.get("overlap", {}).get("group_id")
            if (
                disposition in {"independent", "none_known"}
                and item.get("status") in INCLUDED_OPPORTUNITY_STATUSES
                and item["id"] not in trust_excluded_ids
                and (not group_id or eligible_group_counts[group_id] == 1)
            ):
                included.append(item)
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
                "inclusion_rule": "Include only identified, under-review, or approved opportunities with independent or none-known overlap disposition whose deterministic overlap group appears exactly once across the complete opportunity catalog. Exclude every candidate in repeated groups because v0.2 has no canonical selection or precedence mechanism, and exclude opportunities related to invalid-metric findings; also exclude rejected, closed, implemented-pending-verification, potential, nested, and exclusive entries. All candidates remain cataloged and estimates are not verified savings.",
            }
        )
    return aggregates


def build_trusted_report(
    manifest_path: Path,
    *,
    generated_at: str | None = None,
    report_id: str = "report.tech-spend.trusted",
) -> dict[str, Any]:
    if not _valid_id(report_id):
        raise TrustedReportError("report_id must be a canonical CCAC id")
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
    if manifest.get("status") != "complete":
        raise TrustedReportError("manifest status must be complete")
    if manifest.get("errors") != []:
        raise TrustedReportError("manifest errors must be an empty array")
    if not isinstance(manifest.get("started_at"), str) or not isinstance(
        manifest.get("completed_at"), str
    ):
        raise TrustedReportError(
            "manifest started_at and completed_at must be timezone-aware RFC3339"
        )
    started_at = _timestamp(manifest["started_at"], "manifest.started_at")
    completed_at = _timestamp(manifest["completed_at"], "manifest.completed_at")
    started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    completed = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
    if completed < started:
        raise TrustedReportError("manifest completed_at cannot be before started_at")
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
        allowed_artifact_fields = {
            "producer",
            "document_type",
            "relative_path",
            "content_sha256",
            "status",
            "contract_valid",
            "omission_reason",
        }
        required_artifact_fields = allowed_artifact_fields - {"omission_reason"}
        if set(
            artifact
        ) - allowed_artifact_fields or not required_artifact_fields.issubset(artifact):
            raise TrustedReportError(
                "manifest artifact metadata is structurally invalid"
            )
        artifact_producer = _producer(
            artifact.get("producer"), "manifest artifact producer"
        )
        producer = artifact_producer["name"]
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
        if artifact.get("document_type") != "tool_result":
            raise TrustedReportError(
                f"{producer} manifest artifact document_type must be tool_result"
            )
        digest_value = artifact.get("content_sha256")
        if not isinstance(digest_value, str) or not re.fullmatch(
            r"[a-f0-9]{64}", digest_value
        ):
            raise TrustedReportError(f"{producer} artifact content_sha256 is invalid")
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
        if digest != digest_value:
            raise TrustedReportError(f"artifact hash mismatch for {producer}")
        _validate_result(document, producer, run_id, mode)
        document_producer = _producer(document.get("producer"), f"{producer}.producer")
        if artifact_producer["version"] != document_producer["version"]:
            raise TrustedReportError(
                f"{producer} manifest and document producer versions do not match"
            )
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
    valid_metric_map = {
        item["id"]: item for item in metrics if item.get("quality_status") != "invalid"
    }
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
    if cloud_total.get("quality_status") == "invalid":
        raise TrustedReportError("metric.cloud.total is invalid and cannot be trusted")
    if any(item.get("quality_status") == "invalid" for item in cloud_services):
        raise TrustedReportError(
            "an invalid cloud service metric cannot be used for reconciliation"
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
    for metric in valid_metric_map.values():
        producer = next(
            name
            for name, document in results.items()
            if any(row["id"] == metric["id"] for row in document["metrics"])
        )
        section_ids[producer].append(metric["id"])
    headline = [
        item
        for item in ("metric.cloud.total", "metric.ai.total-cost")
        if item in valid_metric_map
    ]
    headline.extend(
        item["id"]
        for item in valid_metric_map.values()
        if item["id"].endswith(".invoice-cost")
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
    if len(valid_metric_map) != len(metric_map):
        disclosures.append(
            "Invalid producer metrics remain in the catalog for audit only and are excluded from headlines, displayed sections, aggregates, and reconciliation."
        )
    invalid_metric_ids = set(metric_map) - set(valid_metric_map)
    invalid_metric_finding_ids = {
        item["id"]
        for item in findings
        if set(item["metric_ids"]).intersection(invalid_metric_ids)
    }
    invalid_lineage_opportunity_ids = {
        item["id"]
        for item in opportunities
        if set(item["related_finding_ids"]).intersection(invalid_metric_finding_ids)
    }
    if invalid_metric_finding_ids or invalid_lineage_opportunity_ids:
        disclosures.append(
            "Findings that reference invalid metrics remain audit-only and are excluded from display; related opportunities are excluded from aggregates under the conservative v0.2 lineage rule."
        )
    aggregates = _select_opportunities(
        opportunities, trust_excluded_ids=invalid_lineage_opportunity_ids
    )
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
                    (
                        item
                        for item in findings
                        if item["id"] not in invalid_metric_finding_ids
                    ),
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
