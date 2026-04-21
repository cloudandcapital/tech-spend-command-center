# Changelog

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
