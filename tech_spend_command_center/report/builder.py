"""Assemble ReportData from parsed inputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from ..parsers.inputs import (
    AiData,
    Anomaly,
    CloudData,
    ResilienceData,
    SaasData,
    WatchdogData,
)

RISK_THRESHOLD_PCT = 20.0


# ---------------------------------------------------------------------------
# ReportData — the canonical intermediate representation
# ---------------------------------------------------------------------------


@dataclass
class SpendRow:
    scope: str
    current: float
    prior: Optional[float] = None
    delta_pct: Optional[float] = None
    delta_amount: Optional[float] = None
    currency: str = "USD"


@dataclass
class OptimizationItem:
    scope: str
    description: str
    estimated_savings: Optional[float] = None


@dataclass
class RiskFlag:
    scope: str
    change_pct: float
    message: str


@dataclass
class ReportData:
    spend_rows: List[SpendRow] = field(default_factory=list)
    anomalies: List[Anomaly] = field(default_factory=list)
    optimization_items: List[OptimizationItem] = field(default_factory=list)
    resilience_cost: Optional[float] = None
    resilience_scenario: Optional[str] = None
    risk_flags: List[RiskFlag] = field(default_factory=list)
    period_label: Optional[str] = None
    currency: str = "USD"

    @property
    def total_spend(self) -> None:
        """Legacy scope summaries lack the boundaries required for a safe total."""
        return None

    @property
    def total_prior_spend(self) -> None:
        """Prior values also remain separate because scopes may not be comparable."""
        return None

    @property
    def forecast_next_month(self) -> None:
        """Legacy inputs do not contain enough evidence for a trustworthy forecast."""
        return None


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_report(
    cloud: Optional[CloudData] = None,
    watchdog: Optional[WatchdogData] = None,
    resilience: Optional[ResilienceData] = None,
    ai: Optional[AiData] = None,
    saas: Optional[SaasData] = None,
) -> ReportData:
    report = ReportData()

    # --- Spend rows ---
    if cloud is not None:
        prior = None
        delta_pct = cloud.change_percentage
        delta_amount = cloud.change_amount
        # Reconstruct prior from delta_amount if available
        if delta_amount is not None and cloud.total_cost is not None:
            prior = cloud.total_cost - delta_amount
        report.spend_rows.append(
            SpendRow(
                scope="Cloud",
                current=cloud.total_cost,
                prior=prior,
                delta_pct=delta_pct,
                delta_amount=delta_amount,
                currency=cloud.currency,
            )
        )
        if cloud.period_label:
            report.period_label = cloud.period_label
        report.currency = cloud.currency

    if ai is not None:
        report.spend_rows.append(
            SpendRow(
                scope="AI",
                current=ai.total_cost,
            )
        )

    if saas is not None:
        report.spend_rows.append(
            SpendRow(
                scope="SaaS",
                current=saas.total_cost,
            )
        )

    # --- Anomalies (up to 5) ---
    all_anomalies: List[Anomaly] = []
    if watchdog is not None:
        all_anomalies.extend(watchdog.anomalies)
    # Sort by severity: high → medium → low → info
    severity_order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    all_anomalies.sort(key=lambda a: severity_order.get(a.severity.lower(), 9))
    report.anomalies = all_anomalies[:5]

    # --- Optimization opportunities (up to 3) ---
    # Legacy summaries contain costs, not canonical opportunity evidence.
    # Recommendations are emitted only by upstream CCAC producers.
    report.optimization_items = []

    # --- Resilience cost ---
    if resilience is not None:
        report.resilience_cost = resilience.total_monthly_resilience_cost
        report.resilience_scenario = resilience.scenario_name

    # --- Risk flags ---
    for row in report.spend_rows:
        if row.delta_pct is not None and row.delta_pct > RISK_THRESHOLD_PCT:
            report.risk_flags.append(
                RiskFlag(
                    scope=row.scope,
                    change_pct=row.delta_pct,
                    message=(
                        f"{row.scope} spend increased {row.delta_pct:.1f}% month-over-month "
                        f"(+${row.delta_amount:,.2f})"
                        if row.delta_amount
                        else f"{row.scope} spend increased {row.delta_pct:.1f}% month-over-month"
                    ),
                )
            )

    return report
