# Provenance — what came from Graft/Trail-Code, and under which license

This page records the upstream project behind the graph ideas in `./vr explore`, what we merged,
what we deliberately did **not** take, and the license position. It is written so a reviewer can
check the claim instead of trusting it.

## Upstream

| | |
|---|---|
| Project | **Trail-Code** (formerly published as **Graft**) by Trail |
| Repository | <https://github.com/trailhq/Trail-Code> |
| License | **MIT** — “Copyright (c) 2026 Context Graph Engine contributors” |
| Version looked at | CLI `0.30.5` (`@trailhq/trail-code`), read on 2026-11-17 |
| Docs read | `README.md`, `docs/006-deployment.md`, `LICENSE` |

Graft is a code map + learnings layer for coding agents: a ranked call graph (`hubs`, `callers`,
`impact`, `skeleton`), an LLM-written concept map, a `.trail/` learnings store, MCP access and
agent hooks. We evaluated it on this machine and kept the parts that fit Vibe Rescue's
“offline first, evidence labelled, no unattended repair” design.

## What we merged (idea → our implementation)

| Graft capability | Vibe Rescue | Where | Original code? |
|---|---|---|---|
| Ranked graph (`hubs`, `hotspots`) | `hubs` / `hotspots` + PageRank | `scripts/graph_query.py` | yes — our own ranking code |
| `callers` / `callees` / `impact` / `skeleton` | same four queries | `scripts/graph_query.py` | yes — our own BFS/AST code |
| Concept map | **call-graph clusters** (deterministic label propagation), no LLM | `Graph.clusters`, `graph/INDEX.md` | yes — our algorithm |
| Compact agent context | `graph/CONTEXT.md`, written by `./vr explore` | `render_context` | yes — our template |
| Learnings (`.trail/`) | `VIBE_RESCUE/learnings/` + `./vr note`, `./vr learnings --check` | `scripts/learnings.py` | yes — our JSONL/markdown store |
| Token-savings framing | kept as a design goal, not as a claim | `docs/GRAPH_QUERIES.md` | n/a |

## What we did not take

- **No source code, prompts, assets or tests** from Graft/Trail-Code were copied. The modules above
  were written for this repository against the existing atlas data model.
- **No LLM “deep” synthesis.** Vibe Rescue already has an explicit AI step (`./vr report`/`fix`)
  with owner approval; a hidden LLM pass would contradict that.
- **No MCP server, agent hooks, statusline injection or telemetry.** Those change the developer’s
  environment; Vibe Rescue writes only inside `VIBE_RESCUE/`.
- **No account or cloud coupling** — everything here is local and offline.

## License position

- Upstream is MIT; this repository is MIT (`LICENSE`). MIT permits reuse and derivative works,
  and requires the upstream copyright notice and permission text only when a **copy or substantial
  portion** of the software is included.
- We copied no code or text, so no upstream notice is legally required in `LICENSE`. This page is
  the attribution we choose to keep anyway, because the design ideas came from reading their
  public documentation and running their CLI.
- If a future change does copy code from Trail-Code/Graft (or any MIT project), it must carry the
  upstream copyright line and the MIT permission text in this file (or `THIRD_PARTY_NOTICES.md`),
  and the copied block must be marked in the source.

## How this was audited

1. `rg -n "graft|trailhq|trail-code" scripts/ tests/ docs/` — the only hits are this page and the
   provenance note in `scripts/learnings.py`; no imported identifiers, templates or comments.
2. `git diff --stat` of the merge commit: new files are `graph_query.py`, `learnings.py`,
   `tests/test_graph_query.py`, `tests/test_learnings.py`, this page; edits are additive
   (`logic_atlas.py`, `vr.py`).
3. Tests: 176 passed, 8 skipped (`tests/test_v02_semgrep.py` excluded — semgrep is not installed in
   the test environment on this machine, the pre-existing gap recorded in `STATUS.md`). `ruff check`
   is clean on every file this merge touched.
4. Behaviour was compared on the same repository: Graft reported 1,524 symbols / 3,730 edges on
   `medlc_redteam`; the Vibe Rescue atlas graph for the same tree is queryable with the same
   questions (`hubs`, `callers`, `impact`, `skeleton`), and its output was checked by hand against
   `medlc_redteam`'s source.

## Reproducing the comparison

```bash
# Upstream, for reading only (installed on this machine):
npm install -g @trailhq/trail-code
trail --dir /tmp/graft-demo build path/to/repo

# Ours:
PATH=~/miniconda3/bin:$PATH ./vr explore path/to/repo
python scripts/graph_query.py hubs --atlas path/to/repo/VIBE_RESCUE/atlas
```

---

**Tóm tắt (tiếng Việt).** Ý tưởng graph xếp hạng, `callers`/`impact`/`skeleton`, concept map, context
cho agent và learnings học từ **Trail-Code (trước là Graft)** — MIT, copyright 2026 Context Graph
Engine contributors. Chúng tôi **không copy code/prompt/asset** nào; toàn bộ implementation viết mới
trên dữ liệu atlas sẵn có, nên không phát sinh nghĩa vụ chèn notice của MIT. Trang này giữ attribution
tự nguyện và ghi rõ quy trình audit để người review kiểm lại được.
