"""Assemble ReportData from parsed inputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..parsers.inputs import AiData, CloudData, ResilienceData, SaasData, WatchdogData, Anomaly

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
    def total_spend(self) -> float:
        return sum(row.current for row in self.spend_rows)

    @property
    def total_prior_spend(self) -> Optional[float]:
        priors = [row.prior for row in self.spend_rows if row.prior is not None]
        return sum(priors) if priors else None

    @property
    def forecast_next_month(self) -> float:
        """Simple linear forecast: apply weighted average growth to total spend."""
        total = self.total_spend
        if total == 0:
            return 0.0
        # Collect weighted change percentages
        weighted_sum = 0.0
        weighted_count = 0.0
        for row in self.spend_rows:
            if row.delta_pct is not None:
                weighted_sum += row.delta_pct * row.current
                weighted_count += row.current
        if weighted_count > 0:
            avg_growth_pct = weighted_sum / weighted_count
        else:
            avg_growth_pct = 0.0
        return round(total * (1 + avg_growth_pct / 100), 2)


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
        report.spend_rows.append(SpendRow(
            scope="Cloud",
            current=cloud.total_cost,
            prior=prior,
            delta_pct=delta_pct,
            delta_amount=delta_amount,
            currency=cloud.currency,
        ))
        if cloud.period_label:
            report.period_label = cloud.period_label
        report.currency = cloud.currency

    if ai is not None:
        report.spend_rows.append(SpendRow(
            scope="AI",
            current=ai.total_cost,
        ))

    if saas is not None:
        report.spend_rows.append(SpendRow(
            scope="SaaS",
            current=saas.total_cost,
        ))

    # --- Anomalies (up to 5) ---
    all_anomalies: List[Anomaly] = []
    if watchdog is not None:
        all_anomalies.extend(watchdog.anomalies)
    if ai is not None:
        # Surface top AI rows with high cost as informal anomaly signals
        sorted_ai = sorted(ai.rows, key=lambda r: r.cost, reverse=True)
        for row in sorted_ai[:2]:
            if row.cost > 100:
                from ..parsers.inputs import Anomaly as AnomalyType
                all_anomalies.append(AnomalyType(
                    service=row.key,
                    severity="info",
                    message=f"Top AI spend: ${row.cost:,.2f} ({row.provider})",
                    scope="ai",
                ))
    # Sort by severity: high → medium → low → info
    severity_order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    all_anomalies.sort(key=lambda a: severity_order.get(a.severity.lower(), 9))
    report.anomalies = all_anomalies[:5]

    # --- Optimization opportunities (up to 3) ---
    opts: List[OptimizationItem] = []
    if cloud is not None and cloud.service_breakdown:
        top_service = cloud.service_breakdown[0]
        opts.append(OptimizationItem(
            scope="Cloud",
            description=(
                f"Review rightsizing for {top_service['service_name']} "
                f"(${top_service['total_cost']:,.2f}, "
                f"{top_service.get('percentage_of_total', 0):.1f}% of cloud spend)"
            ),
        ))
    if saas is not None and saas.rows:
        top_saas = saas.rows[0]
        opts.append(OptimizationItem(
            scope="SaaS",
            description=(
                f"Audit license utilization for {top_saas.key} "
                f"(${top_saas.cost:,.2f}/mo) — check for unused seats"
            ),
            estimated_savings=round(top_saas.cost * 0.15, 2),
        ))
    if ai is not None and ai.rows:
        top_ai = ai.rows[0]
        opts.append(OptimizationItem(
            scope="AI",
            description=(
                f"Evaluate model tiering: migrate lower-priority workloads off "
                f"{top_ai.key} (${top_ai.cost:,.2f}) to a lower-cost model"
            ),
        ))
    report.optimization_items = opts[:3]

    # --- Resilience cost ---
    if resilience is not None:
        report.resilience_cost = resilience.total_monthly_resilience_cost
        report.resilience_scenario = resilience.scenario_name

    # --- Risk flags ---
    for row in report.spend_rows:
        if row.delta_pct is not None and row.delta_pct > RISK_THRESHOLD_PCT:
            report.risk_flags.append(RiskFlag(
                scope=row.scope,
                change_pct=row.delta_pct,
                message=(
                    f"{row.scope} spend increased {row.delta_pct:.1f}% month-over-month "
                    f"(+${row.delta_amount:,.2f})" if row.delta_amount else
                    f"{row.scope} spend increased {row.delta_pct:.1f}% month-over-month"
                ),
            ))

    return report
