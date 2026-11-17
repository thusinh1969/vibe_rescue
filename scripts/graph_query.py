"""Ranked queries over the static graph atlas: hubs, callers, callees, impact, skeleton.

The atlas stores static references (Pyan for Python, tree-sitter for other languages).
This module only ranks and queries that graph, offline and with the standard library:
an agent or a teammate asks "who calls this?" instead of guessing which file matters.

Vietnamese: truy vấn đồ thị tĩnh của atlas — hub, caller, callee, impact, skeleton.
Không AI, không mạng. Cạnh là tham chiếu tĩnh; dynamic dispatch chưa được kiểm chứng.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
from collections import Counter, defaultdict, deque
from pathlib import Path

NODE_RE = re.compile(r'^\s*"([^"]+)" \[label="([^"]+)".*tooltip="((?:\\.|[^"])*)"')
EDGE_RE = re.compile(r'^\s*"([^"]+)" -> "([^"]+)"')


def parse_dot(text: str) -> tuple[list[dict], list[dict]]:
    """Read the Pyan DOT that ``logic_atlas.py`` already writes, without importing it."""
    nodes, edges = [], []
    for line in text.splitlines():
        found = NODE_RE.match(line)
        if found:
            symbol_id, label, raw = found.groups()
            try:
                tooltip = json.loads('"' + raw + '"')
            except json.JSONDecodeError:
                tooltip = ""
            source = next((p for p in tooltip.splitlines()
                           if ".py:" in p or p.endswith(".py")), "")
            file, sep, lineno = source.partition(":")
            nodes.append({"id": symbol_id, "label": label, "file": file,
                          "line": int(lineno) if sep and lineno.isdigit() else None,
                          "kind": "pyan syntax symbol"})
        found = EDGE_RE.match(line)
        if found:
            edges.append({"source": found.group(1), "target": found.group(2),
                          "kind": "Pyan static uses"})
    return nodes, edges


class Graph:
    """One language's static call graph, indexed both ways."""

    def __init__(self, language: str, nodes: list[dict], edges: list[dict]):
        self.language = language
        self.nodes: dict[str, dict] = {}
        for node in nodes:
            node_id = str(node.get("id"))
            if not node_id:
                continue
            self.nodes[node_id] = {
                "id": node_id,
                "label": str(node.get("label") or node_id),
                "file": str(node.get("file") or ""),
                "line": node.get("line"),
                "kind": str(node.get("kind") or ""),
            }
        self.out: dict[str, set[str]] = defaultdict(set)
        self.inn: dict[str, set[str]] = defaultdict(set)
        for edge in edges:
            source, target = str(edge.get("source")), str(edge.get("target"))
            if source in self.nodes and target in self.nodes:
                self.out[source].add(target)
                self.inn[target].add(source)

    def rank(self, by: str = "in", top: int = 20) -> list[str]:
        if by == "in":
            key = lambda node_id: (len(self.inn[node_id]), len(self.out[node_id]))
        else:
            key = lambda node_id: (len(self.out[node_id]), len(self.inn[node_id]))
        return sorted(self.nodes, key=key, reverse=True)[:top]

    def pagerank(self, damping: float = 0.85, iterations: int = 40,
                 tolerance: float = 1e-10) -> dict[str, float]:
        count = len(self.nodes)
        if not count:
            return {}
        rank = {node_id: 1.0 / count for node_id in self.nodes}
        for _ in range(iterations):
            nxt = {node_id: (1.0 - damping) / count for node_id in self.nodes}
            dangling = sum(rank[n] for n in self.nodes if not self.out[n])
            for node_id in self.nodes:
                if not self.out[node_id]:
                    continue
                share = damping * rank[node_id] / len(self.out[node_id])
                for target in self.out[node_id]:
                    nxt[target] += share
            # Dangling nodes have no edge to follow: spread their mass evenly.
            if dangling:
                spread = damping * dangling / count
                for node_id in self.nodes:
                    nxt[node_id] += spread
            delta = sum(abs(nxt[n] - rank[n]) for n in self.nodes)
            rank = nxt
            if delta < tolerance:
                break
        return rank

    def match(self, query: str, limit: int = 10) -> list[str]:
        wanted = query.lower().strip()
        if not wanted:
            return []
        exact = [n for n in self.nodes if n.lower() == wanted]
        if exact:
            return exact[:limit]
        suffix = [n for n in self.nodes if n.lower().endswith(wanted)]
        if suffix:
            return sorted(suffix)[:limit]
        return [n for n in self.nodes
                if wanted in n.lower() or wanted in self.nodes[n]["label"].lower()][:limit]

    def callers(self, node_id: str) -> list[str]:
        return sorted(self.inn[node_id])

    def callees(self, node_id: str) -> list[str]:
        return sorted(self.out[node_id])

    def clusters(self, iterations: int = 25) -> list[dict]:
        """Group symbols into call-graph communities by deterministic label propagation.

        Offline and cheap: neighbours vote, ties go to the smallest label, so the same
        graph always yields the same clusters. A cluster is a lead for "what belongs
        together", not a bounded-context claim.
        """
        labels = {node_id: node_id for node_id in self.nodes}
        neighbours = {node_id: set(self.inn[node_id]) | set(self.out[node_id])
                      for node_id in self.nodes}
        order = sorted(self.nodes)
        for _ in range(iterations):
            changed = False
            for node_id in order:
                if not neighbours[node_id]:
                    continue
                counts = Counter(labels[other] for other in neighbours[node_id])
                best = min(counts.items(), key=lambda item: (-item[1], item[0]))[0]
                if labels[node_id] != best:
                    labels[node_id] = best
                    changed = True
            if not changed:
                break
        groups: dict[str, list[str]] = defaultdict(list)
        for node_id, label in labels.items():
            groups[label].append(node_id)
        result = []
        for members in groups.values():
            members = sorted(members)
            inside = set(members)
            bridges = sorted(
                node for node in members
                if any(other not in inside for other in self.out[node] | self.inn[node]))
            files = Counter(self.nodes[node]["file"].split("/")[0]
                            for node in members if self.nodes[node]["file"])
            result.append({
                "size": len(members),
                "files": [name for name, _ in files.most_common(3)],
                "members": members,
                "hubs": sorted(members, key=lambda n: len(self.inn[n]), reverse=True)[:5],
                "bridges": bridges[:5],
            })
        return sorted(result, key=lambda cluster: (-cluster["size"], cluster["members"][0]))

    def impact(self, node_id: str, depth: int = 3) -> dict[int, list[str]]:
        """Reverse BFS: who would feel a change here, level by level."""
        seen = {node_id}
        levels: dict[int, list[str]] = {}
        queue = deque([(node_id, 0)])
        while queue:
            current, level = queue.popleft()
            if level >= depth:
                continue
            for caller in self.inn[current]:
                if caller in seen:
                    continue
                seen.add(caller)
                levels.setdefault(level + 1, []).append(caller)
                queue.append((caller, level + 1))
        return {level: sorted(nodes) for level, nodes in sorted(levels.items())}


def load_graphs(atlas: Path) -> list[Graph]:
    """Load every graph the atlas wrote, preferring the JSON that this version records."""
    graphs: list[Graph] = []
    python_json = atlas / "python-graph.json"
    python_dot = atlas / "python-calls.dot"
    if python_json.exists():
        data = json.loads(python_json.read_text(encoding="utf-8"))
        graphs.append(Graph("python", data.get("nodes", []), data.get("edges", [])))
    elif python_dot.exists():
        nodes, edges = parse_dot(python_dot.read_text(encoding="utf-8"))
        graphs.append(Graph("python", nodes, edges))
    for path in sorted(atlas.glob("*-syntax.json")):
        if path.name == "frontend-symbols.json":
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        graphs.append(Graph(path.stem.removesuffix("-syntax"), data.get("nodes", []),
                            data.get("edges", [])))
    symbols = atlas / "frontend-symbols.json"
    if symbols.exists():
        data = json.loads(symbols.read_text(encoding="utf-8"))
        graphs.append(Graph("frontend", data.get("nodes", []), data.get("edges", [])))
    return [graph for graph in graphs if graph.nodes]


def describe(node: dict) -> str:
    where = node["file"] or "?"
    if node.get("line"):
        where += f":{node['line']}"
    return f"{node['label']} — {where}"


def skeleton_for(path: Path) -> list[str]:
    """A file's API in a few lines: classes, functions, signatures and line numbers."""
    source = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"! không parse được {path}: {exc.msg} (dòng {exc.lineno})"]
    rows = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
            args = ast.unparse(node.args)
            returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
            rows.append((node.lineno, f"L{node.lineno}  {prefix} {node.name}({args}){returns}"))
        elif isinstance(node, ast.ClassDef):
            bases = ", ".join(ast.unparse(base) for base in node.bases)
            rows.append((node.lineno, f"L{node.lineno}  class {node.name}" + (f"({bases})" if bases else "")))
    return [line for _, line in sorted(rows)]


def render_index(atlas: Path, out_path: Path, top: int = 15) -> str:
    graphs = load_graphs(atlas)
    lines = ["# Graph queries — static call graph", "",
             ("Ranked from the atlas graph: hubs (most called), hotspots (most fan-out) and the "
              "questions an agent should ask before changing a symbol."), "",
             ("Cạnh là tham chiếu tĩnh (Pyan/tree-sitter). Dynamic dispatch, reflection và callback "
              "chưa được kiểm chứng — dùng như gợi ý đọc source, không phải bằng chứng chạy."), ""]
    for graph in graphs:
        rank = graph.pagerank()
        lines += [(f"## {graph.language} — {len(graph.nodes)} symbols, "
                   f"{sum(len(v) for v in graph.out.values())} edges"), "",
                  "### Hubs (most callers)", ""]
        for node_id in graph.rank("in", top):
            node = graph.nodes[node_id]
            lines.append(f"- {describe(node)} — {len(graph.inn[node_id])} callers, "
                         f"pagerank {rank.get(node_id, 0):.4f}")
        lines += ["", "### Hotspots (most callees)", ""]
        for node_id in graph.rank("out", top):
            node = graph.nodes[node_id]
            lines.append(f"- {describe(node)} — calls {len(graph.out[node_id])}")
        lines += ["", "### Concepts (call-graph clusters)", ""]
        for cluster in graph.clusters()[:8]:
            hubs = ", ".join(graph.nodes[n]["label"] for n in cluster["hubs"][:3])
            where = "/".join(cluster["files"]) or "?"
            bridges = f"; {len(cluster['bridges'])} bridge(s)" if cluster["bridges"] else ""
            lines.append(f"- {where} — {cluster['size']} symbols{bridges}; hubs: {hubs}")
        lines.append("")
    lines += ["## Ask", "",
              "```bash",
              "python scripts/graph_query.py hubs    --atlas VIBE_RESCUE/atlas --top 20",
              "python scripts/graph_query.py callers --atlas VIBE_RESCUE/atlas run_scan",
              "python scripts/graph_query.py impact  --atlas VIBE_RESCUE/atlas run_scan --depth 3",
              "python scripts/graph_query.py skeleton scripts/logic_atlas.py",
              "```", ""]
    text = "\n".join(lines)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text + "\n", encoding="utf-8")
    return text


def render_context(atlas: Path, out_path: Path, repo: str = "",
                   top: int = 10, max_clusters: int = 6) -> str:
    """A compact context page an agent reads before opening any source file."""
    graphs = load_graphs(atlas)
    lines = [f"# Code context — {repo or 'this repository'}", "",
             ("Generated from the static atlas by ./vr explore. Read this before opening files; "
              "ask the graph instead of guessing. Static references only — dynamic dispatch and "
              "callbacks are not resolved."), ""]
    for graph in graphs:
        edges = sum(len(targets) for targets in graph.out.values())
        lines += [f"## {graph.language} — {len(graph.nodes)} symbols, {edges} edges", "",
                  "Hubs (most callers):"]
        for node_id in graph.rank("in", top):
            node = graph.nodes[node_id]
            lines.append(f"- {describe(node)} — {len(graph.inn[node_id])} callers")
        lines += ["", "Clusters:"]
        for cluster in graph.clusters()[:max_clusters]:
            hubs = ", ".join(graph.nodes[n]["label"] for n in cluster["hubs"][:3])
            where = "/".join(cluster["files"]) or "?"
            lines.append(f"- {where} — {cluster['size']} symbols; hubs: {hubs}")
        lines.append("")
    lines += ["## Ask", "", "```bash",
              "python scripts/graph_query.py hubs    --atlas VIBE_RESCUE/atlas --top 20",
              "python scripts/graph_query.py callers --atlas VIBE_RESCUE/atlas <symbol>",
              "python scripts/graph_query.py impact  --atlas VIBE_RESCUE/atlas <symbol> --depth 3",
              "python scripts/graph_query.py skeleton <file.py>",
              "```", ""]
    text = "\n".join(lines)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text + "\n", encoding="utf-8")
    return text


def _print_matches(graph: Graph, query: str, rows: list[str], title: str) -> int:
    print(f"{title}: {query}")
    if not rows:
        print("  (0 — không có cạnh nào trong đồ thị tĩnh; xem ghi chú evidence ở graph/INDEX.md)")
        return 0
    for row in rows:
        print(f"  {row}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ranked queries over the static atlas graph.")
    sub = parser.add_subparsers(dest="command", required=True)

    def atlas_arg(p: argparse.ArgumentParser) -> None:
        p.add_argument("--atlas", default="VIBE_RESCUE/atlas", type=Path)
        p.add_argument("--json", action="store_true")

    p_index = sub.add_parser("index", help="write graph/INDEX.md for ./vr explore")
    atlas_arg(p_index)
    p_index.add_argument("--out", type=Path, default=Path("VIBE_RESCUE/graph/INDEX.md"))
    p_index.add_argument("--top", type=int, default=15)

    p_context = sub.add_parser("context", help="write graph/CONTEXT.md for agents")
    atlas_arg(p_context)
    p_context.add_argument("--out", type=Path, default=Path("VIBE_RESCUE/graph/CONTEXT.md"))
    p_context.add_argument("--repo", default="")

    p_clusters = sub.add_parser("clusters", help="call-graph communities")
    atlas_arg(p_clusters)
    p_clusters.add_argument("--top", type=int, default=10)

    for name in ("hubs", "hotspots"):
        p = sub.add_parser(name)
        atlas_arg(p)
        p.add_argument("--top", type=int, default=20)

    for name in ("callers", "callees"):
        p = sub.add_parser(name)
        atlas_arg(p)
        p.add_argument("symbol")

    p_impact = sub.add_parser("impact")
    atlas_arg(p_impact)
    p_impact.add_argument("symbol")
    p_impact.add_argument("--depth", type=int, default=3)

    p_skel = sub.add_parser("skeleton")
    p_skel.add_argument("file", type=Path)

    args = parser.parse_args(argv)

    if args.command == "skeleton":
        rows = skeleton_for(args.file)
        print("\n".join(rows) if rows else f"{args.file}: không có class/function")
        return 0

    if args.command == "index":
        render_index(args.atlas, args.out, args.top)
        print(f"wrote {args.out}")
        return 0

    if args.command == "context":
        render_context(args.atlas, args.out, args.repo)
        print(f"wrote {args.out}")
        return 0

    graphs = load_graphs(args.atlas)
    if not graphs:
        print(f"không có graph trong {args.atlas} — chạy ./vr explore trước")
        return 2

    if args.command == "clusters":
        payload = {}
        for graph in graphs:
            payload[graph.language] = [
                {key: cluster[key] for key in ("size", "files", "bridges")}
                | {"hubs": [graph.nodes[n]["label"] for n in cluster["hubs"]]}
                for cluster in graph.clusters()[:args.top]]
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=1))
            return 0
        for language, clusters in payload.items():
            print(f"## {language}")
            for cluster in clusters:
                where = "/".join(cluster["files"]) or "?"
                print(f"  {where} — {cluster['size']} symbols; hubs: {', '.join(cluster['hubs'])}")
        return 0

    if args.command in ("hubs", "hotspots"):
        payload = {}
        for graph in graphs:
            ranked = graph.rank("in" if args.command == "hubs" else "out", args.top)
            payload[graph.language] = [graph.nodes[node_id] for node_id in ranked]
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=1))
            return 0
        for language, nodes in payload.items():
            print(f"## {language}")
            for node in nodes:
                degree = (f"{len(graph.inn[node['id']])} callers"
                          if args.command == "hubs" else
                          f"{len(graph.out[node['id']])} callees")
                print(f"  {describe(node)} — {degree}")
        return 0

    code = 2
    for graph in graphs:
        matches = graph.match(args.symbol)
        if not matches:
            continue
        for node_id in matches[:3]:
            node = graph.nodes[node_id]
            if args.command == "callers":
                rows = [describe(graph.nodes[n]) for n in graph.callers(node_id)]
                title = f"callers of {node['label']}"
            elif args.command == "callees":
                rows = [describe(graph.nodes[n]) for n in graph.callees(node_id)]
                title = f"callees of {node['label']}"
            else:
                levels = graph.impact(node_id, args.depth)
                rows = [f"depth {level}: " + ", ".join(graph.nodes[n]['label'] for n in nodes)
                        for level, nodes in levels.items()]
                title = f"impact of {node['label']}"
            if args.json:
                print(json.dumps({"symbol": node, "rows": rows}, ensure_ascii=False, indent=1))
                code = 0
                continue
            code = min(code, _print_matches(graph, node["label"], rows, title))
    if code == 2:
        print(f"không thấy symbol khớp {args.symbol!r} trong {args.atlas}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
