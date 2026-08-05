# Six-Tool Release Checklist

This checklist is for maintainers preparing the coordinated public release. It keeps repository code, package metadata, GitHub presentation, and the cross-repository pipeline aligned while allowing each producer to preserve its own release history.

## Before opening pull requests

- Confirm the working tree diff contains only intentional v0.2 changes.
- Confirm no credentials, private keys, customer exports, local absolute paths, caches, build directories, or editor backup files are tracked.
- Run each repository’s complete test suite.
- Build each wheel and source distribution.
- Install all six packages into one empty virtual environment.
- Run `techspend demo-pipeline --output-dir <new-directory>`.
- Validate `manifest.json` and `report.json` with the CCAC reference validator.
- Confirm the report is illustrative, complete, and contains no invented combined spend total or verified savings.
- Confirm Cloud Cost Guard has not changed.

## Release order

Release producers before the aggregator so the public quickstart never points at unavailable interfaces:

1. FinOps Lite `0.2.0`
2. FinOps Watchdog `0.4.0`
3. Recovery Economics `0.2.0`
4. AI Cost Lens `0.2.0`
5. SaaS Cost Analyzer `0.2.0`
6. Tech Spend Command Center `0.2.0`

For each repository:

1. Create an intentional branch from the current default branch.
2. Review the complete diff and generated package contents.
3. Commit only that repository’s changes.
4. Push the branch and open a pull request.
5. Require the Python matrix and package smoke job to pass.
6. Merge only after review.
7. Tag the exact merge commit with that repository's approved application version and create release notes from the changelog.
8. Re-run the public installation command from the tag before continuing.

## GitHub “About” descriptions

Update these repository settings during release. They are outside the README and can otherwise preserve stale claims.

| Repository | Recommended description |
|---|---|
| `finops-lite` | Read-only AWS cost visibility and canonical CCAC cloud-cost producer. |
| `finops-watchdog` | Robust, financially material cloud-cost anomaly detection with CCAC output. |
| `recovery-economics` | Resilience scenario economics, RTO/RPO modeling, and restore-evidence analysis. |
| `ai-cost-lens` | Evidence-aware AI and LLM usage-cost analysis with price provenance and CCAC output. |
| `saas-cost-analyzer` | SaaS contract, invoice, entitlement, activity, and renewal governance with CCAC output. |
| `tech-spend-command-center` | Hash-locked aggregation of six-tool CCAC results into one trusted executive report. |

Remove any description or topic that claims “FOCUS 2026,” certified FOCUS conformance, native Azure/GCP integrations, automated savings, or direct Cloud Cost Guard production ingestion.

Recommended shared topics: `finops`, `cloud-cost`, `cost-management`, `open-source`, `python`, `ccac`, and `cloud-and-capital`. Add domain-specific topics only where the implementation is real.

## README launch check

Open each public repository in a logged-out browser and verify:

- The first paragraph explains the tool without requiring knowledge of the other repositories.
- Install commands use the `cloudandcapital` organization URL.
- The named console command matches the built wheel.
- The illustrative demo runs without credentials.
- Illustrative data is visibly labeled.
- Real-input instructions state permissions, schemas, and read-only behavior.
- Output basis, accounting boundary, and unknown-value semantics are explained.
- Pipeline compatibility points to Command Center.
- Planned capabilities are not worded as current features.
- Every relative link and example file resolves.

## Final coordinated acceptance

After all six default branches contain the release commits:

1. Clone the six repositories into a new directory.
2. Create one empty Python 3.12 virtual environment.
3. Install each tool from its approved release tag: FinOps Watchdog `v0.4.0` and the other five tools `v0.2.0`.
4. Run the one-command demo twice into different directories.
5. Confirm corresponding artifacts are byte-identical.
6. Independently validate both manifests and reports.
7. Record package hashes, commit hashes, tool versions, CCAC version, test counts, and acceptance timestamp.
8. Only then begin the separate Cloud Cost Guard adapter review.

## LinkedIn readiness

Before sharing links publicly:

- Use Tech Spend Command Center as the main pipeline link.
- Link individual tools when the post discusses that domain specifically.
- Say “illustrative demo” and “estimated opportunity,” not “live customer savings.”
- Do not say FOCUS-conformant until an official validator run supports the exact dataset and applicability criteria.
- Keep Cloud Cost Guard described as the existing dashboard until its trusted-report adapter is actually released.
- Include the release tag rather than an unreviewed branch link.
