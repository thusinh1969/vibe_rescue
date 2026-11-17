# Graph queries — what a change can break

`./vr explore` already draws the atlas. This page covers the ranked call graph written next to it:
`VIBE_RESCUE/graph/INDEX.md`, built from the same static graph, offline and without AI.

The idea is borrowed from the "graft map" approach: an agent should read a **ranked** graph instead of
guessing which file matters. Hubs (most callers) are the symbols a change is most likely to break;
hotspots (most callees) are the symbols that fan out and are worth splitting.

## What is in `graph/INDEX.md`

- **Hubs** — the 15 symbols with the most callers per language, with `file:line` and a PageRank score.
- **Hotspots** — the 15 symbols that call the most other symbols.
- **Ask** — the four commands below, ready to copy.

## Ask the graph

From the repository that has the atlas:

```bash
python scripts/graph_query.py hubs    --atlas PROJECT/VIBE_RESCUE/atlas --top 20
python scripts/graph_query.py hotspots --atlas PROJECT/VIBE_RESCUE/atlas
python scripts/graph_query.py callers --atlas PROJECT/VIBE_RESCUE/atlas run_scan
python scripts/graph_query.py callees --atlas PROJECT/VIBE_RESCUE/atlas run_scan
python scripts/graph_query.py impact  --atlas PROJECT/VIBE_RESCUE/atlas run_scan --depth 3
python scripts/graph_query.py skeleton scripts/logic_atlas.py
```

`--json` on `hubs`, `hotspots`, `callers`, `callees` and `impact` prints machine-readable output for an
agent. `skeleton` reads one Python file and prints its classes and function signatures with line
numbers; it does not need an atlas.

## Clusters and the agent context page

`graph/INDEX.md` also lists call-graph **clusters** (deterministic label propagation over the same
edges), and `./vr explore` writes `graph/CONTEXT.md` — a compact page to paste into an AI before it
opens files: hubs, clusters and the four queries.

```bash
python scripts/graph_query.py clusters --atlas PROJECT/VIBE_RESCUE/atlas
python scripts/graph_query.py context  --atlas PROJECT/VIBE_RESCUE/atlas --repo my-repo
```

A cluster is a lead for "what belongs together", not a bounded-context claim; the label is the
dominant top-level directory, the hubs are its most-called members, and bridges are members with
edges to other clusters.

## Learnings — what the team worked out

Graft keeps a `.trail/` learnings store; Vibe Rescue keeps the same idea in
`VIBE_RESCUE/learnings/` (append-only `learnings.jsonl` + regenerated `LEARNINGS.md`):

```bash
./vr note "retry stays at 4 because the gateway idempotency key is per attempt"
./vr note "the nightly job owns the lock" --file src/jobs/nightly.py   # repeatable --file
./vr learnings                 # newest first
./vr learnings --check         # learnings that mention files you have changed
```

`--check` reads `git status --porcelain`; it is a reminder to read the note, not a gate. Notes carry
a UTC timestamp, the short git HEAD and the author, so a stale note is visible as stale.

## Evidence, and what it is not

The edges come from Pyan (Python) and tree-sitter (other languages): **static references**. Dynamic
dispatch, reflection, callbacks registered by name and framework routing are not resolved, and the atlas
marks those as unresolved where it can. A hub is a lead to read the source, not proof that a path runs.

## Where the ideas come from

See [PROVENANCE.md](PROVENANCE.md) for the upstream (Trail-Code/Graft, MIT), what we
re-implemented, and what we deliberately left out.

## Where the code comes from

- `scripts/logic_atlas.py` writes `atlas/python-graph.json` next to the DOT it already produced.
- `scripts/graph_query.py` ranks and queries it (standard library only).
- `scripts/vr.py` runs the index step during `./vr explore` and points `START_HERE.md` at `graph/INDEX.md`.

---

**Tóm tắt (tiếng Việt).** `./vr explore` ghi thêm `VIBE_RESCUE/graph/INDEX.md`: hub (bị gọi nhiều nhất),
hotspot (gọi nhiều nhất) và 4 lệnh hỏi nhanh `callers` / `callees` / `impact` / `skeleton`. Tất cả là
đồ thị tĩnh từ atlas, không AI, không mạng. Cạnh là tham chiếu tĩnh — dynamic dispatch và callback chưa
được giải, nên hub chỉ là gợi ý đọc source, không phải bằng chứng chạy.
