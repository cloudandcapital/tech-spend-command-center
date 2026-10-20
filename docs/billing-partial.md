# Supplied cloud bills: explicit partial reports (draft)

Install the `billing` extra to use the pinned companion FinOps Lite and Watchdog
drafts. The released CCAC 0.2.0 validator is used without schema changes. The
default five-producer complete-report command/policy stays unchanged.

`python -m tech_spend_command_center.billing` reads a JSON data object on stdin
and returns exact canonical artifact strings plus a read-only presentation.
It invokes FinOps Lite, then Watchdog, assembles manifests/report using the
existing canonical catalogs, and validates the actual run before returning.

```python
from pathlib import Path
from tech_spend_command_center.billing import run_billing_pipeline

bundle = run_billing_pipeline({
    "current": [{"name": "bill.csv", "text": Path("bill.csv").read_text()}],
    # "previous": [{"name": "earlier.csv", "text": ...}],
    # "options": {"current": {"duplicatePolicy": "keep"}},
})
```

Amounts and comparisons are owned by FinOps Lite. Watchdog owns eligible daily
diagnostics using its existing history/statistical/materiality rules. Command
Center assembles their emitted results, preserves exact service reconciliation,
and explicitly omits direct AI, SaaS and resilience producers when their input
is absent. Cloud billed cost is partial and ineligible for all-in Technology
Spend. Missing domains are never zeroed or populated from an example fixture.

`validate_billing_run` enforces producer inventories, identities, quality, run
and period consistency, upstream/manifest/artifact hashes, safe fixed filenames,
omission state, CCAC run validation, and exact report ownership of every catalog
entry. A rehashed altered chart or finding still fails the producer comparison.
This adapter does not weaken the separate default complete-report validator.

The presentation copies metric values as decimal strings and keeps their IDs;
it contains no secondary aggregation engine. Finding templates refer to the
canonical finding's own metric references. Original exact JSON artifact strings
remain available to download; JavaScript JSON-number rounding cannot alter them.

The runner uses a temporary directory and removes it before returning. In Guard
this is the WebAssembly worker's in-memory filesystem, and the worker is then
terminated. There is no cloud login, hosted upload endpoint, analytics payload,
AI transfer, public workflow run or retained customer file. The bundled code
and validator run on the visitor's device. Lumen is a deterministic guide over
that same validated presentation; the separate sample-only AI API is unchanged.

Tests use invented bills and adversarial artifact changes. Guard adds native/
WebAssembly parity and real browser interaction checks. Keep this draft linked
to Guard #32 and the producer drafts until the coordinated release is approved.
