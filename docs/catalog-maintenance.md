# Refreshing reference records

From the repository root, use the existing Python environment:

```bash
.venv/bin/python scripts/update_catalog.py
```

This is the regular, manual refresh. It reads the live index, checks all hosted
families in the bundled catalog and checks the linked external squares page.
It applies the hosted records, source dates, compact catalogs and audit only
after the source checks and derived outputs succeed. It does not send email.
The parsers are the existing `build_packing_catalog.py` and
`build_squares_records.py`, now kept in Git alongside this command. The old
`build_packing_catalog.py --refresh --report` invocation delegates to it.
Other local builders, cached pages and generated working files stay ignored.

To inspect the changes without applying them:

```bash
.venv/bin/python scripts/update_catalog.py --check
```

Both commands print progress, change counts, failures and elapsed time. Their
detailed report is `.private/catalog-update/latest.json`. The applied audit is
`apps/web/public/catalog/source_audit.json`. Source check dates are retrieval
dates; discovery dates remain part of the source attribution. An improvement
in the comparison can also be a correction of an older catalog reading.
Earlier non-empty audits are retained in its `history` array.

## Cost and repeatability

HTML is cached under `scripts/out/catalog-update/`. Live checks use HTTP ETag
and Last-Modified validators when the server supplies them, with at most four
requests in flight. A 304 response still counts as a live check. Images,
coordinate files, previews and submission dossiers are not rebuilt by a
reference refresh.

The 2026-10-14 benchmark checked 107 hosted pages, the index and the external
squares page in **6.5 seconds** with no failures, excluding interpreter startup.
A cached replay took **0.5 seconds**. These are measurements on this checkout,
not time guarantees: network failures have a 30-second request timeout.
Applying the two reader corrections, including a fresh engine comparison, took
**36 seconds**; an unchanged refresh skips that comparison.
A second live refresh, with HTTP validators populated and no record changes,
took **2.6 seconds**.

For offline parser verification:

```bash
.venv/bin/python scripts/update_catalog.py --offline --check
.venv/bin/python -m pytest -q tests/catalog/test_update.py
```

Offline mode requires a populated cache and cannot apply changes or advance
source dates. If reference fields changed, applying the refresh also runs the
existing engine comparison; if none changed, it retains the engine check date.
It never rewrites locally held candidates or claims that newly published images
have known coordinates. Tests and frontend builds are development checks,
not part of the regular refresh command.

## Source anomalies and review

The parser reads formula-only values and missing equals signs without shifting
the following figures. Unequal figure/value counts retain the figures with
unknown numeric references and explicit ambiguity. Overlapping count ranges
retain the best printed construction for each count. Truncated maximized values
retain the precision of the last printed digit.

An unavailable or unreadable page prevents publication of the update. Changes
to index membership, removed selections in a compact catalog and differences
on the externally curated squares page also stop for maintainer review; the
report identifies them. The external squares parser checks counts, numeric
values and figure links; its prose attributions are still curated. This command
does not invent templates for new families or proofs for published constructions.
Writes replace individual files after validation; an interrupted filesystem
write is not a transaction across the whole asset set. Rerun the live command
after resolving the filesystem error.
