"""Read-only human-readable rendering of a fully validated pipeline run."""

from __future__ import annotations

import json
import math
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .trusted import ANALYTICAL_PRODUCERS, TrustedReportError, build_trusted_report

MAX_DISPLAY_TEXT = 240


@dataclass(frozen=True)
class ValidatedRun:
    """Canonical report plus validated artifact ownership and paths."""

    directory: Path
    report: dict[str, Any]
    artifact_paths: dict[str, Path]
    metric_producers: dict[str, str]
    finding_producers: dict[str, str]


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
    except FileNotFoundError as exc:
        raise TrustedReportError(f"missing {label}: {path}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TrustedReportError(f"unable to read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise TrustedReportError(f"{label} must contain a JSON object")
    return value


def validate_run_directory(run_directory: Path) -> ValidatedRun:
    """Validate one complete run directory and its stored trusted report."""
    directory = run_directory.resolve()
    if not directory.exists():
        raise TrustedReportError(f"run directory not found: {directory}")
    if not directory.is_dir():
        raise TrustedReportError(f"run path must be a directory: {directory}")

    manifest_path = directory / "manifest.json"
    report_path = directory / "report.json"
    manifest = _read_object(manifest_path, "manifest.json")
    stored_report = _read_object(report_path, "report.json")

    generated_at = stored_report.get("generated_at")
    report_id = stored_report.get("report_id")
    if manifest.get("contract") == "ccac/1.1.0":
        from .ccac11 import validate_complete_run

        rebuilt_report, validated_paths = validate_complete_run(directory)
    else:
        rebuilt_report = build_trusted_report(
            manifest_path, generated_at=generated_at, report_id=report_id
        )
    if stored_report != rebuilt_report:
        raise TrustedReportError(
            "report.json does not correspond exactly to the validated manifest and producer artifacts"
        )

    artifacts = manifest.get("artifacts", [])
    artifact_paths: dict[str, Path] = {}
    metric_producers: dict[str, str] = {}
    finding_producers: dict[str, str] = {}
    expected_json_paths = {manifest_path.resolve(), report_path.resolve()}
    for artifact in artifacts:
        producer = artifact["producer"]["name"]
        path = (directory / artifact["relative_path"]).resolve()
        raw = path.read_bytes()
        if __import__("hashlib").sha256(raw).hexdigest() != artifact["content_sha256"]:
            raise TrustedReportError(f"artifact hash mismatch for {producer}")
        if artifact["document_type"] == "trusted_report":
            expected_json_paths.add(path)
            continue
        artifact_paths[producer] = path
        expected_json_paths.add(path)
        document = _read_object(path, f"{producer} artifact")
        metric_producers.update({item["id"]: producer for item in document["metrics"]})
        finding_producers.update(
            {item["id"]: producer for item in document["findings"]}
        )
    if manifest.get("contract") == "ccac/1.1.0" and artifact_paths != validated_paths:
        raise TrustedReportError("validated run producer path inventory changed")

    actual_json_paths = {path.resolve() for path in directory.rglob("*.json")}
    if actual_json_paths != expected_json_paths:
        missing = sorted(
            str(path.relative_to(directory))
            for path in expected_json_paths - actual_json_paths
        )
        unexpected = sorted(
            str(path.relative_to(directory))
            for path in actual_json_paths - expected_json_paths
        )
        raise TrustedReportError(
            f"run directory JSON artifact set is inconsistent; missing={missing}, unexpected={unexpected}"
        )

    if set(artifact_paths) != set(ANALYTICAL_PRODUCERS):
        raise TrustedReportError(
            "run directory does not contain exactly five canonical producers"
        )
    return ValidatedRun(
        directory=directory,
        report=rebuilt_report,
        artifact_paths=artifact_paths,
        metric_producers=metric_producers,
        finding_producers=finding_producers,
    )


def _safe_text(value: Any, field: str, *, limit: int = MAX_DISPLAY_TEXT) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TrustedReportError(f"{field} must be a nonempty display string")
    if any(unicodedata.category(char) in {"Cc", "Cf"} for char in value):
        raise TrustedReportError(f"{field} contains terminal-control characters")
    text = " ".join(value.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _number(value: Any, field: str) -> str:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
    ):
        raise TrustedReportError(f"{field} must be a finite number")
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.6f}".rstrip("0").rstrip(".")


def _period(value: dict[str, Any]) -> str:
    return f"{value['start']} to {value['end']} ({value.get('timezone', 'UTC')})"


def _metric_value(metric: dict[str, Any]) -> str:
    if metric["value"] is None:
        return f"unknown — {_safe_text(metric['unknown_reason'], metric['id'] + '.unknown_reason')}"
    formatted = _number(metric["value"], metric["id"] + ".value")
    if metric.get("unit") == "currency":
        return f"{metric['currency']} {formatted}"
    unit = _safe_text(metric.get("unit"), metric["id"] + ".unit")
    return f"{formatted} {unit}"


def render_summary(validated: ValidatedRun) -> str:
    """Render deterministic plain text from canonical display selections only."""
    report = validated.report
    if report["contract"] == "ccac/1.1.0":
        metric_map = {item["id"]: item for item in report["metric_catalog"]}
        total = metric_map["metric.tech-spend.total"]
        cloud = metric_map["metric.tech-spend.scope.cloud"]
        direct_ai = metric_map["metric.tech-spend.scope.direct_ai"]
        saas = metric_map["metric.tech-spend.scope.saas"]
        return "\n".join(
            [
                "Cloud & Capital Trusted Report",
                f"Mode: {report['mode'].upper()}",
                (
                    "ILLUSTRATIVE DATA — NO CUSTOMER SYSTEMS OR LIVE ACCOUNTS CONNECTED"
                    if report["mode"] == "illustrative"
                    else "DECLARED PRODUCER DATA"
                ),
                f"Reporting period: {_period(report['period'])}",
                f"Contract: {report['contract']}",
                f"Command Center: {report['producer']['version']}",
                "",
                f"Technology Spend: ${total['value']:,.2f}",
                f"Cloud: ${cloud['value']:,.2f}",
                f"Direct AI: ${direct_ai['value']:,.2f}",
                f"SaaS: ${saas['value']:,.2f}",
                "Displayed currency is rounded for readability; canonical JSON retains exact values and reconciliation.",
                "",
                f"Findings for review: {len(report['finding_catalog'])}",
                f"Opportunities for review: {len(report['opportunity_catalog'])}",
                "Recovery Economics is modeled exposure, not billing or additional spend.",
                "This report is analysis, not verified savings or automated remediation.",
                "Cloud Cost Guard is not connected. Lumen is not grounded in this report.",
                "",
                "The seven JSON files are the canonical machine-readable records.",
                "",
            ]
        )
    lines = [
        "Cloud & Capital Trusted Report",
        f"Mode: {report['mode'].upper()}",
    ]
    if report["mode"] == "illustrative":
        lines.append(
            "ILLUSTRATIVE DATA — NO CUSTOMER SYSTEMS OR LIVE CLOUD ACCOUNTS CONNECTED"
        )
    lines.extend(
        [
            f"Run ID: {report['run_id']}",
            f"Report period: {_period(report['period'])}",
            f"Contract: {report['contract']}",
            f"Command Center: {report['producer']['version']}",
            "",
            "Verification",
            "The run's structure, hashes, references, reconciliation, overlap controls, and lineage were validated.",
            f"Included producers: {len(report['included_producers'])}",
            f"Cataloged metrics: {len(report['metric_catalog'])}",
            f"Displayed findings: {len(report['display']['finding_ids'])}",
            f"Cataloged opportunities: {len(report['opportunity_catalog'])}",
        ]
    )
    quality_by_name = {
        item["producer"]["name"]: item["quality"]["status"]
        for item in report["producer_quality"]
    }
    for producer in report["included_producers"]:
        name = producer["name"]
        lines.append(
            f"- {name} {producer['version']} — quality: {quality_by_name[name]}"
        )

    metric_map = {item["id"]: item for item in report["metric_catalog"]}
    lines.extend(["", "Headline metrics"])
    for metric_id in report["display"]["headline_metric_ids"]:
        metric = metric_map[metric_id]
        lines.extend(
            [
                f"- {_safe_text(metric['name'], metric_id + '.name')}: {_metric_value(metric)}",
                f"  period: {_period(metric['period'])}; basis: {metric['basis']}; producer: {validated.metric_producers[metric_id]}; quality: {metric['quality_status']}",
            ]
        )
    lines.append("No total technology-spend figure is created.")

    finding_map = {item["id"]: item for item in report["finding_catalog"]}
    selected_findings = [finding_map[item] for item in report["display"]["finding_ids"]]
    lines.extend(["", "Findings"])
    counts: dict[tuple[str, str], int] = {}
    for finding in selected_findings:
        key = (validated.finding_producers[finding["id"]], finding["finding_type"])
        counts[key] = counts.get(key, 0) + 1
    for (producer, finding_type), count in sorted(counts.items()):
        lines.append(
            f"- {producer} / {_safe_text(finding_type, 'finding_type')}: {count}"
        )
    for finding in selected_findings:
        producer = validated.finding_producers[finding["id"]]
        finding_type = _safe_text(
            finding["finding_type"], finding["id"] + ".finding_type"
        )
        status = _safe_text(finding["status"], finding["id"] + ".status")
        severity = (
            f"; severity: {_safe_text(finding['severity'], finding['id'] + '.severity')}"
            if finding.get("severity")
            else ""
        )
        lines.extend(
            [
                f"- [{producer} / {finding_type}] {_safe_text(finding['title'], finding['id'] + '.title')}",
                f"  status: {status}{severity}",
                f"  context: {_safe_text(finding['description'], finding['id'] + '.description')}",
            ]
        )

    opportunity_map = {item["id"]: item for item in report["opportunity_catalog"]}
    aggregate_map = {item["id"]: item for item in report["opportunity_aggregates"]}
    lines.extend(["", "Opportunities"])
    for aggregate_id in report["display"]["opportunity_aggregate_ids"]:
        aggregate = aggregate_map[aggregate_id]
        lines.append(
            f"- {_safe_text(aggregate['label'], aggregate_id + '.label')}: {aggregate['currency']} {_number(aggregate['low'], aggregate_id + '.low')}–{_number(aggregate['high'], aggregate_id + '.high')} ({aggregate['period']})"
        )
        for opportunity_id in aggregate["opportunity_ids"]:
            opportunity = opportunity_map[opportunity_id]
            estimate = opportunity["estimate"]
            review = opportunity["review"]
            lines.extend(
                [
                    f"  - {_safe_text(opportunity['title'], opportunity_id + '.title')}",
                    f"    status: {opportunity['status']}; confidence: {opportunity['confidence']}; basis: {estimate['basis']}",
                    f"    declared range: {estimate['currency']} {_number(estimate['low'], opportunity_id + '.low')}–{_number(estimate['high'], opportunity_id + '.high')} ({estimate['period']})",
                    "    not realized savings; not verified savings",
                    f"    human review: {'required' if review['required'] else 'not required'}; approval: {'required' if review['approval_required'] else 'not required'}; rollback plan: {'required' if review['rollback_plan_required'] else 'not required'}; later verification: {'required' if review['verification_required'] else 'not required'}",
                ]
            )
            lines.append("    review steps:")
            for index, step in enumerate(review["non_mutating_review_steps"], 1):
                lines.append(
                    f"    {index}. {_safe_text(step, opportunity_id + '.review_step')}"
                )
    if not report["display"]["opportunity_aggregate_ids"]:
        lines.append("- No canonical opportunity aggregates selected for display.")
    lines.append("Excluded or overlapping opportunities are not presented as additive.")

    lines.extend(
        [
            "",
            "Trust boundaries",
            "- Unlike periods, currencies, bases, additivity, and accounting boundaries are not combined.",
            "- Anomaly impact is not savings.",
            "- Modeled resilience exposure is not an invoice or proof of recoverability.",
            "- Potentially overlapping cloud and AI costs are not double-counted.",
            "- Opportunities are estimates requiring human review, approval, rollback planning, and later verification.",
            "- No resources were changed. Cloud Cost Guard is not connected.",
            "",
            "Traceability",
            "- report: report.json",
            "- manifest: manifest.json",
        ]
    )
    for producer in ANALYTICAL_PRODUCERS:
        relative = validated.artifact_paths[producer].relative_to(validated.directory)
        lines.append(f"- {producer}: {relative.as_posix()}")
    lines.append(
        "The JSON files are the canonical machine-readable records; this summary is only a read-only human-readable view."
    )
    return "\n".join(lines) + "\n"


def summarize_run(run_directory: Path) -> str:
    """Validate a complete run directory and render its human-readable view."""
    return render_summary(validate_run_directory(run_directory))
