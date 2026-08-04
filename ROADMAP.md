# Cloud & Capital Six-Tool Roadmap

This roadmap separates working capabilities from planned ones. It is not a promise of dates. A feature moves into the supported column only after its inputs, calculations, output contract, documentation, tests, clean installation, and cross-repository behavior are verified.

## Operational in v0.2

| Capability | Current implementation |
|---|---|
| AWS visibility | FinOps Lite reads AWS Cost Explorer through read-only APIs and produces reconciled service and daily metrics. |
| Cost anomalies | FinOps Watchdog uses trailing median/MAD plus absolute and percentage materiality gates. |
| Resilience economics | Recovery Economics models design, recovery-event, outage-exposure, RTO/RPO, sensitivity, and restore evidence. |
| AI cost | AI Cost Lens separates reported and calculated cost, token categories, price provenance, allocation, and cloud overlap. |
| SaaS governance | SaaS Cost Analyzer separates contracts, invoices, entitlements, assignments, activity freshness, and renewal capacity. |
| Executive trust layer | Tech Spend Command Center verifies same-run artifacts, hashes, references, overlap, and reconciliation before producing `trusted_report`. |
| Public demonstration | One credential-free command runs all five producers and publishes deterministic illustrative artifacts atomically. |

## Next foundation milestones

These increase real-world usefulness without weakening the trust model:

1. Publish the shared CCAC schemas and reference validator as a separately versioned open-source package.
2. Add a versioned pipeline lock/compatibility file so released producer combinations can be reproduced exactly.
3. Add a central cross-repository CI job that installs released versions, runs the illustrative pipeline, and independently validates every artifact.
4. Add structured verified-outcome documents for approved changes, baselines, post-change measurements, and realized savings.
5. Connect Cloud Cost Guard to `trusted_report` through a read-only adapter; dashboard values must remain canonical ID references.
6. Connect Lumen only after dashboard-to-contract traceability is verified.

## Data and analytics milestones

### Cloud and FOCUS

- Read-only FOCUS 1.4 Cost and Usage ingestion.
- Separate Contract Commitment, Invoice Detail, and Billing Period datasets.
- Invoice reconciliation, correction handling, completeness status, and data-recency metadata.
- Read-only Azure and Google Cloud billing-export adapters with representative fixtures.
- Allocation-rule provenance and shared-cost reconciliation.

### Planning and business context

- Versioned budgets with owner, scope, period, and approval provenance.
- Forecasts only when sufficient historical coverage and a declared method exist; include error backtesting and confidence ranges.
- Business dimensions such as team, product, environment, customer, cost center, and application.
- Unit economics such as cost per request, customer, transaction, AI task, or protected workload.
- Showback/chargeback exports that reconcile to canonical source totals.

### AI economics

- Read-only provider usage adapters where exports and permissions support them.
- Historical, effective-dated price books by provider, region, tier, batch mode, and cache policy.
- Quality and business-outcome denominators supplied by users rather than inferred from model names.
- Reconciliation of Bedrock and other hosted-model charges against cloud billing before executive aggregation.

### SaaS governance

- Read-only contract, invoice, assignment, and activity adapters for documented export formats.
- Renewal calendar, notice-deadline workflow, ownership, and evidence freshness monitoring.
- Contract-to-invoice reconciliation with billing cadence and allocation semantics.
- Identity matching with explicit confidence and human review.

### Resilience

- Provider-neutral rate books with effective dates and provenance.
- More recovery architectures and dependency-aware scenario composition.
- Restore-test history and evidence trends rather than one latest observation.
- Review-first scenario comparisons that preserve reliability tradeoffs alongside modeled economics.

## Features deliberately gated

The following will not be presented as working until their evidence requirements exist:

- Verified savings without verified-outcome measurements.
- Automated remediation without approval, rollback, and verification records.
- A combined technology-spend total across mismatched periods, currencies, or overlapping domains.
- Forecasts from one or two arbitrary totals.
- “Unused” SaaS licenses when activity evidence is missing or stale.
- AI optimization based only on model names or token price.
- FOCUS conformance without the official validator and declared applicability criteria.

## Definition of done

Every new capability must satisfy all of these gates:

- A strict, versioned input contract and clearly labeled illustrative fixture.
- Read-only real-data behavior unless a separately approved mutation workflow exists.
- Transparent formulas, accounting boundary, provenance, and unknown-value semantics.
- Unit tests, hostile tests, reconciliation tests, clean installation, and CLI smoke tests.
- Correct README commands executed from the built package.
- Cross-repository acceptance through the trusted report.
- No dashboard number that cannot be traced to a canonical metric ID.
