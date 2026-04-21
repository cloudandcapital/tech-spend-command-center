"""Parse JSON and CSV outputs from each tool in the FinOps pipeline."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------

@dataclass
class CloudData:
    total_cost: float
    trend_direction: Optional[str] = None
    change_percentage: Optional[float] = None
    change_amount: Optional[float] = None
    service_breakdown: List[Dict[str, Any]] = field(default_factory=list)
    period_label: Optional[str] = None
    currency: str = "USD"


@dataclass
class Anomaly:
    service: str
    severity: str
    message: str
    scope: str = "cloud"


@dataclass
class WatchdogData:
    anomalies: List[Anomaly] = field(default_factory=list)
    total_anomalies: int = 0


@dataclass
class ResilienceData:
    total_monthly_resilience_cost: float = 0.0
    scenario_name: Optional[str] = None
    currency: str = "USD"


@dataclass
class AiRow:
    key: str
    cost: float
    provider: str = ""


@dataclass
class AiData:
    total_cost: float = 0.0
    rows: List[AiRow] = field(default_factory=list)
    schema_version: str = "1.0"


@dataclass
class SaasRow:
    key: str
    cost: float


@dataclass
class SaasData:
    total_cost: float = 0.0
    rows: List[SaasRow] = field(default_factory=list)
    schema_version: str = "1.0"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> Dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Cloud (FinOps Lite)
# ---------------------------------------------------------------------------

def parse_cloud(path: Path) -> CloudData:
    """Parse FinOps Lite JSON output."""
    data = _load_json(path)
    trend = data.get("trend") or {}
    window = data.get("window") or {}
    breakdown_raw = data.get("service_breakdown") or []
    breakdown = []
    for item in breakdown_raw:
        if isinstance(item, dict):
            breakdown.append({
                "service_name": item.get("service_name", ""),
                "total_cost": _safe_float(item.get("total_cost")),
                "percentage_of_total": _safe_float(item.get("percentage_of_total")),
            })
    return CloudData(
        total_cost=_safe_float(data.get("total_cost")),
        trend_direction=trend.get("trend_direction"),
        change_percentage=_safe_float(trend.get("change_percentage")) if trend.get("change_percentage") is not None else None,
        change_amount=_safe_float(trend.get("change_amount")) if trend.get("change_amount") is not None else None,
        service_breakdown=breakdown,
        period_label=window.get("label"),
        currency=data.get("currency", "USD"),
    )


# ---------------------------------------------------------------------------
# Watchdog (FinOps Watchdog)
# ---------------------------------------------------------------------------

def parse_watchdog(path: Path) -> WatchdogData:
    """Parse FinOps Watchdog JSON output."""
    data = _load_json(path)
    raw_anomalies = data.get("anomalies") or []
    anomalies: List[Anomaly] = []
    for item in raw_anomalies:
        if not isinstance(item, dict):
            continue
        anomalies.append(Anomaly(
            service=item.get("service", "Unknown"),
            severity=item.get("severity", "info"),
            message=item.get("message", ""),
            scope="cloud",
        ))
    return WatchdogData(
        anomalies=anomalies,
        total_anomalies=len(anomalies),
    )


# ---------------------------------------------------------------------------
# Resilience (Recovery Economics)
# ---------------------------------------------------------------------------

def parse_resilience(path: Path) -> ResilienceData:
    """Parse Recovery Economics JSON or CSV output."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return _parse_resilience_csv(path)
    return _parse_resilience_json(path)


def _parse_resilience_json(path: Path) -> ResilienceData:
    data = _load_json(path)
    return ResilienceData(
        total_monthly_resilience_cost=_safe_float(data.get("total_monthly_resilience_cost")),
        scenario_name=data.get("scenario_name"),
        currency=data.get("currency", "USD"),
    )


def _parse_resilience_csv(path: Path) -> ResilienceData:
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
    if not rows:
        return ResilienceData()
    row = rows[0]
    return ResilienceData(
        total_monthly_resilience_cost=_safe_float(row.get("total_monthly_resilience_cost")),
        scenario_name=row.get("scenario_name"),
        currency=row.get("currency", "USD"),
    )


# ---------------------------------------------------------------------------
# AI (AI Cost Lens)
# ---------------------------------------------------------------------------

def parse_ai(path: Path) -> AiData:
    """Parse AI Cost Lens JSON output."""
    data = _load_json(path)
    raw_rows = data.get("rows") or []
    rows: List[AiRow] = []
    for item in raw_rows:
        if not isinstance(item, dict):
            continue
        rows.append(AiRow(
            key=item.get("key", ""),
            cost=_safe_float(item.get("cost")),
            provider=item.get("provider", ""),
        ))
    return AiData(
        total_cost=_safe_float(data.get("total_cost")),
        rows=rows,
        schema_version=data.get("schema_version", "1.0"),
    )


# ---------------------------------------------------------------------------
# SaaS (SaaS Cost Analyzer)
# ---------------------------------------------------------------------------

def parse_saas(path: Path) -> SaasData:
    """Parse SaaS Cost Analyzer JSON output."""
    data = _load_json(path)
    raw_rows = data.get("rows") or []
    rows: List[SaasRow] = []
    for item in raw_rows:
        if not isinstance(item, dict):
            continue
        rows.append(SaasRow(
            key=item.get("key", ""),
            cost=_safe_float(item.get("cost")),
        ))
    return SaasData(
        total_cost=_safe_float(data.get("total_cost")),
        rows=rows,
        schema_version=data.get("schema_version", "1.0"),
    )
