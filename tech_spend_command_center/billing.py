"""Run and assemble the existing analytical producers for a supplied cloud bill.

This is an explicit partial CCAC 1.1 path. The existing five-producer complete
report policy is unchanged. Missing producers remain omitted, never zero/demo.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from copy import deepcopy
from decimal import Decimal, localcontext
from pathlib import Path

from ccac import validate_run_directory
from finops_lite.billing import build_billing_result
from finops_lite.ccac_json import dumps_exact, loads_exact
from finops_watchdog.billing import build_billing_result as analyze_daily_billing

from . import __version__
from .ccac11 import CONTRACT, VERSIONS, _require_ccac, _unique_catalog
from .trusted import (
    ANALYTICAL_PRODUCERS,
    REQUIRED_PRODUCERS,
    TrustedReportError,
    _timestamp,
)

OMITTED = {
    "recovery-economics": "No resilience design, backup or restore-test evidence was supplied.",
    "ai-cost-lens": "No direct AI-vendor usage or invoices were supplied. Provider-billed AI remains within Cloud.",
    "saas-cost-analyzer": "No separate SaaS invoices, entitlements or seat activity were supplied.",
}


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read(path):
    if path.is_symlink() or path.stat().st_size > 64 * 1024 * 1024:
        raise TrustedReportError("Unsupported artifact path or size.")
    text = path.read_text(encoding="utf-8")
    value = loads_exact(text)
    if not isinstance(value, dict):
        raise TrustedReportError("A canonical artifact must be a JSON object.")
    return value, text


def load_billing_producers(paths):
    if set(paths) != {"finops-lite", "finops-watchdog"}:
        raise TrustedReportError(
            "The billing path requires exactly FinOps Lite and Watchdog artifacts."
        )
    documents, hashes = {}, {}
    identity = None
    for name in ["finops-lite", "finops-watchdog"]:
        document, text = _read(paths[name])
        _require_ccac(document, name)
        if (
            document.get("producer") != {"name": name, "version": VERSIONS[name]}
            or document.get("document_type") != "tool_result"
            or document.get("contract") != CONTRACT
        ):
            raise TrustedReportError("Unsupported billing producer identity.")
        current = (document["run_id"], document["mode"], document["period"])
        if identity is not None and current != identity:
            raise TrustedReportError(
                "Billing producer run, mode or reporting period differs."
            )
        identity = current
        if document["quality"]["status"] not in {"valid", "partial"}:
            raise TrustedReportError("Invalid producer quality cannot enter a report.")
        documents[name] = document
        hashes[name] = digest(text)
    extension = documents["finops-lite"].get("extensions", {}).get("finops_lite", {})
    if extension.get("input_profile") != "billing_csv/1.0":
        raise TrustedReportError(
            "This partial report requires the canonical billing input profile."
        )
    watchdog = documents["finops-watchdog"]
    if (
        watchdog.get("extensions", {}).get("finops_watchdog", {}).get("input_profile")
        != "billing_csv/1.0"
    ):
        raise TrustedReportError("Watchdog did not analyze the billing input profile.")
    if (
        len(watchdog["inputs"]) != 1
        or watchdog["inputs"][0]["content_sha256"] != hashes["finops-lite"]
    ):
        raise TrustedReportError(
            "Watchdog input hash does not match the supplied FinOps Lite artifact."
        )
    for metric in watchdog["metrics"]:
        if (
            metric.get("accounting_boundary") is not None
            or metric.get("metric_role") is not None
        ):
            raise TrustedReportError(
                "Watchdog diagnostics cannot contribute another spend scope."
            )
    return documents, hashes


def build_billing_report(paths, *, generated_at, manifest_sha256):
    documents, hashes = load_billing_producers(paths)
    source = documents["finops-lite"]
    metrics = _unique_catalog(documents, "metrics")
    findings = _unique_catalog(documents, "findings")
    evidence = _unique_catalog(documents, "evidence")
    opportunities = _unique_catalog(documents, "opportunities")
    by_id = {item["id"]: item for item in metrics}
    canonical = [
        item
        for item in metrics
        if item.get("accounting_boundary", {}).get("relationship")
        == "canonical_scope_spend"
    ]
    if (
        len(canonical) != 1
        or canonical[0]["id"] != "metric.tech-spend.scope.cloud"
        or canonical[0]["accounting_boundary"]["canonical_owner"] != "finops-lite"
        or canonical[0]["accounting_boundary"]["cost_basis"] != "billed_cost"
        or canonical[0]["accounting_boundary"]["total_eligible"] is not False
        or canonical[0]["accounting_boundary"]["coverage"] != "partial"
    ):
        raise TrustedReportError(
            "A supplied bill must keep its partial billed-cost Cloud boundary."
        )
    if any(item.get("metric_role") == "technology_spend_total" for item in metrics):
        raise TrustedReportError(
            "A partial cloud bill cannot advertise all-in Technology Spend."
        )
    reconciliations = deepcopy(
        source["extensions"]["finops_lite"]["billing"]["reconciliation"]
    )
    if len(reconciliations) != 1:
        raise TrustedReportError(
            "The supplied Cloud service reconciliation is missing."
        )
    for record in reconciliations:
        refs = record["input_metric_ids"]
        if (
            len(set(refs)) != len(refs)
            or any(ref not in by_id for ref in refs)
            or record["output_metric_id"] != canonical[0]["id"]
        ):
            raise TrustedReportError(
                "Invalid supplied Cloud reconciliation references."
            )
        with localcontext() as context:
            context.prec = 50
            difference = Decimal(str(canonical[0]["value"])) - sum(
                (Decimal(str(by_id[ref]["value"])) for ref in refs), Decimal(0)
            )
        if (
            difference != 0
            or record["difference"] != 0
            or record["tolerance"] != 0
            or record["status"] != "passed"
        ):
            raise TrustedReportError("Supplied service costs do not reconcile exactly.")
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    findings.sort(key=lambda item: order[item["severity"]])
    report = dict(
        contract=CONTRACT,
        document_type="trusted_report",
        producer=dict(name="tech-spend-command-center", version=__version__),
        report_id="report.cloud-bill.trusted",
        run_id=source["run_id"],
        generated_at=_timestamp(generated_at),
        mode=source["mode"],
        status="partial",
        period=deepcopy(source["period"]),
        included_producers=[
            deepcopy(documents[name]["producer"])
            for name in ANALYTICAL_PRODUCERS
            if name in documents
        ],
        omitted_producers=[
            dict(name=name, reason=reason) for name, reason in OMITTED.items()
        ],
        producer_quality=[
            dict(
                producer=deepcopy(documents[name]["producer"]),
                quality=deepcopy(documents[name]["quality"]),
            )
            for name in ANALYTICAL_PRODUCERS
            if name in documents
        ],
        metric_catalog=metrics,
        finding_catalog=findings,
        opportunity_catalog=opportunities,
        opportunity_aggregates=[],
        display=dict(
            headline_metric_ids=[canonical[0]["id"]],
            section_metric_ids={
                name: [item["id"] for item in document["metrics"]]
                for name, document in documents.items()
            },
            finding_ids=[item["id"] for item in findings],
            opportunity_aggregate_ids=[],
            disclosures=[
                (
                    "Illustrative supplied billing data."
                    if source["mode"] == "illustrative"
                    else "This report uses supplied billing CSV records; complete organizational coverage has not been established."
                ),
                "Cloud billed cost includes signed supplied adjustments and provider-billed AI. Other domains require their own evidence.",
                "Watchdog findings are anomaly diagnostics, not savings or a root-cause conclusion.",
                "Partial report: direct-AI, SaaS and resilience evidence were not supplied. No all-in Technology Spend total is published.",
            ],
        ),
        reconciliation=reconciliations,
        provenance=dict(manifest_sha256=manifest_sha256, artifact_sha256s=hashes),
    )
    _require_ccac(report, "partial billing trusted report")
    return report


def _manifest(documents, texts, *, generated_at, report_text=None):
    source = documents["finops-lite"]
    records = []
    for name in ANALYTICAL_PRODUCERS:
        produced = name in documents
        records.append(
            dict(
                producer=dict(name=name, version=VERSIONS[name]),
                document_type="tool_result",
                relative_path=name + ".json",
                content_sha256=digest(texts[name]) if produced else "0" * 64,
                status="produced" if produced else "omitted",
                contract_valid=produced,
                omission_reason=None if produced else OMITTED[name],
            )
        )
    if report_text is not None:
        records.append(
            dict(
                producer=dict(name="tech-spend-command-center", version=__version__),
                document_type="trusted_report",
                relative_path="report.json",
                content_sha256=digest(report_text),
                status="produced",
                contract_valid=True,
                omission_reason=None,
            )
        )
    manifest = dict(
        contract=CONTRACT,
        document_type="pipeline_manifest",
        run_id=source["run_id"],
        mode=source["mode"],
        started_at=generated_at,
        completed_at=generated_at,
        status="partial",
        required_producers=list(REQUIRED_PRODUCERS),
        artifacts=records,
        errors=[],
    )
    _require_ccac(manifest, "partial manifest")
    return manifest


def validate_billing_run(directory):
    directory = Path(directory).resolve()
    manifest, manifest_text = _read(directory / "manifest.json")
    _require_ccac(manifest, "billing manifest")
    if (
        manifest["status"] != "partial"
        or tuple(manifest["required_producers"]) != REQUIRED_PRODUCERS
        or manifest["errors"]
    ):
        raise TrustedReportError("Billing manifest has an invalid completeness claim.")
    records = manifest["artifacts"]
    names = [item["producer"]["name"] for item in records]
    if len(names) != len(set(names)) or set(names) != set(REQUIRED_PRODUCERS):
        raise TrustedReportError("Billing manifest producer inventory is invalid.")
    for item in records:
        name = item["producer"]["name"]
        expected = (
            "report.json" if name == "tech-spend-command-center" else name + ".json"
        )
        if item["relative_path"] != expected or Path(expected).name != expected:
            raise TrustedReportError("Unexpected billing artifact path.")
        if name in OMITTED:
            if (
                item["status"] != "omitted"
                or item["contract_valid"] is not False
                or item.get("omission_reason") != OMITTED[name]
                or (directory / expected).exists()
            ):
                raise TrustedReportError(
                    "Missing domain evidence was substituted or relabeled."
                )
        elif (
            item["status"] != "produced"
            or item["contract_valid"] is not True
            or digest(_read(directory / expected)[1]) != item["content_sha256"]
        ):
            raise TrustedReportError(
                "Billing artifact hash or production status differs."
            )
    source_manifest, source_text = _read(directory / "source-manifest.json")
    report, report_text = _read(directory / "report.json")
    if report["provenance"]["manifest_sha256"] != digest(
        source_text
    ) or source_manifest["artifacts"] != [
        item for item in records if item["document_type"] == "tool_result"
    ]:
        raise TrustedReportError(
            "Partial report does not bind the source artifact manifest."
        )
    for field in [
        "run_id",
        "mode",
        "status",
        "required_producers",
        "started_at",
        "completed_at",
        "errors",
    ]:
        if source_manifest[field] != manifest[field]:
            raise TrustedReportError("Source and final manifest identities differ.")
    _require_ccac(source_manifest, "source manifest")
    issues = validate_run_directory(directory)
    if issues:
        raise TrustedReportError(
            "Released CCAC run validation failed: " + issues[0].message
        )
    paths = {
        name: directory / (name + ".json")
        for name in ["finops-lite", "finops-watchdog"]
    }
    expected = build_billing_report(
        paths, generated_at=report["generated_at"], manifest_sha256=digest(source_text)
    )
    if report != expected:
        raise TrustedReportError(
            "Trusted report differs from its producer-owned metrics and findings."
        )
    return report, manifest


def project_billing_report(report, documents):
    """Read-only view of a validated report; every amount retains its metric ID.

    Decimal values are strings at the presentation boundary. Charts may convert
    them for geometry, but neither the browser nor this projection recalculates
    totals, shares, changes or findings.
    """
    from finops_lite.billing import text_decimal

    layout = documents["finops-lite"]["extensions"]["finops_lite"]["billing"]
    metrics = {item["id"]: item for item in report["metric_catalog"]}

    def value(identifier):
        item = metrics[identifier]
        return (
            None if item["value"] is None else text_decimal(Decimal(str(item["value"])))
        )

    def period(data):
        if data is None:
            return None
        result = deepcopy(data)
        result.update(
            {key: value(identifier) for key, identifier in data["metric_ids"].items()}
        )
        result["services"] = [
            {
                **row,
                **{
                    key: value(identifier)
                    for key, identifier in row["metric_ids"].items()
                },
            }
            for row in data["services"]
        ]
        result["daily"] = [
            {**row, "cost": value(row["metric_id"])} for row in data["daily"]
        ]
        result["chargeChart"] = [
            {**row, "exact": value(row["metric_id"])} for row in data["chargeChart"]
        ]
        if "providerSummaries" in data:
            result["providerSummaries"] = {
                key: period(item) for key, item in data["providerSummaries"].items()
            }
        return result

    comparison = deepcopy(layout["comparison"])
    if comparison:
        comparison.update(
            delta=value(comparison["delta_metric_id"]),
            percent=value(comparison["percent_metric_id"]),
        )
        comparison["drivers"] = [
            {
                **row,
                "current": (
                    value(row["current_metric_id"]) if row["current_metric_id"] else "0"
                ),
                "previous": (
                    value(row["previous_metric_id"])
                    if row["previous_metric_id"]
                    else "0"
                ),
                "delta": value(row["delta_metric_id"]),
            }
            for row in comparison["drivers"]
        ]
    findings = []
    for finding in report["finding_catalog"]:
        parts = layout["finding_templates"].get(finding["id"])
        if parts and any(
            isinstance(part, dict) and part["metric_id"] not in finding["metric_ids"]
            for part in parts
        ):
            raise TrustedReportError(
                "A presentation reference is not grounded in its finding."
            )
        findings.append(
            {
                **deepcopy(finding),
                "text": finding["description"],
                "parts": (
                    [
                        (
                            {**part, "value": value(part["metric_id"])}
                            if isinstance(part, dict)
                            else part
                        )
                        for part in parts
                    ]
                    if parts
                    else None
                ),
                "producer": (
                    "finops-lite"
                    if finding["id"] in layout["finding_templates"]
                    else "finops-watchdog"
                ),
            }
        )
    current = period(layout["current"])
    watchdog = documents["finops-watchdog"]["extensions"]["finops_watchdog"]
    return dict(
        schema="cloud-cost-guard.billing-upload.v1",
        source="uploaded",
        currency=current["currency"],
        current=current,
        previous=period(layout["previous"]),
        comparison=comparison,
        findings=findings,
        largestService=current["services"][0]["service"],
        costBasis="Sum of supplied signed Cost or FOCUS BilledCost values. Negative amounts reduce the total. No conversion, amortization, tax, or credit is inferred or added. This is not a full FOCUS conformance check.",
        privacy="Calculated in this browser by FinOps Lite, Watchdog, and Command Center. Billing files and Lumen questions are not sent to a server or AI service. Data is kept in memory until you clear it, switch to the example, reload, or close this tab.",
        pipeline=dict(
            contract=CONTRACT,
            validator="cloudandcapital-ccac/0.2.0",
            status=report["status"],
            run_id=report["run_id"],
            included_producers=report["included_producers"],
            omitted_producers=report["omitted_producers"],
            reconciliation=report["reconciliation"],
            watchdog=deepcopy(watchdog),
        ),
    )


def run_billing_pipeline(payload):
    """The same callable runs in the CLI, tests and the browser's local worker."""
    generated = _timestamp(payload.get("generated_at"))
    source = build_billing_result(
        payload["current"],
        payload.get("previous", []),
        options=payload.get("options"),
        run_id=payload.get("run_id"),
        generated_at=generated,
        mode=payload.get("mode", "real"),
    )
    watchdog = analyze_daily_billing(source, generated_at=generated)
    documents = {"finops-lite": source, "finops-watchdog": watchdog}
    texts = {name: dumps_exact(document) for name, document in documents.items()}
    with tempfile.TemporaryDirectory(prefix="cloud-cost-guard-") as temporary:
        directory = Path(temporary)
        for name, text in texts.items():
            (directory / (name + ".json")).write_text(text, encoding="utf-8")
        preliminary = dumps_exact(_manifest(documents, texts, generated_at=generated))
        (directory / "source-manifest.json").write_text(preliminary, encoding="utf-8")
        report = build_billing_report(
            {name: directory / (name + ".json") for name in documents},
            generated_at=generated,
            manifest_sha256=digest(preliminary),
        )
        report_text = dumps_exact(report)
        (directory / "report.json").write_text(report_text, encoding="utf-8")
        manifest = _manifest(
            documents, texts, generated_at=generated, report_text=report_text
        )
        (directory / "manifest.json").write_text(
            dumps_exact(manifest), encoding="utf-8"
        )
        validated_report, _ = validate_billing_run(directory)
        presentation = project_billing_report(validated_report, documents)
        files = {
            path.name: path.read_text(encoding="utf-8") for path in directory.iterdir()
        }
    return dict(
        contract=CONTRACT,
        validator="cloudandcapital-ccac/0.2.0",
        status="partial",
        run_id=source["run_id"],
        report_sha256=digest(report_text),
        manifest_sha256=digest(files["manifest.json"]),
        files=files,
        presentation=presentation,
    )


if __name__ == "__main__":
    import sys

    # Standard input is data, never executable Python. Output contains no logs.
    try:
        print(dumps_exact(run_billing_pipeline(loads_exact(sys.stdin.read()))))
    except (ValueError, KeyError, TypeError) as error:
        print(json.dumps(dict(error=str(error))))
        sys.exit(2)
