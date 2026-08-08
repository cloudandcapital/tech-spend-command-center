# Changelog

## 0.3.0 — unreleased

- Add explicit CCAC 1.1 illustrative reconciliation of canonical Cloud,
  direct-AI, and SaaS scope spend into one exact Technology Spend total.
- Preserve CCAC 1.0 as the default and keep Watchdog and Recovery Economics
  diagnostic-only.

## 0.2.1

- Add `techspend summarize <run-directory>`, a deterministic, read-only,
  human-readable view that fails closed unless the complete manifest,
  producer artifact set, and stored trusted report validate as one coherent
  run.
- Preserve canonical display selections, declared values, unknowns, periods,
  currencies, bases, quality, confidence, overlap-safe aggregates, and trust
  boundaries without creating financial calculations or recommendations.
- Change no financial calculations, schemas, producer contracts, overlap
  rules, trust validation, or remediation behavior.

## 0.2.0

- Validate canonical bare MAJOR.MINOR.PATCH release versions through centralized, explicit
  per-producer compatibility ranges, including FinOps Lite `0.3.x` and FinOps Watchdog `0.4.x`, while
  keeping application-version policy independent from `ccac/1.0.0` validation.

- Add manifest-controlled aggregation of five CCAC tool results.
- Emit a versioned, independently validatable CCAC trusted report.
- Verify hashes, run identity, mode, references, review gates, numeric integrity, and cloud reconciliation.
- Exclude unresolved opportunity overlap and avoid adding unlike periods/accounting boundaries.
- Remove invented savings, recommendations, AI anomalies, and forecasts from the legacy report path.
- Fail closed on malformed legacy numeric values.
- Add an atomic `demo-pipeline` quickstart that orchestrates all five installed producers.
- Preserve every included producer's quality status and exact issues in the trusted report.
- Require exactly one produced artifact from every analytical producer and reject omissions, duplicates, unsupported versions, incompatible currencies, unsafe classifications, and broken lineage.
- Make opportunity aggregation status-aware and deterministic per explicit overlap group while retaining excluded IDs.
- Protect cloud reconciliation with matching periods, currencies, and additive classifications.
- Validate complete manifest state, timezone-aware timestamps, exact producer semantic versions, artifact structure, non-empty evidence lineage, and canonical report IDs.
- Exclude invalid metrics from decision-ready display and fail closed when required cloud reconciliation metrics are invalid.
- Reject executable mutation commands recursively in illustrative findings and opportunities without blocking ordinary explanatory prose.
- Exclude every candidate in a repeated overlap group until a future canonical precedence mechanism exists.
- Enforce typed, unique canonical reference arrays and structurally valid non-mutating review steps.
- Detect repeated overlap groups globally across producers and periods, and prevent invalid metrics from re-entering display or aggregates through dependent findings and opportunities.

All notable changes to Tech Spend Command Center are documented here.

## [0.1.0] — Initial release

### Added
- `techspend report` command: reads outputs from up to five FinOps pipeline tools and produces a unified executive summary
- `--cloud` — accepts FinOps Lite JSON (total cost, service breakdown, trend)
- `--watchdog` — accepts FinOps Watchdog JSON (anomalies with severity and message)
- `--resilience` — accepts Recovery Economics JSON or CSV (monthly resilience cost, scenario name)
- `--ai` — accepts AI Cost Lens JSON (total AI spend, model-level rows)
- `--saas` — accepts SaaS Cost Analyzer JSON (total SaaS spend, product-level rows)
- `--format markdown|json|html` — CFO-ready output in three formats
- `--output <file>` — write report to file instead of stdout
- Six report sections: Spend Summary, Anomalies, Optimization Opportunities, Resilience Cost, Forecast, Risk Flags
- Risk flag detection: any scope with >20% month-over-month increase
- Linear next-month spend forecast based on weighted average growth across scopes
- Clean single-page HTML output with inline CSS, colored severity badges, no external dependencies
- Machine-readable JSON output with `schema_version: "1.0"`
- Defensive input parsing: missing or partial inputs are handled gracefully
- Exit codes: 0 success, 2 usage error, 3 file not found, 5 internal error
- GitHub Actions CI on Python 3.10, 3.11, 3.12
- Example input files for all five tools in `examples/`
