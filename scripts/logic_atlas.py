#!/usr/bin/env python3
"""Local, evidence-labelled language graphs for one tracked repository scope."""
import argparse
import datetime
import json
import re
import shutil
import subprocess
import sys
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.atlas_render import write_graph
from tools.meta.redact import mask_text

EXTS = {
    "python": {".py", ".pyi"},
    "frontend": {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte"},
    "rust": {".rs"},
    "go": {".go"},
    "java": {".java"},
    "csharp": {".cs"},
    "php": {".php"},
}
OTHER_CODE_EXTS = {".c", ".cc", ".cpp", ".h", ".hpp", ".kt", ".kts", ".swift",
                   ".rb", ".scala", ".sc", ".dart", ".ex", ".exs", ".lua",
                   ".hs", ".zig", ".m", ".mm", ".pyx", ".sh", ".bash"}
ASSET_SKIP_DIRS = {"audit_claude", "logs_audit", "test_e2e", "tokenizer", "corpora",
                   "attachments", "artifacts", "evidence", "VIBE_RESCUE"}


def manifest():
    with (ROOT / "tools" / "manifest.toml").open("rb") as fh:
        return tomllib.load(fh)


def _git(target, *args):
    result = subprocess.run(["git", "-C", str(target), *args], capture_output=True,
                            text=True, check=False, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"[WHAT] git {' '.join(args)} lỗi: {result.stderr[:200]}")
    return result.stdout.strip()


def resolve_scope(target, value):
    path = (target / value).resolve()
    try:
        path.relative_to(target)
    except ValueError as exc:
        raise ValueError("[WHAT] --scope phải nằm trong target") from exc
    if not path.exists():
        raise ValueError(f"[WHAT] --scope không tồn tại: {value}")
    return path


def tracked_files(target, scope, with_skipped=False):
    rel = scope.relative_to(target)
    result = subprocess.run(["git", "-C", str(target), "ls-files", "-z", "--", str(rel)],
                            capture_output=True, check=False, timeout=60)
    if result.returncode != 0:
        raise RuntimeError("[WHAT] không đọc được git ls-files")
    paths = [Path(p.decode("utf-8", errors="replace")) for p in result.stdout.split(b"\0") if p]
    safe = [p for p in paths if (target / p).is_file() and not (target / p).is_symlink()
            and (target / p).resolve().is_relative_to(target.resolve())]
    return (safe, [str(p) for p in paths if p not in safe]) if with_skipped else safe


def classify(files):
    return {lang: [p for p in files if p.suffix.lower() in exts]
            for lang, exts in EXTS.items()}


def write_assets(files, outdir):
    """Path-only inventory of contracts that a source call graph cannot explain."""
    groups = {name: [] for name in ("rules", "prompts", "configs", "pipelines", "harness")}
    skipped = 0
    for path in files:
        if any(part in ASSET_SKIP_DIRS for part in path.parts):
            skipped += 1
            continue
        name = path.name.lower()
        whole = str(path).lower()
        if name in {"agents.md", "claude.md", "kimi.md", "gemini.md", "skill.md",
                    "codex.md", ".cursorrules"}:
            groups["rules"].append(str(path))
        if "prompt" in name or path.suffix.lower() in {".jinja", ".j2", ".tmpl"}:
            groups["prompts"].append(str(path))
        if "config" in name or path.suffix.lower() in {".yaml", ".yml", ".toml", ".ini", ".cfg"}:
            groups["configs"].append(str(path))
        if "pipeline" in whole or "orchestrat" in whole:
            groups["pipelines"].append(str(path))
        if "harness" in whole:
            groups["harness"].append(str(path))
    (outdir / "ASSETS.json").write_text(json.dumps({"groups": groups,
        "excluded_paths": skipped, "method": "Git-tracked path metadata only; no asset content read"},
        ensure_ascii=False, indent=1), encoding="utf-8")
    lines = ["# Asset inventory", "",
             "Git-tracked paths only. Content, freshness, active wiring, and contradictions are not verified.", ""]
    for name, paths in groups.items():
        lines.extend([f"## {name} ({len(paths)})", ""])
        lines.extend(f"- `{path}`" for path in paths)
        lines.append("")
    (outdir / "ASSETS.md").write_text("\n".join(lines), encoding="utf-8")
    return {"artifact": "ASSETS.md", "counts": {name: len(paths) for name, paths in groups.items()},
            "excluded_paths": skipped}


def _run(args, cwd, output, timeout, env=None):
    try:
        result = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                                check=False, timeout=timeout, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "failed", "reason": str(exc)[:250]}
    if result.returncode != 0:
        return {"status": "failed", "reason": mask_text(result.stderr[-500:])}
    if not result.stdout.strip():
        return {"status": "failed", "reason": "tool không tạo graph"}
    if len(result.stdout) > 5_000_000:
        return {"status": "failed", "reason": "graph >5 MB; thu hẹp --scope"}
    output.write_text(mask_text(result.stdout.replace(str(cwd) + "/", "")), encoding="utf-8")
    return {"status": "ok", "artifact": output.name}


def _pyan_graph(dot):
    nodes, edges = [], []
    node_re = re.compile(r'^\s*"([^"]+)" \[label="([^"]+)".*tooltip="((?:\\.|[^"])*)"')
    edge_re = re.compile(r'^\s*"([^"]+)" -> "([^"]+)"')
    for line in dot.splitlines():
        found = node_re.match(line)
        if found:
            symbol_id, label, raw = found.groups()
            try:
                tooltip = json.loads('"' + raw + '"')
            except json.JSONDecodeError:
                tooltip = ""
            source = next((p for p in tooltip.splitlines() if ".py:" in p or p.endswith(".py")), "")
            file, sep, lineno = source.partition(":")
            nodes.append({"id": symbol_id, "label": label, "file": file,
                          "line": int(lineno) if sep and lineno.isdigit() else None,
                          "kind": "pyan syntax symbol"})
        found = edge_re.match(line)
        if found:
            edges.append({"source": found.group(1), "target": found.group(2),
                          "kind": "Pyan static uses"})
    return {"nodes": nodes, "edges": edges, "unknown": [],
            "evidence": "Pyan static uses; dynamic dispatch unverified"}


def _python_cmd(paths, cfg):
    version = cfg["logic_map"]["packages"]["pyan3"]
    return ["uvx", "--from", f"pyan3=={version}", "pyan3",
            *[f"./{p}" for p in paths], "--uses", "--no-defines", "--depth", "2", "--dot"]


def _python_partitions(paths, prefix, max_files):
    """Keep related files together, then bisect only when one group is still huge."""
    if len(paths) <= max_files:
        return [paths]
    groups = {}
    for path in paths:
        rest = path.relative_to(prefix).parts
        groups.setdefault(rest[0], []).append(path)
    if len(groups) == 1:
        half = len(paths) // 2
        return (_python_partitions(paths[:half], prefix, max_files)
                + _python_partitions(paths[half:], prefix, max_files))
    return [part for name, group in sorted(groups.items())
            for part in _python_partitions(group, prefix / name, max_files)]


def _python_shards(paths, target, scope, outdir, cfg, max_files, timeout, pdf):
    """Map every tracked Python file even when one Pyan graph exceeds 5 MB."""
    shard_root = outdir / "python-shards"
    shard_root.mkdir(parents=True, exist_ok=True)
    planned = _python_partitions(sorted(paths), scope.relative_to(target), max_files)

    def one(group, folder):
        folder.mkdir(parents=True, exist_ok=True)
        output = folder / "python-calls.dot"
        run = _run(_python_cmd(group, cfg), target, output, timeout)
        if run["status"] == "failed" and run.get("reason") == "graph >5 MB; thu hẹp --scope" \
                and len(group) > 1:
            half = len(group) // 2
            return (one(group[:half], folder / "part-1")
                    + one(group[half:], folder / "part-2"))
        record = {"files": len(group), "first_file": str(group[0]),
                  "last_file": str(group[-1]), "status": run["status"],
                  "directory": str(folder.relative_to(outdir))}
        if run["status"] == "ok":
            graph = _pyan_graph(output.read_text(encoding="utf-8"))
            record["view"] = write_graph(graph, f"{target.name} · Python",
                                         folder, "python-map", pdf=pdf)
            if not graph["nodes"]:
                record["status"] = "partial"
                record["reason"] = "parser không trích được symbol nào"
        else:
            record["reason"] = run.get("reason", "tool failed")
        return [record]

    with ThreadPoolExecutor(max_workers=min(4, len(planned))) as pool:
        futures = [pool.submit(one, group, shard_root / f"shard-{idx:03d}")
                   for idx, group in enumerate(planned, 1)]
        records = [record for future in futures for record in future.result()]
    mapped = sum(x["files"] for x in records if x["status"] == "ok")
    failed = sum(x["files"] for x in records if x["status"] != "ok")
    rows = ["# Python atlas shards", "",
            ("All tracked Python files are assigned to a shard. Function calls across "
             "shards are not resolved; inspect the combined import graph separately."), "",
            "| First file | Files | Status | HTML | SVG pages |", "| --- | ---: | --- | --- | --- |"]
    for item in records:
        view = item.get("view", {})
        folder = item["directory"].removeprefix("python-shards/")
        html = f"[{view['html']}]({folder}/{view['html']})" if view.get("html") else item.get("reason", "")
        pages = view.get("svg_pages", [])
        svg = ", ".join(f"[{i + 1}]({folder}/{name})" for i, name in enumerate(pages))
        rows.append(f"| `{item['first_file']}` | {item['files']} | {item['status']} | {html} | {svg} |")
    (shard_root / "INDEX.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
    (outdir / "python-shards.json").write_text(json.dumps(records, ensure_ascii=False, indent=1),
                                                 encoding="utf-8")
    return {"status": "partial" if failed == 0 else "failed",
            "reason": "sharded graph; cross-shard function calls unresolved" if failed == 0
                      else f"{failed} Python files lacked a complete shard map",
            "artifact": "python-shards/INDEX.md", "shards": len(records),
            "mapped_files": mapped, "unmapped_files": failed}


def _frontend_graph(raw, files):
    data = json.loads(raw)
    allowed = {str(p) for p in files}
    nodes = [{"id": p, "label": Path(p).name, "file": p, "kind": "file"}
             for p in sorted(allowed)]
    edges, unknown = [], []
    for module in data.get("modules", []):
        source = module.get("source", "")
        if source not in allowed:
            continue
        for dep in module.get("dependencies", []):
            target = dep.get("resolved", "")
            if dep.get("couldNotResolve") or target not in allowed:
                unknown.append({"file": source, "import": dep.get("module", ""),
                                "reason": "unresolved or outside scope"})
            else:
                edges.append({"source": source, "target": target, "kind": "static import"})
    return {"nodes": nodes, "edges": edges, "unknown": unknown,
            "evidence": "dependency-cruiser static imports; target config disabled"}


def _run_frontend(target, paths, output, timeout, cfg):
    version = cfg["core"]["js"]["dependency-cruiser"]
    ts_version = cfg["logic_map"]["packages"]["typescript"]
    cmd = ["npx", "-y", "-p", f"dependency-cruiser@{version}",
           "-p", f"typescript@{ts_version}", "depcruise",
           *[f"./{p}" for p in paths], "--output-type", "json", "--no-config"]
    try:
        run = subprocess.run(cmd, cwd=target, capture_output=True, text=True,
                             timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "failed", "reason": str(exc)[:250]}, None
    if run.returncode != 0:
        return {"status": "failed", "reason": mask_text(run.stderr[-500:])}, None
    try:
        graph = _frontend_graph(run.stdout, paths)
    except (ValueError, KeyError) as exc:
        return {"status": "failed", "reason": f"JSON parser lỗi: {exc}"}, None
    output.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    unsupported = [str(p) for p in paths if p.suffix in {".vue", ".svelte"}]
    partial = bool(graph["unknown"] or unsupported)
    return {"status": "partial" if partial else "ok", "artifact": output.name,
            "unresolved": len(graph["unknown"]), "unsupported": unsupported}, graph


def generate(target, scope, outdir, max_files=400, timeout=180, inventory_only=False,
             pdf=False):
    files, skipped = tracked_files(target, scope, with_skipped=True)
    groups = classify(files)
    mapped = {p for paths in groups.values() for p in paths}
    unmapped = [str(p) for p in files if p not in mapped and p.suffix.lower() in OTHER_CODE_EXTS]
    outdir.mkdir(parents=True, exist_ok=True)
    assets = write_assets(files, outdir)
    cfg = manifest()
    tools = {}
    if not inventory_only:
        for lang, paths in groups.items():
            if not paths:
                continue
            if len(paths) > max_files and lang != "python":
                tools[lang] = {"status": "too_large", "reason": f"{len(paths)} files; chia --scope"}
                continue
            graph = None
            if lang == "python":
                if len(paths) > max_files:
                    tools[lang] = _python_shards(paths, target, scope, outdir, cfg,
                                                 max_files, timeout, pdf)
                    continue
                cmd = _python_cmd(paths, cfg)
                output = outdir / "python-calls.dot"
            elif lang == "frontend":
                if not shutil.which("npx"):
                    tools[lang] = {"status": "unavailable", "reason": "thiếu npx"}
                else:
                    output = outdir / "frontend-dependencies.json"
                    tools[lang], graph = _run_frontend(target, paths, output, timeout, cfg)
            else:
                try:
                    from scripts.syntax_map import extract
                    graph = extract(target, paths, lang)
                    output = outdir / f"{lang}-syntax.json"
                    output.write_text(json.dumps(graph, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
                    tools[lang] = {"status": "partial" if graph["unknown"] else "ok",
                                   "artifact": output.name,
                                   "unknown_calls": len(graph["unknown"])}
                except (ImportError, LookupError) as exc:
                    tools[lang] = {"status": "unavailable", "reason": str(exc)[:200]}
            if lang == "python":
                if not shutil.which(cmd[0]):
                    tools[lang] = {"status": "unavailable", "reason": f"thiếu {cmd[0]}"}
                    continue
                tools[lang] = _run(cmd, target, output, timeout)
                if tools[lang]["status"] == "failed" and tools[lang].get("reason") \
                        == "graph >5 MB; thu hẹp --scope" and len(paths) > 1:
                    tools[lang] = _python_shards(paths, target, scope, outdir, cfg,
                                                 max_files, timeout, pdf)
                    continue
                if tools[lang]["status"] == "ok":
                    graph = _pyan_graph(output.read_text(encoding="utf-8"))
                    # Persist the parsed graph so graph_query.py can rank/query it without re-running Pyan.
                    (outdir / "python-graph.json").write_text(
                        json.dumps(graph, ensure_ascii=False, indent=1), encoding="utf-8")
                    tools[lang]["graph"] = "python-graph.json"
            if graph is not None and tools[lang]["status"] in {"ok", "partial"}:
                view = write_graph(graph, f"{target.name} · {lang}", outdir,
                                   f"{lang}-map", pdf=pdf)
                tools[lang]["view"] = view
                if not graph["nodes"]:
                    tools[lang]["status"] = "partial"
                    tools[lang]["reason"] = "parser không trích được symbol nào"
                if view["truncated"]:
                    tools[lang]["status"] = "partial"
                if pdf and "pdf" not in view:
                    tools[lang]["status"] = "partial"
            if lang == "frontend":
                try:
                    from scripts.syntax_map import extract
                    symbols = extract(target, paths, "frontend")
                    symbol_out = outdir / "frontend-symbols.json"
                    symbol_out.write_text(json.dumps(symbols, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
                    symbol_view = write_graph(symbols, f"{target.name} · frontend functions",
                                              outdir, "frontend-functions", pdf=pdf)
                    partial = (bool(symbols["unknown"]) or not symbols["nodes"]
                               or symbol_view["truncated"] or (pdf and "pdf" not in symbol_view))
                    tools["frontend_symbols"] = {"status": "partial" if partial else "ok",
                                                 "artifact": symbol_out.name,
                                                 "unknown_calls": len(symbols["unknown"]),
                                                 "view": symbol_view}
                except (ImportError, LookupError) as exc:
                    tools["frontend_symbols"] = {"status": "unavailable",
                                                 "reason": str(exc)[:200]}
    if not inventory_only and unmapped:
        tools["other"] = {"status": "unmapped", "reason": f"{len(unmapped)} code files ngoài parser hiện có",
                          "sample": unmapped[:20]}
    if not inventory_only and not tools:
        tools["scope"] = {"status": "empty", "reason": "scope không có source file được hỗ trợ"}
    if skipped:
        tools["safety"] = {"status": "skipped", "reason": f"{len(skipped)} tracked path là symlink/không an toàn",
                           "sample": skipped[:20]}
    head = _git(target, "rev-parse", "HEAD")
    dirty = [line for line in _git(target, "status", "--porcelain", "--untracked-files=no").splitlines()
             if line]
    result = {"target": str(target), "scope": str(scope.relative_to(target)), "head": head,
              "tracked_files": len(files), "language_files": {k: len(v) for k, v in groups.items()},
              "unmapped_code_files": len(unmapped),
              "skipped_tracked_paths": len(skipped),
              "tracked_changes": len(dirty), "tools": tools,
              "assets": assets,
              "source": "static analysis of tracked working tree; runtime branches unverified"}
    (outdir / "manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                            encoding="utf-8")
    rows = []
    for lang, data in tools.items():
        artifact = f"[{data['artifact']}]({data['artifact']})" if data.get("artifact") else data.get("reason", "")
        if data.get("view"):
            view = data["view"]
            artifact += (f" · [HTML]({view['html']}) · [SVG]({view['svg']})"
                         + (f" · [PDF]({view['pdf']})" if view.get("pdf") else ""))
            pages = view.get("svg_pages", [])
            if len(pages) > 1:
                artifact += f" · {len(pages)} SVG pages linked from HTML"
            if view.get("pdf_error"):
                artifact += " · PDF unavailable"
        rows.append(f"| {lang} | {data['status']} | {artifact} |")
    (outdir / "INDEX.md").write_text("\n".join([
        f"# Logic atlas — {target.name}", "",
        f"- Commit: `{head}`", f"- Scope: `{result['scope']}`",
        f"- Tracked changes since HEAD: {len(dirty)} (0 = graph đúng snapshot commit).",
        (f"- Tracked files: {len(files)}; " + ", ".join(f"{k} {len(v)}" for k, v in groups.items()) + "."),
        "- [Config, prompt, pipeline, and harness path inventory](ASSETS.md).",
        "- Mũi tên trong graph là phân tích tĩnh; chưa chứng minh nhánh runtime.",
        "", "| Nhóm | Trạng thái | Evidence |", "|---|---|---|", *rows, "",
        ("Dùng [journey template](JOURNEY_TEMPLATE.md) để nối UI → API → service → dữ liệu "
         "và xác nhận bằng trace/test. Không gọi atlas này là toàn bộ logic khi còn unknown."), "",
    ]), encoding="utf-8")
    template = ROOT / "docs" / "JOURNEY_TEMPLATE.md"
    if template.is_file():
        (outdir / "JOURNEY_TEMPLATE.md").write_text(template.read_text(encoding="utf-8"),
                                                     encoding="utf-8")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Bản đồ tĩnh đa ngôn ngữ; không gọi LLM.")
    parser.add_argument("--target", required=True)
    parser.add_argument("--scope", default=".", help="thư mục/file cần đào; mặc định repo root")
    parser.add_argument("--outdir", help="mặc định reports/logic-atlas/<repo>-<UTC>")
    parser.add_argument("--max-files", type=int, default=400)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--inventory-only", action="store_true")
    parser.add_argument("--pdf", action="store_true", help="thử xuất PDF bằng Chromium/Chrome")
    args = parser.parse_args(argv)
    target = Path(args.target).resolve()
    try:
        scope = resolve_scope(target, args.scope)
        if args.max_files < 1 or args.timeout < 1:
            parser.error("--max-files và --timeout phải > 0")
        stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
        outdir = Path(args.outdir).resolve() if args.outdir else \
            ROOT / "reports" / "logic-atlas" / f"{target.name}-{stamp}"
        result = generate(target, scope, outdir, args.max_files, args.timeout,
                          args.inventory_only, args.pdf)
    except (OSError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"[ATLAS] {outdir / 'INDEX.md'}")
    if any(v["status"] != "ok" for v in result["tools"].values()):
        print("[ATLAS] INCOMPLETE: xem manifest.json (không suy diễn graph thiếu)")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
