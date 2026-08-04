# Tech Spend Command Center

The trust and aggregation layer for the Cloud & Capital six-tool pipeline.

Version 0.2 consumes exactly one same-run `ccac/1.0.0` tool result from each of the five analytical producers, verifies their identities and hashes, preserves their canonical metrics, findings, opportunities, and evidence references, and emits one independently validatable `trusted_report`. Missing, duplicate, omitted, failed, unsupported, or incorrectly identified producer artifacts fail closed.

```text
FinOps Lite ───────────┐
FinOps Watchdog ───────┤
Recovery Economics ───┤
AI Cost Lens ──────────┼─> pipeline manifest ─> trusted_report JSON
SaaS Cost Analyzer ────┘
```

Cloud Cost Guard is a planned downstream consumer, but no trusted-report adapter or production integration exists yet. This repository does not deploy or modify it. Lumen is also future work and remains gated on verified dashboard-to-contract traceability.

See the [six-tool roadmap](ROADMAP.md) for the verified v0.2 boundary and the [coordinated release checklist](RELEASE_CHECKLIST.md) for public-launch verification.

## Trust rules

- The Command Center does not invent anomalies, forecasts, recommendations, or savings.
- Every displayed number is an ID from a canonical producer metric.
- Tool-result metrics cannot claim a `verified` basis. Realized savings require a separate verified-outcome document.
- Untagged or unattributed spend remains cost, never an opportunity.
- Potential, nested, and exclusive opportunity overlaps are excluded from headline aggregates until resolved. Rejected, closed, and implemented-pending-verification opportunities are also excluded.
- Independent and `none_known` opportunities may be aggregated, but remain estimates.
- A repeated deterministic overlap group is counted at most once; the lexicographically first opportunity ID takes precedence and every remaining ID stays visible in the excluded catalog.
- Metrics with different periods or accounting boundaries are not forced into one total.
- AI cost with possible cloud-billing overlap and modeled resilience exposure remain non-additive.
- Public review steps must be non-mutating and every opportunity remains approval-, rollback-, and verification-gated.
- Illustrative reports carry an explicit visible disclosure.

## Install

Python 3.10 or later is required.

```bash
pipx install "git+https://github.com/cloudandcapital/tech-spend-command-center.git"
techspend --version
```

The installed command is `techspend`. Installing Command Center alone provides its manifest, trusted-report, and legacy commands. The one-command six-tool demo additionally requires the five producer packages shown below.

## One-command illustrative quickstart

From a directory containing the six repository checkouts, install all six into one environment:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install \
  ./finops-lite \
  ./finops-watchdog \
  ./recovery-economics \
  ./ai-cost-lens \
  ./saas-cost-analyzer \
  ./tech-spend-command-center
```

Then run the complete credential-free pipeline:

```bash
techspend demo-pipeline --output-dir ./demo-run
```

The target directory must not already exist. The command runs every producer in a temporary sibling directory and publishes `demo-run` only after all five results, the manifest, the cloud reconciliation, and the trusted report pass internal validation. A producer failure, missing executable, timeout, hash mismatch, or trust failure leaves no partial target directory.

The result contains:

```text
demo-run/
├── finops-lite.json
├── finops-watchdog.json
├── recovery-economics.json
├── ai-cost-lens.json
├── saas-cost-analyzer.json
├── manifest.json
└── report.json
```

All demo data is explicitly illustrative. The deterministic defaults use a fixed run UUID and timestamp so identical tool versions produce identical artifacts. Override `--run-id` and `--generated-at` only when testing orchestration metadata.

## Compatibility matrix

| Tool | Compatible release | Canonical role |
|---|---|---|
| FinOps Lite | `0.2.x` | Observed cloud-cost producer |
| FinOps Watchdog | `0.2.x` | Cloud anomaly producer |
| Recovery Economics | `0.2.x` | Modeled resilience producer |
| AI Cost Lens | `0.2.x` | AI usage-cost producer |
| SaaS Cost Analyzer | `0.2.x` | SaaS governance producer |
| Tech Spend Command Center | `0.2.x` | Manifest and trusted-report producer |
| Shared contract | `ccac/1.0.0` | Versioned data contract |

## Canonical workflow

All five producers must use the same UUID and mode. Place their results in one run directory. Each producer supports deterministic illustrative output; see its own README for exact input preparation.

Create a hash-locked pipeline manifest:

```bash
techspend manifest \
  --finops-lite run/finops-lite.json \
  --finops-watchdog run/finops-watchdog.json \
  --recovery-economics run/recovery-economics.json \
  --ai-cost-lens run/ai-cost-lens.json \
  --saas-cost-analyzer run/saas-cost-analyzer.json \
  --started-at 2026-08-04T12:00:00Z \
  --completed-at 2026-08-04T12:00:00Z \
  --output run/manifest.json
```

Artifact paths must be inside the manifest directory. The builder checks contract identity, producer identity, run and mode agreement, finite numeric values, unknown-value explanations, evidence and metric references, estimate ranges, review gates, and non-mutating review steps before marking an artifact contract-valid.

Build the trusted report:

```bash
techspend trusted-report \
  --manifest run/manifest.json \
  --generated-at 2026-08-04T12:00:00Z \
  --output run/report.json
```

The aggregator rereads and hashes every artifact. Any later modification fails closed. It also rejects cross-producer ID collisions, incompatible currencies, invalid periods and classifications, broken evidence or metric references, unsupported producer versions, malformed estimates, and non-review-first opportunities. The complete FinOps Lite service breakdown must use matching periods and currencies, remain additive, and reconcile to `metric.cloud.total` within one cent.

Producer periods can describe different valid accounting windows. The report period is their union for navigation only; it is not a claim that the windows are comparable. The Command Center does not manufacture a unified technology-spend number from unlike periods, scopes, bases, or accounting boundaries.

The release acceptance suite uses the separate Cloud & Capital CCAC reference implementation for independent validation:

```bash
ccac validate run/manifest.json
ccac validate run/report.json
```

That validator is a contributor/release tool and is not bundled with Command Center v0.2. Normal users do not need it for `demo-pipeline`; the command performs fail-closed artifact, reference, overlap, and reconciliation checks before publishing output.

## What the trusted report contains

- Exactly five included producer identities. The v0.2 CLI does not create partial trusted reports.
- A quality summary for every included producer, including preserved warning and error details.
- One metric catalog preserving producer bases, periods, additivity, formulas, and evidence references.
- Finding and opportunity catalogs without reinterpretation.
- Opportunity aggregates grouped by estimate period and currency.
- Explicitly excluded overlapping, blocked-status, and duplicate-group opportunities.
- Display IDs rather than copied or recalculated dashboard numbers.
- Cloud service-to-total reconciliation.
- Manifest and artifact SHA-256 provenance.
- Visible accounting and illustrative-data disclosures.

The report period is the union of producer periods. That does **not** make unlike periods additive. Consumers must use the period and additivity carried by each metric. FinOps Watchdog findings do not add spend; Recovery Economics metrics remain modeled scenario economics; AI provider-reported and calculated cost metrics retain their producer-declared bases; and SaaS supplied invoices, commitments, annualized commitments, renewal exposure, and estimated renewal capacity remain separate views.

Canonical metrics retain their complete formula, basis, dimensions, period, additivity, input-metric IDs, and evidence IDs; opportunities also retain confidence and review requirements. The immutable producer artifact hashes in report provenance bind those references back to the source inputs and evidence records stored beside `report.json`. The Command Center does not rewrite evidence into a new claim.

## Legacy report command

The original v0.1 command remains available for compatibility:

```bash
techspend report --cloud cloud.json --ai ai.json --saas saas.json --format markdown
```

It accepts legacy, non-CCAC summaries and therefore cannot provide pipeline trust guarantees. Version 0.2 keeps each supplied scope visible but does not sum Cloud, AI, and SaaS into a unified total because those inputs lack compatible period, cost-basis, and accounting-boundary evidence. It also removed the invented 15% SaaS estimate, informal AI anomalies, unsupported model-tier recommendation, and synthetic forecast. Malformed numeric data now fails instead of silently becoming zero. New integrations should use `manifest` and `trusted-report` only.

## FOCUS positioning

This project consumes CCAC analytical results; it is not itself a FOCUS billing-data generator or a FOCUS conformance validator. FinOps Lite’s current AWS Cost Explorer adapter is a lossy service-level source, not a certified FOCUS export. Future read-only FOCUS 1.4 adapters should preserve Cost and Usage, Contract Commitment, Invoice Detail, and Billing Period datasets separately.

## Test and build

```bash
uv run --with pytest pytest -q
uv build
```

The hostile suite covers hash tampering, mixed run IDs, verified-value misuse, duplicate cross-producer IDs, unresolved overlap, mutating review steps, silent numeric fallbacks, and invented legacy insights. Cross-repository acceptance additionally runs all five producers and validates the manifest and report with the independent CCAC validator.

## Deliberate limits

- Currency conversion is not performed.
- Different estimate periods are never annualized automatically.
- Partial trusted reports are deliberately unsupported in v0.2; all five analytical producers are required exactly once.
- Budget, forecast, allocation, and unit-economics metrics must first come from a versioned authoritative producer contract.
- No vendor or cloud mutation is implemented.
- Real mode requires producer inputs to declare `local_read_only` access and `customer_confidential` classification. No upload, network collection, credential discovery, remediation, or deployment is performed.

MIT licensed. Public examples must remain clearly illustrative.
