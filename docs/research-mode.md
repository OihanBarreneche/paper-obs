# Research mode

Research mode is the counterpart of the workflows. A workflow is a graph the lab drives: the model acts through a fixed set of tools, inside a budget. In research mode an outside agent (Claude Code, Codex, a person with scripts) drives. It may write any program in any language, run long searches and change method whenever it likes. The lab is the referee and the logbook: every arrangement the agent claims is judged by the engine and recorded in a session, which the web app shows in the Search tab.

Read this page when the owner asks for a research session or a record hunt. Nothing here is a workflow: the steps below are what makes a result comparable and trustworthy, not a recipe for searching.

## 1. Choose the problem

- A family of the shipped catalog: `paper-obs research problem squintri 38 -o problem.json`. The problem carries the published record (`metadata.reference`: value, unit, author, figure, page) for that count.
- Any other problem: build or open it in the web app and use **Export ▸ Problem**.

The catalog is a snapshot, dated in `reference.verified_on`, and Friedman's tables change within days. Before working on a record, read the current value on the family page for that count. Source consultation and engine validation have separate dates. During a hunt, read only the pages a claim depends on. A complete catalog check is a separate, owner-requested maintenance task; do not turn it into periodic crawling.

## 2. Plan the machine

Before any long computation, audit what the machine offers: logical processors, memory, GPU and current load (`nproc`, `free -h` and `nvidia-smi` on Linux or WSL; `Get-CimInstance Win32_Processor`, `Win32_OperatingSystem` and `nvidia-smi` on Windows). Then propose a plan to the owner, for example "8 processes at idle priority, about 6 GB of memory, no GPU". It can be greedy, but it must leave the computer usable. The owner validates or adjusts it. Without an answer, use half the logical processors.

Set the low priority from the program itself, so worker processes inherit it, and never run two heavy jobs at once. Write the agreed plan as the session's first note.

## 3. Open a session

```bash
paper-obs research start -p problem.json --name "38 squares, Cantrell extension" --agent "Claude Code · Opus 5.5" --goal "beat 10.304"
```

The answer gives the session id and its folder, `runs/research/<id>/`. The folder holds `session.json`, which the lab writes, and `work/`, which belongs to the agent: put programs, logs, seeds and intermediate files there. The runs folder is ignored by Git, so nothing in it is published by accident.

Open the session before the first computation, so the owner can follow the whole search.

## 4. Search freely, keep the journal

Candidates are the lab's JSON: `problem_id`, `scale` and `placements`, each with `shape_id`, `x`, `y` and `rotation` in degrees. They are written in the problem's own frame:

- **A fixed arena (`maximize_scale`):** the arena is the unit container and the copies share the scale `scale`. The container side the source publishes is the arena's `reference_length` (1 for every catalog arena) divided by `scale`.
- **A derived container (`minimize_container`):** the copies are unit copies, and the engine measures the smallest square or circle around them.

Useful commands:

```bash
paper-obs research submit <id> -c candidate.json --method search --from 3 --program lns.py --note "LNS from the x.301 seed"
paper-obs research note <id> --step dead-end "corner seeds never beat 7.6188 in 20 min on 8 processes: dropped"
paper-obs research status <id>                    # best so far and the record
paper-obs research status <id> --set paused       # active, paused or done
paper-obs evaluate -p problem.json -c candidate.json   # judge without logging
```

A submission is judged, and the command exits 1 when the arrangement is invalid. From Python, `paper_obs.research.submit(session_id, candidate, note, method=..., builds_on=..., programs=[...])` and `paper_obs.research.add_note(session_id, text, step, path)` do the same as the commands, and `paper_obs.geometry.engine.evaluate` judges without logging. A session keeps the arrangement and full verdict of improvements only, and the measure of every submission.

The lab also offers four tools, none of them required. `refine` and `picture` need the `research` extra (`pip install -e ".[research]"`: SciPy, Pillow and resvg):

```bash
paper-obs research refine -p problem.json -c candidate.json -o refined.json   # close the contacts
paper-obs research verify -p problem.json -c refined.json                    # judge again, exactly
paper-obs research leads                                                     # entries a dissection beats
paper-obs research picture -p problem.json -c refined.json -o 26.gif --like old26.gif
```

- **`refine`** closes an arrangement's contacts. It keeps each nearby pair apart by one fixed separating axis, keeps every copy in the arena, and maximises the scale with SLSQP, choosing the axes again until they settle. The engine then accepts the largest scale it judges valid. It covers `maximize_scale` problems with equal convex polygonal copies. A non-convex arena (an L, a frame, holes) is its convex hull minus convex obstacles, and a disc arena is its exact circle. From Python: `paper_obs.search.refine.exact_refine(problem, candidate)`.
- **`leads`** scans the shipped catalog for entries that a construction from other entries beats. A copy can hold copies (a square holds two tans, a tan is two tans 1/√2 its size), and a container can split into containers (a triangle of side 2s is four of side s). A printed value counts at the upper end of its last digit, since it is truncated. A lead is a hint to check on the live page, not a record.
- **`verify`** judges the arrangement again on a code path of its own (`paper_obs.geometry.exact_check`): every corner becomes an exact fraction, and the separating-axis theorem decides overlaps and containment in rational arithmetic, with no tolerance. It reports the overlapping pairs, the copies out and the smallest margins, and exits 1 when the arrangement is invalid.
- **`picture`** draws an SVG and renders it in the requested format. `--like` reads the original's size, colours and transparency; `--rotate` matches its orientation. The agent can download the specific image being replaced while checking the claim's page.
- **`prepare`** creates a private submission dossier from a session's best, judged against the current bundled reference and independently where supported. Dimensions and format come from the downloaded original; its exact filename comes from the source URL, including letters such as `ts38.gif`. Compare the original and output visually.
- **`batch`** packages selected prepared dossiers. Images retain their exact names inside one folder per source page, with measurements and an email draft. Coordinates, SVG working files and engine checks stay local.

### The journal

The owner follows a session live in **Search ▸ Free research**, which reads it again every five seconds. Afterwards, the owner reads it to understand how a result was found: by understanding the problem, by composing known arrangements, or by searching. Write each entry when it happens, never reconstructed at the end. Keep it to one or two sentences with the numbers that matter.

Every note names its step with `--step`:

| Step | When to write it | What it says |
| --- | --- | --- |
| `idea` | You understand something or see a lead: a pattern, a symmetry, a dissection. | What you understood, and why it could beat the record. |
| `program` | You write or substantially change a program in `work/`. Name it with `--path`, relative to `work/`. | What it reads, what it computes and what it gives, in one sentence. |
| `search` | You launch a computation of more than a minute, and again when it ends. | Which program, on how many processes, for how long, and what came out. |
| `dead-end` | You drop an approach. | What was tried, for how long, the best it reached, and why it is dropped. |
| `check` | You verify a result. | Engine, `verify` margins, the live page and the date it was read. |

A note without a step gives context, such as the machine plan.

Every submission says where its arrangement comes from:

- `--method` is one of four:
  - `reasoning`: built from an understanding of the problem, such as a construction family extended by one step, a symmetric construction or a pattern computed in closed form;
  - `composition`: assembled from published or earlier arrangements, by dissection, scaling or juxtaposition, without searching;
  - `search`: found by an automatic exploration with randomness or enumeration, such as random restarts, LNS, basin hopping or brute force;
  - `refinement`: a local optimisation that keeps an earlier arrangement's structure, such as closing contacts with SLSQP.
- `--from` gives what it starts from: the `index` of an earlier submission, as `submit` printed it, or a short text naming an outside source, such as `"Morandi's n = 13 (2012)"`.
- `--program` names each `work/` program that produced it; repeat it for several.

Submit each new best, and also each intermediate step that a later best builds on, even when it does not beat the session's best (a composition that a refinement then improves, for example). Then the chain from the starting point to the best arrangement is complete. Do not submit every attempt of a search: its outcome goes in a `search` note.

When the search ends, first complete the submission step in section 6, then set the status to `done` and write a last note on what the result owes to understanding, to composition and to search. The page draws the chain from the starting point to the best arrangement, labels each link with its method, lists the programs with their code, and shows the journal in order: a new best wears a green mark, an invalid submission a red one, and dead ends are muted. Each session says whether it beats the published record, ties it or how far it stays. Sessions written before steps and methods existed show their improvements as the chain, without labels. Opening a session shows its best arrangement on the canvas, and a chart draws each new best against the record. The list of every session sorts by date or by improvement, which brings records first, and filters by shape and container. A session that led nowhere can be deleted from that list or from its own header: its folder moves to `runs/research/deleted/`, out of the listing, and moving it back by hand restores it.

Two record hunts ship as example sessions in `examples/research/`, journaled live as they ran: 50 squares in a tan, beaten by extending a construction family, and 41 dominoes in a tan, beaten by moving a published gesture to another place, with an invalid construction and its correction left in the journal. Their programs are copied as they were; some need a C compiler or files of the hunt that are not shipped, so they are for reading. `paper-obs serve` copies them into the runs folder once, as it does the example runs.

## 5. Before claiming a record

1. The engine judges the arrangement valid when it is submitted. Keep a small safety margin, for example a scale shrunk by `1e-9` relative, so that a contact closed exactly by an optimiser stays legal.
2. Check independently: `paper-obs research verify` decides in exact rational arithmetic, apart from the engine's predicates.
3. Published values are truncated, so `1.499+` means at least 1.499. A claim must be strictly better than the printed digits.
4. Re-read the live page on the day of the claim, and note the date in the session.
5. Keep the code that produced the result in `work/`, with a `program` note for each file and the `--program` of each submission.

## 6. Submitting to the source

Preparing the dossier is the final step of every successful record hunt, before
marking the session `done`. Re-read the live reference on that day; if it is newer
than the bundled catalog, update the catalog before preparation. Visually check
the output against the original for orientation and colours, and journal the
prepared dossier. If no record is improved, or preparation is blocked, record why.

Only the owner sends the email. Use `.private/submissions/` (ignored by Git) for
the dossiers. In his reply supplied by the owner on 2026-10-14, Erich clarified
that coordinates are **not required**, and permitted reuse of the packings with
credit to **Erich's Packing Center** and a link. Keep coordinates and verification
results as local research evidence, outside the recipient attachments. Exact
coordinates and an exact expression for the measured value are different things:
the latter remains welcome when available.

The [public submission guidelines](https://erich-friedman.github.io/packing/submit.html)
request:

1. a descriptive title, in a new email rather than a reply to an earlier exchange;
2. a picture of the packing in the same orientation, colours, pixel size, file type and name as the picture it replaces, with no border or text. In the "Maximize Total Perimeter" pages, any rainbow palette in which close sizes get close colours is accepted;
3. the radius or side length to 5 decimal places, and the exact value if possible;
4. the submitter's full name, for attribution;
5. for a new submitter, a description of the program or method used.

Extending an existing table is accepted only up to n = 50. A large batch is sorted by page into named folders, with the values in one text file per page or in the email itself.

```bash
.venv/bin/paper-obs research prepare res-SESSION \
  --like runs/research/res-SESSION/work/ts38.gif \
  --author "Full name" --method "Short explanation" --rotate 0
.venv/bin/paper-obs research status res-SESSION --set done
.venv/bin/paper-obs research batch res-SESSION res-ANOTHER \
  -o .private/submissions/batch.zip
```

The filename comes from the current source image, not from the count or the session
name. Do not prefix filenames with family names inside the attachments: the page
folder already distinguishes two images both called `26.gif`. `prepare` requires
the original image format and derives its pixel dimensions and palette; for total
perimeter it uses the guidelines' rainbow exception, mapping close sizes to close
colours. Orientation is selected with `--rotate` and still requires visual review.

In **Search ▸ Free research ▸ All sessions**, check the prepared sessions and use
**Download selected submissions**. The ZIP contains images, one `values.txt` per
page and `email.txt`; it never sends mail. Review the five-decimal values and add
any useful exact expression before sending. A changed best candidate invalidates
its prepared dossier; a batch also refuses a candidate that no longer beats the
current catalog or two dossiers replacing the same image.

Automatic dossiers cover supported catalog families with an existing raster image
to replace. New counts and externally hosted families need a manual submission
plan. Image orientation and the inferred fill style still require visual review;
source-value checks and geometric validity do not establish those visual choices.

## 7. What has worked so far

These are observations from the record hunts so far, not rules:

- **Extend a construction family.** Published records come in families: square-in-triangle sides of the form k + 2/√3, k + 0.30122 and so on. A recent record that breaks a family's pattern can be beaten by extending the family by one step. This is how n = 38 squares in a triangle went from 10.304 to 10.30122.
- **Look for dissections.** A tan is two tans 1/√2 its size, a unit octagon holds a unit circle, a triangle of side 2s is four triangles of side s, and so on. Each fact turns one published record into a construction for another entry. An exact refinement of the assembled arrangement then helps, because the internal cuts are not walls. This is how n = 26 tans in an L went from 2.12132 to 2.12043.
- **Start from published figures.** Reading the copies' centres and angles off a figure, then refining exactly (maximise the scale with fixed contacts), recovered every square-in-triangle record to about 1e-12. It gives exact coordinates of current records as seeds.
- **Enumerate a structure exhaustively.** When records share a structure, a staircase in the right-angle corner and bands turned by 45 degrees for squares or dominoes in a tan, a small C program can try every combination of its parameters in seconds. Adding one band beat n = 50 squares in a tan; the same enumeration beat n = 44 dominoes.
- **Move a published gesture.** A local trick an author used for some n, such as two dominoes leaning together in a V over a corner of the staircase, can be tried at every place it fits in other entries. Adding it to the enumeration beat n = 41, 47 and 48 dominoes in a tan.
- **Calibrate before believing a search.** Random restarts, corner-block seeds and ruin-and-recreate did not rediscover recent records for n ≈ 20 to 26 squares in a triangle in 20 minutes. Ideas beat brute force there.
