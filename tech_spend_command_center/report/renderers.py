"""Markdown, JSON, and HTML renderers for ReportData."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from .builder import ReportData

SCHEMA_VERSION = "1.0"
_SEVERITY_EMOJI = {"high": "🔴", "medium": "🟡", "low": "🔵", "info": "⚪"}


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _fmt_money(value: Optional[float], currency: str = "USD") -> str:
    if value is None:
        return "—"
    return f"${value:,.2f}"


def _fmt_delta(delta_pct: Optional[float]) -> str:
    if delta_pct is None:
        return "—"
    sign = "+" if delta_pct >= 0 else ""
    return f"{sign}{delta_pct:.1f}%"


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------

def render_markdown(report: ReportData) -> str:
    lines = []
    period = report.period_label or "Current Period"
    generated = _now_utc()

    lines.append("# Tech Spend Command Center")
    lines.append(f"**Period:** {period}  **Generated:** {generated}")
    lines.append("")

    # --- Spend Summary ---
    lines.append("## Spend Summary")
    lines.append("")
    lines.append("| Scope | Current | Prior | Δ |")
    lines.append("|-------|---------|-------|---|")
    for row in report.spend_rows:
        lines.append(
            f"| {row.scope} "
            f"| {_fmt_money(row.current, row.currency)} "
            f"| {_fmt_money(row.prior, row.currency)} "
            f"| {_fmt_delta(row.delta_pct)} |"
        )
    total_prior = report.total_prior_spend
    lines.append(
        f"| **Total** "
        f"| **{_fmt_money(report.total_spend, report.currency)}** "
        f"| **{_fmt_money(total_prior, report.currency)}** "
        f"| — |"
    )
    lines.append("")

    # --- Anomalies ---
    lines.append("## Anomalies (Top 5)")
    lines.append("")
    if report.anomalies:
        for a in report.anomalies:
            icon = _SEVERITY_EMOJI.get(a.severity.lower(), "⚪")
            lines.append(f"- {icon} **[{a.severity.upper()}]** `{a.service}` — {a.message}")
    else:
        lines.append("_No anomalies detected._")
    lines.append("")

    # --- Optimization Opportunities ---
    lines.append("## Optimization Opportunities")
    lines.append("")
    if report.optimization_items:
        for i, opt in enumerate(report.optimization_items, 1):
            savings_note = ""
            if opt.estimated_savings:
                savings_note = f" _(est. savings: {_fmt_money(opt.estimated_savings)}/mo)_"
            lines.append(f"{i}. **[{opt.scope}]** {opt.description}{savings_note}")
    else:
        lines.append("_No optimization opportunities identified._")
    lines.append("")

    # --- Resilience Cost ---
    lines.append("## Resilience Cost")
    lines.append("")
    if report.resilience_cost is not None:
        scenario = report.resilience_scenario or "Default Scenario"
        lines.append(
            f"Monthly resilience cost for **{scenario}**: "
            f"**{_fmt_money(report.resilience_cost, report.currency)}**"
        )
    else:
        lines.append("_No resilience data provided._")
    lines.append("")

    # --- Forecast ---
    lines.append("## Forecast")
    lines.append("")
    forecast = report.forecast_next_month
    lines.append(
        f"Projected next-month total spend: **{_fmt_money(forecast, report.currency)}**"
    )
    if report.total_spend > 0 and forecast != report.total_spend:
        delta = forecast - report.total_spend
        sign = "+" if delta >= 0 else ""
        lines.append(
            f"_(vs current {_fmt_money(report.total_spend, report.currency)}, "
            f"change: {sign}{_fmt_money(delta, report.currency)})_"
        )
    lines.append("")

    # --- Risk Flags ---
    lines.append("## Risk Flags")
    lines.append("")
    if report.risk_flags:
        for flag in report.risk_flags:
            lines.append(f"- 🚨 **{flag.scope}** — {flag.message}")
    else:
        lines.append("✅ No risk flags. All scopes within normal variance thresholds.")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON renderer
# ---------------------------------------------------------------------------

def render_json(report: ReportData) -> str:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_utc(),
        "period": report.period_label,
        "sections": {
            "spend_summary": {
                "total_spend": report.total_spend,
                "total_prior_spend": report.total_prior_spend,
                "currency": report.currency,
                "scopes": [
                    {
                        "scope": row.scope,
                        "current": row.current,
                        "prior": row.prior,
                        "delta_pct": row.delta_pct,
                        "delta_amount": row.delta_amount,
                        "currency": row.currency,
                    }
                    for row in report.spend_rows
                ],
            },
            "anomalies": [
                {
                    "service": a.service,
                    "severity": a.severity,
                    "message": a.message,
                    "scope": a.scope,
                }
                for a in report.anomalies
            ],
            "optimization_opportunities": [
                {
                    "scope": o.scope,
                    "description": o.description,
                    "estimated_savings": o.estimated_savings,
                }
                for o in report.optimization_items
            ],
            "resilience_cost": {
                "total_monthly_resilience_cost": report.resilience_cost,
                "scenario_name": report.resilience_scenario,
                "currency": report.currency,
            } if report.resilience_cost is not None else None,
            "forecast": {
                "projected_next_month": report.forecast_next_month,
                "current_total": report.total_spend,
                "currency": report.currency,
            },
            "risk_flags": [
                {
                    "scope": f.scope,
                    "change_pct": f.change_pct,
                    "message": f.message,
                }
                for f in report.risk_flags
            ],
        },
    }
    return json.dumps(payload, indent=2) + "\n"


# ---------------------------------------------------------------------------
# HTML renderer
# ---------------------------------------------------------------------------

_HTML_STYLE = """
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      margin: 0; padding: 2rem; background: #f5f7fa; color: #1a1a2e;
      font-size: 15px; line-height: 1.6;
    }
    h1 { font-size: 1.75rem; margin-bottom: 0.25rem; color: #0f172a; }
    h2 { font-size: 1.2rem; margin-top: 2rem; margin-bottom: 0.5rem;
         color: #1e3a5f; border-bottom: 2px solid #cbd5e1; padding-bottom: 0.25rem; }
    .meta { color: #64748b; font-size: 0.875rem; margin-bottom: 1.5rem; }
    table { border-collapse: collapse; width: 100%; max-width: 700px; margin-bottom: 1rem; }
    th { background: #1e3a5f; color: #fff; text-align: left; padding: 0.5rem 0.75rem; }
    td { padding: 0.45rem 0.75rem; border-bottom: 1px solid #e2e8f0; }
    tr:last-child td { border-bottom: none; }
    tr.total-row td { font-weight: 700; background: #f1f5f9; }
    .badge {
      display: inline-block; padding: 0.15rem 0.55rem; border-radius: 9999px;
      font-size: 0.75rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em;
    }
    .badge-high   { background: #fee2e2; color: #991b1b; }
    .badge-medium { background: #fef9c3; color: #92400e; }
    .badge-low    { background: #dbeafe; color: #1e40af; }
    .badge-info   { background: #f1f5f9; color: #475569; }
    .badge-ok     { background: #dcfce7; color: #166534; }
    .badge-risk   { background: #fee2e2; color: #991b1b; }
    ul { padding-left: 1.25rem; }
    li { margin-bottom: 0.35rem; }
    .section { background: #fff; border-radius: 0.5rem; padding: 1.25rem 1.5rem;
               margin-bottom: 1.25rem; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
    .forecast-value { font-size: 1.5rem; font-weight: 700; color: #1e3a5f; }
""".strip()


def _severity_badge(severity: str) -> str:
    cls = f"badge-{severity.lower()}"
    return f'<span class="badge {cls}">{severity}</span>'


def _risk_badge(is_risk: bool) -> str:
    if is_risk:
        return '<span class="badge badge-risk">Risk</span>'
    return '<span class="badge badge-ok">OK</span>'


def render_html(report: ReportData) -> str:
    period = report.period_label or "Current Period"
    generated = _now_utc()

    # --- Spend table ---
    spend_rows_html = ""
    for row in report.spend_rows:
        spend_rows_html += (
            f"<tr>"
            f"<td>{row.scope}</td>"
            f"<td>{_fmt_money(row.current, row.currency)}</td>"
            f"<td>{_fmt_money(row.prior, row.currency)}</td>"
            f"<td>{_fmt_delta(row.delta_pct)}</td>"
            f"</tr>\n"
        )
    total_prior = report.total_prior_spend
    spend_rows_html += (
        f'<tr class="total-row">'
        f"<td>Total</td>"
        f"<td>{_fmt_money(report.total_spend, report.currency)}</td>"
        f"<td>{_fmt_money(total_prior, report.currency)}</td>"
        f"<td>—</td>"
        f"</tr>\n"
    )

    # --- Anomalies ---
    if report.anomalies:
        anomaly_items = "\n".join(
            f"<li>{_severity_badge(a.severity)} <strong>{a.service}</strong> — {a.message}</li>"
            for a in report.anomalies
        )
        anomalies_html = f"<ul>{anomaly_items}</ul>"
    else:
        anomalies_html = "<p><em>No anomalies detected.</em></p>"

    # --- Optimization ---
    if report.optimization_items:
        opt_items = "\n".join(
            f"<li><strong>[{o.scope}]</strong> {o.description}"
            + (f" <em>(est. savings: {_fmt_money(o.estimated_savings)}/mo)</em>" if o.estimated_savings else "")
            + "</li>"
            for o in report.optimization_items
        )
        opt_html = f"<ol>{opt_items}</ol>"
    else:
        opt_html = "<p><em>No optimization opportunities identified.</em></p>"

    # --- Resilience ---
    if report.resilience_cost is not None:
        scenario = report.resilience_scenario or "Default Scenario"
        resilience_html = (
            f"<p>Monthly resilience cost for <strong>{scenario}</strong>: "
            f"<strong>{_fmt_money(report.resilience_cost, report.currency)}</strong></p>"
        )
    else:
        resilience_html = "<p><em>No resilience data provided.</em></p>"

    # --- Forecast ---
    forecast = report.forecast_next_month
    delta = forecast - report.total_spend
    sign = "+" if delta >= 0 else ""
    forecast_html = (
        f'<p class="forecast-value">{_fmt_money(forecast, report.currency)}</p>'
        f"<p>Current total: {_fmt_money(report.total_spend, report.currency)} "
        f"&nbsp;|&nbsp; Change: {sign}{_fmt_money(delta, report.currency)}</p>"
    )

    # --- Risk flags ---
    if report.risk_flags:
        risk_items = "\n".join(
            f"<li>{_risk_badge(True)} <strong>{f.scope}</strong> — {f.message}</li>"
            for f in report.risk_flags
        )
        risk_html = f"<ul>{risk_items}</ul>"
    else:
        risk_html = f"<p>{_risk_badge(False)} All scopes within normal variance thresholds.</p>"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Tech Spend Command Center — {period}</title>
<style>
{_HTML_STYLE}
</style>
</head>
<body>
<h1>Tech Spend Command Center</h1>
<p class="meta"><strong>Period:</strong> {period} &nbsp;|&nbsp; <strong>Generated:</strong> {generated}</p>

<div class="section">
<h2>Spend Summary</h2>
<table>
<thead><tr><th>Scope</th><th>Current</th><th>Prior</th><th>Δ</th></tr></thead>
<tbody>
{spend_rows_html}
</tbody>
</table>
</div>

<div class="section">
<h2>Anomalies (Top 5)</h2>
{anomalies_html}
</div>

<div class="section">
<h2>Optimization Opportunities</h2>
{opt_html}
</div>

<div class="section">
<h2>Resilience Cost</h2>
{resilience_html}
</div>

<div class="section">
<h2>Forecast</h2>
{forecast_html}
</div>

<div class="section">
<h2>Risk Flags</h2>
{risk_html}
</div>

</body>
</html>
"""
    return html
