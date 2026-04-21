# Tech Spend Command Center

[![CI](https://github.com/dianuhs/tech-spend-command-center/actions/workflows/test.yml/badge.svg)](https://github.com/dianuhs/tech-spend-command-center/actions/workflows/test.yml)

**The top of the FinOps pipeline stack.** Tech Spend Command Center reads outputs from all five pipeline tools and produces a single CFO-ready executive summary report covering Cloud, AI, and SaaS spend in one view.

| Stage | Tool | What it does |
|-------|------|-------------|
| **Visibility** | [FinOps Lite](https://github.com/dianuhs/finops-lite) | AWS/Azure/GCP cost visibility, FOCUS 1.0 export |
| **Variance** | [FinOps Watchdog](https://github.com/dianuhs/finops-watchdog) | Anomaly detection from any cost CSV |
| **Tradeoffs** | [Recovery Economics](https://github.com/dianuhs/recovery-economics) | Resilience cost modeling, scenario comparison |
| **AI Spend** | [AI Cost Lens](https://github.com/dianuhs/ai-cost-lens) | OpenAI/Anthropic/Bedrock billing → FOCUS 1.0 |
| **SaaS Spend** | [SaaS Cost Analyzer](https://github.com/dianuhs/saas-cost-analyzer) | SaaS billing → FOCUS 1.0, unused licenses, forecasting |
| **Command Center** | [Tech Spend Command Center](https://github.com/dianuhs/tech-spend-command-center) | Unified Cloud+AI+SaaS executive summary report |

---

## What It Does

`techspend report` accepts JSON or CSV outputs from any of the five tools above (all inputs are optional — report on whatever you have) and produces a unified executive summary with:

- **Spend Summary** — total spend by scope (Cloud / AI / SaaS) with period-over-period delta where available
- **Top Anomalies** — up to 5 anomalies across all scopes (sourced from Watchdog and AI Cost Lens)
- **Optimization Opportunities** — up to 3 actionable items (unused licenses, rightsizing, model tiering)
- **Resilience Cost** — monthly resilience cost from Recovery Economics
- **Forecast** — projected next-month total spend across all scopes
- **Risk Flags** — any scope where spend increased >20% month-over-month

Output formats: **markdown** (default), **json** (machine-readable, `schema_version: "1.0"`), or **html** (CFO-ready, inline CSS only, no external dependencies).

## Install

```bash
pip install -e .
# or
pipx install "git+https://github.com/dianuhs/tech-spend-command-center.git"
```

## Quickstart

### Full pipeline report (all five tools)

```bash
techspend report \
  --cloud    finops-lite-output.json \
  --watchdog watchdog-output.json \
  --resilience recovery-output.json \
  --ai       ai-cost-lens-output.json \
  --saas     saas-output.json \
  --format   markdown
```

### Cloud + AI only, JSON output

```bash
techspend report \
  --cloud  finops-lite-output.json \
  --ai     ai-cost-lens-output.json \
  --format json | jq '.sections.spend_summary'
```

### Write an HTML report to file

```bash
techspend report \
  --cloud  examples/cloud-input.json \
  --ai     examples/ai-input.json \
  --saas   examples/saas-input.json \
  --format html \
  --output report.html
```

### Try the example inputs

```bash
techspend report \
  --cloud       examples/cloud-input.json \
  --watchdog    examples/watchdog-input.json \
  --resilience  examples/resilience-input.json \
  --ai          examples/ai-input.json \
  --saas        examples/saas-input.json
```

See [`examples/sample-report.md`](examples/sample-report.md) for what this produces.

## Command Reference

```
techspend report [OPTIONS]

Options:
  --cloud       PATH   Path to FinOps Lite JSON output
  --watchdog    PATH   Path to FinOps Watchdog JSON output
  --resilience  PATH   Path to Recovery Economics JSON or CSV output
  --ai          PATH   Path to AI Cost Lens JSON output
  --saas        PATH   Path to SaaS Cost Analyzer JSON output
  --format      TEXT   markdown | json | html  [default: markdown]
  --output      PATH   Write to file instead of stdout
  --help               Show this message and exit.
```

## Input Formats

| Flag | Tool | Format |
|------|------|--------|
| `--cloud` | FinOps Lite | JSON: `total_cost`, `service_breakdown`, `trend` |
| `--watchdog` | FinOps Watchdog | JSON: `anomalies[]` with `service`, `severity`, `message` |
| `--resilience` | Recovery Economics | JSON or CSV: `total_monthly_resilience_cost`, `scenario_name` |
| `--ai` | AI Cost Lens | JSON: `total_cost`, `rows[]` with `key`, `cost`, `provider` |
| `--saas` | SaaS Cost Analyzer | JSON: `total_cost`, `rows[]` with `key`, `cost` |

All inputs are optional. If a field is missing, that section is skipped gracefully.

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `2` | Usage/validation error (no inputs provided, bad `--format`) |
| `3` | File not found |
| `5` | Internal error |

## Examples

See [`examples/`](examples/) for sample input files for all five tools and a pre-rendered [`sample-report.md`](examples/sample-report.md).

## License

MIT
