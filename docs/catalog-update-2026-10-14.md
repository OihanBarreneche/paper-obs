# Source check: 2026-10-14

All 107 hosted families in the bundled catalog were checked once against
[Erich's Packing Center](https://erich-friedman.github.io/packing/index.html).
The check completed without a failed page. The resulting 4,445 table entries
describe 4,747 individual counts; a picture can serve several counts.

Compared with the 2026-10-02 snapshot, the count-level changes are:

| Change | Counts |
| --- | ---: |
| Better printed value with changed construction information | 563 |
| Newly listed count | 503 |
| Attribution, formula, status or figure update | 38 |
| Numerical correction with unchanged formula and attribution | 23 |
| Higher printed packing size | 1 |
| Removed count | 4 |
| Corrected association of a source cell | 4 |
| Recovered entry omitted by the old reader | 2 |
| Ambiguous source reference, retained without a scalar value | 2 |

These are changes in published references, not proofs of optimality. The
machine-readable [audit](../apps/web/public/catalog/source_audit.json), including its retained history, lists the
page, count and before/after fields for every change, and a check record for every
family. A changed attribution is evidence of a revised published construction;
the audit does not independently establish when it was found.

The octagons-in-squares page now prints 11.47892 for n = 21, replacing the old
snapshot's 11.47891 and attribution. This slightly larger printed size is retained
as a source revision, not reported as a better record. The triangles-in-hexagons
page no longer lists n = 51–54, so those counts are removed rather than extrapolated.
The linked [squares-in-squares page](https://kingbird.myphotos.cc/packing/squares_in_squares.html)
matches all curated rows; its consultation date is updated.

The figure-label warnings in `lincir`, `dominL` and `penRpen` remain visible.
Two malformed rows are explicitly repaired from their own cells: `taninoct` n=36
misses an equals sign (1.98857), and `triindom` n=1–2 prints only the exact formula
√3/2. The old reader shifted the next values onto those cells and lost n=37 and
n=4 respectively. Their correct associations are restored and recorded in the
audit. These are reader repairs, not newly discovered packings.

The final `cirRpen` table has figures for n=49 and n=50 but three values:
4.66314+, 4.81437+ and 4.86154+. Both entries retain their figures and the full
ambiguous group, with `value: null` and `source_ambiguous: true`. They are not used
for numerical comparisons or automatic submission claims until the source is
clarified. No value is silently assigned to an orphaned cell.

A subsequent replay with the maintained parser corrected two further readings:
`taninL` n=1 prints the exact fraction 1/2, previously read as 1; and `linsqu`
n=29 has a 9.93198+ construction alongside the older 29–33 group with value 10.
The individual construction now wins for n=29 and the old group covers n=30–33.
The catalog consequently covers 4,746 distinct counts, rather than counting
n=29 twice. These corrections concern existing source cells, not new discoveries.
The original source comparison above is preserved in the audit history.

The engine was rerun against the new snapshot for all 336 cards with available
configurations: 120 reproduce the printed number, 117 differ on a rounded number,
93 measure worse, and 6 cannot be measured in the source's quantity. Most catalog
cards still have no local coordinates. Source dates and engine dates are separate;
agreement with a new source value does not promote a local construction to a
source-provided arrangement.

Of the seven local record-hunt cases, the current pages attribute five to Oihan
Barreneche: 38 squares in a triangle, 50 squares in a tan, and 41, 44 and 48
dominoes in a tan. The 26-tans-in-L and 47-dominoes-in-tan references now credit
Yanis Gomes with smaller containing sizes. Local arrangements and journals are
preserved; the references used for new comparisons are updated.
