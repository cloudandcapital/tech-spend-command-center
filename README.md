# Tech Spend Command Center

[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Multi-cloud](https://img.shields.io/badge/cloud-AWS%20%7C%20Azure%20%7C%20GCP-orange)](https://github.com/cloudandcapital/tech-spend-command-center)
[![SaaS](https://img.shields.io/badge/SaaS-included-blueviolet)](https://github.com/cloudandcapital/tech-spend-command-center)
[![AI for FinOps](https://img.shields.io/badge/AI-spend%20included-ff6b35)](https://github.com/cloudandcapital/tech-spend-command-center)
[![FOCUS 2026](https://img.shields.io/badge/FOCUS-2026-brightgreen)](https://focus.finops.org)

**Unified executive reporting across Cloud · AI · SaaS spend — Markdown, JSON, and HTML output.**

Part of the [Cloud & Capital](https://github.com/cloudandcapital) FinOps pipeline.  
The top of the stack — aggregates all pipeline outputs into a single CFO-ready summary.  
Visualize everything in [Cloud Cost Guard](https://github.com/cloudandcapital/cloud-cost-guard) — the unified FinOps dashboard.

---

**Features:**
- Reads output from all five pipeline tools (FinOps Lite, Watchdog, Recovery Economics, AI Cost Lens, SaaS Analyzer)
- Produces a single unified report: Cloud + AI + SaaS + Kubernetes spend in one view
- Output formats: Markdown (async sharing), JSON (API / dashboard feed), HTML (email-ready)
- Period-over-period variance with anomaly highlighting
- FOCUS 2026 aligned — cost categories match the FinOps Foundation taxonomy

---

## Install

```bash
pip install "git+https://github.com/cloudandcapital/tech-spend-command-center.git"
# or
pipx install .
```

---

## Usage

```bash
# Generate unified Markdown executive summary
tech-spend-command-center report --format markdown

# JSON output (feeds Cloud Cost Guard report.json)
tech-spend-command-center report --format json > report.json

# HTML report (email-ready)
tech-spend-command-center report --format html --output report.html

# Include Kubernetes spend
tech-spend-command-center report --include-k8s --format markdown

# Pull from live pipeline outputs
tech-spend-command-center report \
  --cloud-json cost.json \
  --anomalies-json anomalies.json \
  --resilience-json resilience.json \
  --ai-json ai_spend.json \
  --saas-json saas_spend.json \
  --format markdown
```

---

## Report Sections

| Section | Source tool |
|---------|------------|
| Cloud Infrastructure | FinOps Lite |
| Cost Anomalies | FinOps Watchdog |
| Resilience Cost | Recovery Economics |
| AI / LLM Spend | AI Cost Lens |
| SaaS Licenses | SaaS Cost Analyzer |
| Kubernetes | K8s Connector (Cloud Cost Guard) |

---

## Part of the Cloud & Capital Pipeline

| Tool | Role |
|------|------|
| [FinOps Lite](https://github.com/cloudandcapital/finops-lite) | Cost pull + FOCUS 2026 export |
| [FinOps Watchdog](https://github.com/cloudandcapital/finops-watchdog) | Anomaly detection |
| [Recovery Economics](https://github.com/cloudandcapital/recovery-economics) | Resilience cost modeling |
| [AI Cost Lens](https://github.com/cloudandcapital/ai-cost-lens) | AI/LLM spend tracking |
| [SaaS Cost Analyzer](https://github.com/cloudandcapital/saas-cost-analyzer) | SaaS license governance |
| [Cloud Cost Guard](https://github.com/cloudandcapital/cloud-cost-guard) | Unified dashboard |
| **Tech Spend Command Center** | Executive reporting — aggregates all of the above |

---

## License

MIT © 2025 Diana Molski, Cloud & Capital
