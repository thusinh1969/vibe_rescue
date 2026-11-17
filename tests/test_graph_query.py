"""Tests for the ranked graph queries that ./vr explore writes into graph/INDEX.md."""
import json

from scripts import graph_query


def _atlas(tmp_path, nodes, edges):
    atlas = tmp_path / "atlas"
    atlas.mkdir()
    (atlas / "python-graph.json").write_text(
        json.dumps({"nodes": nodes, "edges": edges}), encoding="utf-8")
    return atlas


def _graph(tmp_path):
    nodes = [
        {"id": "m.a", "label": "m.a", "file": "m.py", "line": 1,
         "kind": "pyan syntax symbol"},
        {"id": "m.b", "label": "m.b", "file": "m.py", "line": 10,
         "kind": "pyan syntax symbol"},
        {"id": "m.c", "label": "m.c", "file": "m.py", "line": 20,
         "kind": "pyan syntax symbol"},
    ]
    edges = [
        {"source": "m.b", "target": "m.a", "kind": "Pyan static uses"},
        {"source": "m.c", "target": "m.a", "kind": "Pyan static uses"},
        {"source": "m.c", "target": "m.b", "kind": "Pyan static uses"},
    ]
    return graph_query.load_graphs(_atlas(tmp_path, nodes, edges))[0]


def test_rank_callers_callees_and_impact(tmp_path):
    graph = _graph(tmp_path)
    assert graph.rank("in", 2) == ["m.a", "m.b"]
    assert graph.rank("out", 1) == ["m.c"]
    assert graph.callers("m.a") == ["m.b", "m.c"]
    assert graph.callees("m.c") == ["m.a", "m.b"]
    assert graph.impact("m.a", depth=2) == {1: ["m.b", "m.c"]}
    assert graph.match("b") == ["m.b"]


def test_pagerank_sums_to_one(tmp_path):
    graph = _graph(tmp_path)
    ranks = graph.pagerank()
    assert abs(sum(ranks.values()) - 1.0) < 1e-6
    assert ranks["m.a"] > ranks["m.b"]


def test_skeleton_lists_classes_and_signatures(tmp_path):
    source = tmp_path / "sample.py"
    source.write_text(
        "class A:\n"
        "    def m(self, x: int) -> str: ...\n"
        "\n"
        "def f(a, b=1):\n"
        "    return a\n",
        encoding="utf-8")
    rows = graph_query.skeleton_for(source)
    assert any("class A" in row for row in rows)
    assert any("def m(self, x: int) -> str" in row for row in rows)
    assert any("def f(a, b=1)" in row for row in rows)


def test_render_index_writes_markdown(tmp_path):
    atlas = _atlas(tmp_path, [
        {"id": "m.a", "label": "m.a", "file": "m.py", "line": 1},
        {"id": "m.b", "label": "m.b", "file": "m.py", "line": 2},
    ], [{"source": "m.b", "target": "m.a", "kind": "Pyan static uses"}])
    out = tmp_path / "graph" / "INDEX.md"
    text = graph_query.render_index(atlas, out)
    assert "Hubs (most callers)" in text
    assert "graph_query.py callers" in text
    assert out.exists()


def test_parse_dot_fallback():
    dot = (
        '"m.a" [label="a", color="black", tooltip="m.py:3"];\n'
        '"m.b" [label="b", color="black", tooltip="m.py:9"];\n'
        '"m.b" -> "m.a";\n'
    )
    nodes, edges = graph_query.parse_dot(dot)
    assert [n["id"] for n in nodes] == ["m.a", "m.b"]
    assert nodes[0]["file"] == "m.py" and nodes[0]["line"] == 3
    assert edges == [{"source": "m.b", "target": "m.a", "kind": "Pyan static uses"}]
