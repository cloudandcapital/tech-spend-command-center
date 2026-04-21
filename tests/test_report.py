"""Tests for Tech Spend Command Center — parsers, builder, renderers, and CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from tech_spend_command_center.cli import cli
from tech_spend_command_center.parsers.inputs import (
    parse_ai,
    parse_cloud,
    parse_resilience,
    parse_saas,
    parse_watchdog,
)
from tech_spend_command_center.report.builder import build_report
from tech_spend_command_center.report.renderers import render_html, render_json, render_markdown


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

EXAMPLES = Path(__file__).parent.parent / "examples"


def _write_json(tmp_path: Path, name: str, data: dict) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


CLOUD_DATA = {
    "total_cost": 4821.50,
    "trend": {"trend_direction": "up", "change_percentage": 8.2, "change_amount": 365.20},
    "service_breakdown": [
        {"service_name": "Amazon EC2", "total_cost": 2840.00, "percentage_of_total": 58.9}
    ],
    "currency": "USD",
    "window": {"label": "2026-03"},
}

WATCHDOG_DATA = {
    "anomalies": [
        {"service": "Amazon EC2", "severity": "high", "message": "Spend up 42%"},
        {"service": "Amazon RDS", "severity": "medium", "message": "New instance type"},
    ],
    "total_anomalies": 2,
}

RESILIENCE_DATA = {
    "scenario_name": "Production Workload",
    "total_monthly_resilience_cost": 1240.00,
    "currency": "USD",
}

AI_DATA = {
    "schema_version": "1.0",
    "total_cost": 892.40,
    "rows": [
        {"key": "gpt-4o", "cost": 512.30, "provider": "openai"},
        {"key": "claude-sonnet-4-6", "cost": 280.10, "provider": "anthropic"},
    ],
}

SAAS_DATA = {
    "schema_version": "1.0",
    "total_cost": 1580.00,
    "rows": [
        {"key": "Salesforce", "cost": 750.00},
        {"key": "Slack", "cost": 437.50},
    ],
}


@pytest.fixture()
def runner():
    return CliRunner()


@pytest.fixture()
def cloud_file(tmp_path):
    return _write_json(tmp_path, "cloud.json", CLOUD_DATA)


@pytest.fixture()
def watchdog_file(tmp_path):
    return _write_json(tmp_path, "watchdog.json", WATCHDOG_DATA)


@pytest.fixture()
def resilience_file(tmp_path):
    return _write_json(tmp_path, "resilience.json", RESILIENCE_DATA)


@pytest.fixture()
def ai_file(tmp_path):
    return _write_json(tmp_path, "ai.json", AI_DATA)


@pytest.fixture()
def saas_file(tmp_path):
    return _write_json(tmp_path, "saas.json", SAAS_DATA)


# ---------------------------------------------------------------------------
# 1. Parse cloud JSON → correct total_cost, trend extracted
# ---------------------------------------------------------------------------

def test_parse_cloud_total_cost(cloud_file):
    data = parse_cloud(cloud_file)
    assert data.total_cost == pytest.approx(4821.50)


def test_parse_cloud_trend(cloud_file):
    data = parse_cloud(cloud_file)
    assert data.change_percentage == pytest.approx(8.2)
    assert data.change_amount == pytest.approx(365.20)
    assert data.trend_direction == "up"


# ---------------------------------------------------------------------------
# 2. Parse watchdog JSON → anomalies list populated
# ---------------------------------------------------------------------------

def test_parse_watchdog_anomalies(watchdog_file):
    data = parse_watchdog(watchdog_file)
    assert len(data.anomalies) == 2
    assert data.anomalies[0].service == "Amazon EC2"
    assert data.anomalies[0].severity == "high"


# ---------------------------------------------------------------------------
# 3. Parse resilience JSON → resilience_cost extracted
# ---------------------------------------------------------------------------

def test_parse_resilience_cost(resilience_file):
    data = parse_resilience(resilience_file)
    assert data.total_monthly_resilience_cost == pytest.approx(1240.00)
    assert data.scenario_name == "Production Workload"


# ---------------------------------------------------------------------------
# 4. Parse AI JSON → ai_cost extracted
# ---------------------------------------------------------------------------

def test_parse_ai_cost(ai_file):
    data = parse_ai(ai_file)
    assert data.total_cost == pytest.approx(892.40)
    assert len(data.rows) == 2
    assert data.rows[0].key == "gpt-4o"
    assert data.rows[0].provider == "openai"


# ---------------------------------------------------------------------------
# 5. Parse SaaS JSON → saas_cost extracted
# ---------------------------------------------------------------------------

def test_parse_saas_cost(saas_file):
    data = parse_saas(saas_file)
    assert data.total_cost == pytest.approx(1580.00)
    assert len(data.rows) == 2
    assert data.rows[0].key == "Salesforce"


# ---------------------------------------------------------------------------
# 6. ReportData.total_spend sums across all scopes
# ---------------------------------------------------------------------------

def test_report_total_spend(cloud_file, ai_file, saas_file):
    cloud = parse_cloud(cloud_file)
    ai = parse_ai(ai_file)
    saas = parse_saas(saas_file)
    report = build_report(cloud=cloud, ai=ai, saas=saas)
    expected = 4821.50 + 892.40 + 1580.00
    assert report.total_spend == pytest.approx(expected)


# ---------------------------------------------------------------------------
# 7. Risk flag triggered when change_percentage > 20
# ---------------------------------------------------------------------------

def test_risk_flag_triggered(tmp_path):
    data = {**CLOUD_DATA, "trend": {"trend_direction": "up", "change_percentage": 25.0, "change_amount": 1000.0}}
    f = _write_json(tmp_path, "cloud_risk.json", data)
    cloud = parse_cloud(f)
    report = build_report(cloud=cloud)
    assert len(report.risk_flags) == 1
    assert report.risk_flags[0].scope == "Cloud"
    assert report.risk_flags[0].change_pct == pytest.approx(25.0)


# ---------------------------------------------------------------------------
# 8. Risk flag NOT triggered when change_percentage <= 20
# ---------------------------------------------------------------------------

def test_risk_flag_not_triggered(tmp_path):
    data = {**CLOUD_DATA, "trend": {"trend_direction": "up", "change_percentage": 15.0, "change_amount": 600.0}}
    f = _write_json(tmp_path, "cloud_ok.json", data)
    cloud = parse_cloud(f)
    report = build_report(cloud=cloud)
    assert len(report.risk_flags) == 0


def test_risk_flag_exactly_20_not_triggered(tmp_path):
    data = {**CLOUD_DATA, "trend": {"trend_direction": "up", "change_percentage": 20.0, "change_amount": 800.0}}
    f = _write_json(tmp_path, "cloud_border.json", data)
    cloud = parse_cloud(f)
    report = build_report(cloud=cloud)
    assert len(report.risk_flags) == 0


# ---------------------------------------------------------------------------
# 9. Markdown renderer produces "Spend Summary" header
# ---------------------------------------------------------------------------

def test_markdown_has_spend_summary_header(cloud_file):
    cloud = parse_cloud(cloud_file)
    report = build_report(cloud=cloud)
    md = render_markdown(report)
    assert "## Spend Summary" in md


# ---------------------------------------------------------------------------
# 10. Markdown renderer includes all scope names that have data
# ---------------------------------------------------------------------------

def test_markdown_includes_all_scopes(cloud_file, ai_file, saas_file):
    cloud = parse_cloud(cloud_file)
    ai = parse_ai(ai_file)
    saas = parse_saas(saas_file)
    report = build_report(cloud=cloud, ai=ai, saas=saas)
    md = render_markdown(report)
    assert "Cloud" in md
    assert "AI" in md
    assert "SaaS" in md


# ---------------------------------------------------------------------------
# 11. JSON renderer output has schema_version: "1.0"
# ---------------------------------------------------------------------------

def test_json_renderer_schema_version(cloud_file):
    cloud = parse_cloud(cloud_file)
    report = build_report(cloud=cloud)
    output = render_json(report)
    data = json.loads(output)
    assert data["schema_version"] == "1.0"


def test_json_renderer_structure(cloud_file, ai_file):
    cloud = parse_cloud(cloud_file)
    ai = parse_ai(ai_file)
    report = build_report(cloud=cloud, ai=ai)
    data = json.loads(render_json(report))
    assert "sections" in data
    assert "spend_summary" in data["sections"]
    assert "anomalies" in data["sections"]
    assert "forecast" in data["sections"]
    assert "risk_flags" in data["sections"]


# ---------------------------------------------------------------------------
# 12. HTML renderer produces valid HTML with <html> tag
# ---------------------------------------------------------------------------

def test_html_renderer_has_html_tag(cloud_file):
    cloud = parse_cloud(cloud_file)
    report = build_report(cloud=cloud)
    html = render_html(report)
    assert "<html" in html
    assert "</html>" in html


def test_html_renderer_has_spend_table(cloud_file, saas_file):
    cloud = parse_cloud(cloud_file)
    saas = parse_saas(saas_file)
    report = build_report(cloud=cloud, saas=saas)
    html = render_html(report)
    assert "<table>" in html
    assert "Cloud" in html
    assert "SaaS" in html


# ---------------------------------------------------------------------------
# 13. CLI exits 2 when no inputs provided
# ---------------------------------------------------------------------------

def test_cli_exits_2_no_inputs(runner):
    result = runner.invoke(cli, ["report"])
    assert result.exit_code == 2


# ---------------------------------------------------------------------------
# 14. CLI exits 0 with valid input
# ---------------------------------------------------------------------------

def test_cli_exits_0_with_valid_input(runner, cloud_file):
    result = runner.invoke(cli, ["report", "--cloud", str(cloud_file)])
    assert result.exit_code == 0
    assert "Tech Spend Command Center" in result.output


def test_cli_exits_0_json_format(runner, cloud_file):
    result = runner.invoke(cli, ["report", "--cloud", str(cloud_file), "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["schema_version"] == "1.0"


# ---------------------------------------------------------------------------
# 15. --output flag writes to file instead of stdout
# ---------------------------------------------------------------------------

def test_cli_output_flag_writes_file(runner, cloud_file, tmp_path):
    out_file = tmp_path / "report.md"
    result = runner.invoke(cli, ["report", "--cloud", str(cloud_file), "--output", str(out_file)])
    assert result.exit_code == 0
    assert result.output == ""  # nothing on stdout
    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert "Tech Spend Command Center" in content


# ---------------------------------------------------------------------------
# 16. Missing optional fields handled gracefully (no crash)
# ---------------------------------------------------------------------------

def test_cloud_missing_trend_no_crash(tmp_path):
    data = {"total_cost": 1000.0}
    f = _write_json(tmp_path, "cloud_minimal.json", data)
    cloud = parse_cloud(f)
    report = build_report(cloud=cloud)
    md = render_markdown(report)
    assert "Cloud" in md


def test_watchdog_empty_anomalies_no_crash(tmp_path):
    data = {"anomalies": [], "total_anomalies": 0}
    f = _write_json(tmp_path, "watchdog_empty.json", data)
    watchdog = parse_watchdog(f)
    report = build_report(watchdog=watchdog)
    md = render_markdown(report)
    assert "No anomalies" in md


def test_resilience_csv_parse(tmp_path):
    csv_content = "scenario_name,total_monthly_resilience_cost,currency\nProduction,1240.00,USD\n"
    f = tmp_path / "resilience.csv"
    f.write_text(csv_content, encoding="utf-8")
    data = parse_resilience(f)
    assert data.total_monthly_resilience_cost == pytest.approx(1240.00)
    assert data.scenario_name == "Production"


def test_all_inputs_full_report(runner, tmp_path):
    """Integration: all five inputs produce a complete markdown report."""
    cf = _write_json(tmp_path, "cloud.json", CLOUD_DATA)
    wf = _write_json(tmp_path, "watchdog.json", WATCHDOG_DATA)
    rf = _write_json(tmp_path, "resilience.json", RESILIENCE_DATA)
    af = _write_json(tmp_path, "ai.json", AI_DATA)
    sf = _write_json(tmp_path, "saas.json", SAAS_DATA)
    result = runner.invoke(cli, [
        "report",
        "--cloud", str(cf),
        "--watchdog", str(wf),
        "--resilience", str(rf),
        "--ai", str(af),
        "--saas", str(sf),
    ])
    assert result.exit_code == 0
    assert "## Spend Summary" in result.output
    assert "## Anomalies" in result.output
    assert "## Optimization Opportunities" in result.output
    assert "## Resilience Cost" in result.output
    assert "## Forecast" in result.output
    assert "## Risk Flags" in result.output
    assert "Amazon EC2" in result.output
