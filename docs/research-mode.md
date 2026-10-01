# Research mode

Research mode is the counterpart of the workflows. A workflow is a graph the lab drives: the model acts through a fixed set of tools, inside a budget. In research mode an outside agent (Claude Code, Codex, a person with scripts) drives. It may write any program in any language, run long searches and change method whenever it likes. The lab is the referee and the logbook: every arrangement the agent claims is judged by the engine and recorded in a session, which the web app shows in the Search tab.

Read this page when the owner asks for a research session or a record hunt. Nothing here is a workflow: the steps below are what makes a result comparable and trustworthy, not a recipe for searching.

## 1. Choose the problem

- A family of the shipped catalog: `paper-obs research problem squintri 38 -o problem.json`. The problem carries the published record (`metadata.reference`: value, unit, author, figure, page) for that count.
- Any other problem: build or open it in the web app and use **Export ▸ Problem**.

The catalog is a snapshot, dated in `reference.verified_on`, and Friedman's tables change within days. Before working on a record, read the current value on the family page for that count. Read only the pages a claim depends on: no crawler or automatic refresh of the Packing Center may be built without its author's permission.

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
- **`picture`** draws the arrangement for a submission as an SVG, written beside the picture, then renders it with resvg in the format the file name asks for. With `--like`, it copies the picture it replaces: its pixel size; crisp edges in its exact palette when it has a handful of colours, anti-aliased edges otherwise; a transparent outside when it has one; white as empty space, the most common other colour for the copies and the darkest for the lines. `--size`, `--rotate` and the file suffix set the rest. The owner downloads the original picture; the agent never fetches pages in bulk.

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

When the search ends, set the status to `done` and write a last note on what the result owes to understanding, to composition and to search. The page draws the chain from the starting point to the best arrangement, labels each link with its method, lists the programs with their code, and shows the journal in order, with dead ends muted. Sessions written before steps and methods existed show their improvements as the chain, without labels. A session that led nowhere can be deleted from the tab: its folder moves to `runs/research/deleted/`, out of the listing, and moving it back by hand restores it.

The two record hunts below ship as example sessions in `examples/research/`, reconstructed afterwards from the hunt's log before steps and methods existed. `paper-obs serve` copies them into the runs folder once, as it does the example runs.

## 5. Before claiming a record

1. The engine judges the arrangement valid when it is submitted. Keep a small safety margin, for example a scale shrunk by `1e-9` relative, so that a contact closed exactly by an optimiser stays legal.
2. Check independently: `paper-obs research verify` decides in exact rational arithmetic, apart from the engine's predicates.
3. Published values are truncated, so `1.499+` means at least 1.499. A claim must be strictly better than the printed digits.
4. Re-read the live page on the day of the claim, and note the date in the session.
5. Keep the code that produced the result in `work/`, with a `program` note for each file and the `--program` of each submission.

## 6. Submitting to the source

Only the owner contacts Erich Friedman; the agent prepares the material in a private folder (the owner's is `.private/submissions/`, ignored by Git) and never sends anything. Keep it to the essentials, since the owner writes the email: per record the page, the count, the previous and new values, a one-line method, the picture from `paper-obs research picture`, the candidate and the `verify` output. The Packing Center asks for an email with:

1. a descriptive title, in a new email rather than a reply to an earlier exchange;
2. a picture of the packing in the same orientation, colours, pixel size, file type and name as the picture it replaces, with no border or text. In the "Maximize Total Perimeter" pages, any rainbow palette in which close sizes get close colours is accepted;
3. the radius or side length to 5 decimal places, and the exact value if possible;
4. the submitter's full name, for attribution;
5. for a new submitter, a description of the program or method used.

Extending an existing table is accepted only up to n = 50. A large batch is sorted by page into named folders, with the values in one text file per page or in the email itself.

## 7. What has worked so far

These are observations from the first record hunt, not rules:

- **Extend a construction family.** Published records come in families: square-in-triangle sides of the form k + 2/√3, k + 0.30122 and so on. A recent record that breaks a family's pattern can be beaten by extending the family by one step. This is how n = 38 squares in a triangle went from 10.304 to 10.30122.
- **Look for dissections.** A tan is two tans 1/√2 its size, a unit octagon holds a unit circle, a triangle of side 2s is four triangles of side s, and so on. Each fact turns one published record into a construction for another entry. An exact refinement of the assembled arrangement then helps, because the internal cuts are not walls. This is how n = 26 tans in an L went from 2.12132 to 2.12043.
- **Start from published figures.** Reading the copies' centres and angles off a figure, then refining exactly (maximise the scale with fixed contacts), recovered every square-in-triangle record to about 1e-12. It gives exact coordinates of current records as seeds.
- **Calibrate before believing a search.** Random restarts, corner-block seeds and ruin-and-recreate did not rediscover recent records for n ≈ 20 to 26 squares in a triangle in 20 minutes. Ideas beat brute force there.
