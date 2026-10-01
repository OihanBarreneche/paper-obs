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

## 4. Search freely, submit improvements

Candidates are the lab's JSON: `problem_id`, `scale` and `placements`, each with `shape_id`, `x`, `y` and `rotation` in degrees. They are written in the problem's own frame:

- **A fixed arena (`maximize_scale`):** the arena is the unit container and the copies share the scale `scale`. The container side the source publishes is the arena's `reference_length` (1 for every catalog arena) divided by `scale`.
- **A derived container (`minimize_container`):** the copies are unit copies, and the engine measures the smallest square or circle around them.

Useful commands:

```bash
paper-obs research submit <id> -c candidate.json --note "LNS from the x.301 seed"   # judged; exits 1 when invalid
paper-obs research note <id> "corner seeds never beat 7.6188 in 20 min: dropped"
paper-obs research status <id>                    # best so far and the record
paper-obs research status <id> --set paused       # active, paused or done
paper-obs evaluate -p problem.json -c candidate.json   # judge without logging
```

From Python, `paper_obs.research.submit(session_id, candidate, note)` does the same as the command, and `paper_obs.geometry.engine.evaluate` judges without logging. Submit each new best rather than every attempt: a session keeps the arrangement and full verdict of improvements only, and the measure of every submission.

Notes are what make a session readable afterwards. Write down the ideas tried, the dead ends and why, the method of each improvement, and the machine plan.

## 5. Before claiming a record

1. The engine judges the arrangement valid when it is submitted. Keep a small safety margin, for example a scale shrunk by `1e-9` relative, so that a contact closed exactly by an optimiser stays legal.
2. Check independently when possible, for instance with exact rational arithmetic on the vertices.
3. Published values are truncated, so `1.499+` means at least 1.499. A claim must be strictly better than the printed digits.
4. Re-read the live page on the day of the claim, and note the date in the session.
5. Keep the code that produced the result in `work/`, and summarise the method in a note.

## 6. Submitting to the source

Only the owner contacts Erich Friedman; the agent prepares the material in `work/submission/` and never sends anything. The Packing Center asks for an email with:

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
