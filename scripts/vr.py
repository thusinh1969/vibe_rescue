#!/usr/bin/env python3
"""
vr.py - the one command of Vibe Rescue (start it through ./vr, which prepares the Python environment).

    ./vr doctor                 what is installed, what is missing, how to fix it
    ./vr explore [PROJECT]      map the project and write a team handoff           (no AI)
    ./vr check   [PROJECT]      find concrete problems with free checking tools     (no AI)
    ./vr report  [PROJECT]      an AI explains the findings in plain words           (needs an AI)
    ./vr fix     [PROJECT] --test "pytest -q"   plan, fix, second check; asks you at every step (needs an AI)
    ./vr ai claude | openai     write config.local.toml for the AI you chose (never stores a key)

Everything is written into PROJECT/VIBE_RESCUE/ (start with START_HERE.md). The folder carries its own
.gitignore, so the project's Git status stays clean. Nothing in the project's own files is changed.
This file only calls the existing scripts with one consistent set of options; their logic is untouched.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
PY_TOOLS = "ruff,vulture,radon,bandit"
OUT_NAME = "VIBE_RESCUE"


def say(msg=""):
    print(msg, flush=True)


def tool_env():
    """PATH with this environment's bin first, so the scripts find uv/uvx."""
    env = dict(os.environ)
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    return env


def git(project, *args):
    return subprocess.run(["git", "-C", str(project), *args], capture_output=True, text=True, check=False)


def resolve_project(arg):
    project = Path(arg).expanduser().resolve()
    if not project.is_dir():
        say(f"vr: '{arg}' is not a folder.")
        sys.exit(2)
    if git(project, "rev-parse", "--is-inside-work-tree").returncode != 0:
        say(f"vr: {project} is not a Git repository. Vibe Rescue reads Git-tracked files only.")
        say("    Fix: cd there and run   git init && git add -A && git commit -m 'before rescue'")
        sys.exit(2)
    return project


def out_dir(project):
    out = project / OUT_NAME
    out.mkdir(exist_ok=True)
    (out / ".gitignore").write_text("*\n", encoding="utf-8")       # the folder ignores itself: project Git status stays clean
    if (project / ".rescue").is_dir():
        (project / ".rescue" / ".gitignore").write_text("*\n", encoding="utf-8")
    return out


def has_python(project):
    return any(line.endswith(".py") for line in git(project, "ls-files").stdout.splitlines())


def step(label, cmd, log, ok_codes=(0,), env=None, stream=False):
    """Run one script. Quiet by default (full output goes to a log file); returns (ok, seconds, return code)."""
    t0 = time.time()
    if stream:
        rc = subprocess.run(cmd, env=env or tool_env(), check=False).returncode
    else:
        with open(log, "w", encoding="utf-8") as fh:
            rc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, env=env or tool_env(), check=False).returncode
    secs = time.time() - t0
    ok = rc in ok_codes
    say(f"  [{'ok' if ok else 'FAILED'}] {label} ({secs:.0f}s)" + ("" if ok else f"  exit {rc}, see {log}"))
    if not ok and not stream:
        tail = Path(log).read_text(encoding="utf-8", errors="replace").splitlines()[-12:]
        say("\n".join("      " + line for line in tail))
    return ok, secs, rc


# ------------------------------------------------------------------------------------------ START_HERE
def load_state(out):
    path = out / "state.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_state(out, state):
    (out / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    write_start_here(out, state)


def write_start_here(out, s):
    en, vi = ["# Start here", ""], ["# Bắt đầu từ đây", ""]
    ex, ck, rp = s.get("explore"), s.get("check"), s.get("report")
    if ex:
        en += ["## 1. The map (done)", f"- Python files: {ex.get('code_files', 'n/a')}, functional blocks: {ex.get('blocks', 'n/a')}, documented journeys: {ex.get('journeys', 'n/a')}.",
               "- Open `handoff.html` (English) or `handoff.vi.html` (Vietnamese). It is the packet to give a new teammate.",
               "- To work with an AI chat: paste `HANDOFF.md` into Claude, Codex or any model.",
               "- `atlas/INDEX.md` lists maps for every language found; `manifest.json` there says how complete they are.",
               "- `graph/INDEX.md` ranks the call graph (hubs, hotspots, clusters) and shows how to ask `callers` / `impact` before changing a symbol.",
               "- `graph/CONTEXT.md` is the compact context to paste into an AI before it explores this repository.", ""]
        vi += ["## 1. Bản đồ (đã xong)", f"- File Python: {ex.get('code_files', 'n/a')}, khối chức năng: {ex.get('blocks', 'n/a')}, hành trình có tài liệu: {ex.get('journeys', 'n/a')}.",
               "- Mở `handoff.vi.html` (tiếng Việt) hoặc `handoff.html` (tiếng Anh). Đây là bản bàn giao cho thành viên mới.",
               "- Muốn hỏi AI: dán `HANDOFF.md` vào Claude, Codex hoặc model bất kỳ.",
               "- `atlas/INDEX.md` liệt kê bản đồ cho mọi ngôn ngữ tìm thấy; `manifest.json` ở đó cho biết bản đồ đầy đủ đến đâu.",
               "- `graph/INDEX.md` xếp hạng đồ thị gọi (hub, hotspot, cluster) và chỉ cách hỏi `callers` / `impact` trước khi sửa một symbol.",
               "- `graph/CONTEXT.md` là context gọn để dán vào AI trước khi nó khám phá repo này.", ""]
    else:
        en += ["## 1. The map (not done yet)", "- Run `./vr explore PROJECT`.", ""]
        vi += ["## 1. Bản đồ (chưa chạy)", "- Chạy `./vr explore PROJECT`.", ""]
    if ck:
        c = ck.get("counts", {})
        en += ["## 2. Problems found (done)", f"- {ck.get('total', 0)} findings: " + (", ".join(f"{k} {v}" for k, v in c.items()) or "none") + ".",
               "- Read `check/findings.md`. A finding is evidence to look at, not proof of a bug."]
        vi += ["## 2. Vấn đề tìm thấy (đã xong)", f"- {ck.get('total', 0)} finding: " + (", ".join(f"{k} {v}" for k, v in c.items()) or "không có") + ".",
               "- Đọc `check/findings.md`. Một finding là bằng chứng để xem xét, không phải chứng minh có lỗi."]
        for line in ck.get("top", []):
            en.append("  " + line)
            vi.append("  " + line)
        if ck.get("not_checked"):
            en.append(f"- NOT checked (skipped or failed): {', '.join(ck['not_checked'])}. This is a gap, not a clean result.")
            vi.append(f"- CHƯA kiểm tra (bị bỏ qua hoặc lỗi): {', '.join(ck['not_checked'])}. Đây là khoảng trống, không phải kết quả sạch.")
        en.append("")
        vi.append("")
    else:
        en += ["## 2. Problems found (not done yet)", "- Run `./vr check PROJECT`.", ""]
        vi += ["## 2. Vấn đề tìm thấy (chưa chạy)", "- Chạy `./vr check PROJECT`.", ""]
    if rp:
        en += ["## 3. AI report (done)", f"- Written by an AI: {rp.get('agent_wrote')}. Read `report/README.md` (one page), then `report/PROPOSALS.md` (one card per problem).", ""]
        vi += ["## 3. Báo cáo AI (đã xong)", f"- Do AI viết: {rp.get('agent_wrote')}. Đọc `report/README.md` (một trang), rồi `report/PROPOSALS.md` (mỗi vấn đề một thẻ).", ""]
    else:
        en += ["## 3. AI report and fix (optional)", "- `./vr ai claude` or `./vr ai openai ...`, then `./vr report PROJECT` and `./vr fix PROJECT --test \"your test command\"`.", ""]
        vi += ["## 3. Báo cáo AI và sửa (tùy chọn)", "- `./vr ai claude` hoặc `./vr ai openai ...`, rồi `./vr report PROJECT` và `./vr fix PROJECT --test \"lệnh test của bạn\"`.", ""]
    try:
        sys.path.insert(0, str(ROOT))
        from scripts import learnings as _learnings
        notes = len(_learnings.load(out))
    except (ImportError, OSError):
        notes = 0
    if notes:
        en.append(f"- `learnings/LEARNINGS.md`: {notes} note(s) the team recorded; `./vr note` adds one.")
        vi.append(f"- `learnings/LEARNINGS.md`: {notes} ghi chú team đã lưu; `./vr note` để thêm.")
    (out / "START_HERE.md").write_text("\n".join(en) + "\n---\n\n" + "\n".join(vi) + "\n", encoding="utf-8")


# ------------------------------------------------------------------------------------------ commands
def cmd_doctor(_a):
    say("Vibe Rescue doctor\n")
    rows = []

    def row(name, ok, required, hint):
        rows.append(ok or not required)
        say(f"  {'OK      ' if ok else ('MISSING ' if required else 'optional')}  {name}" + ("" if ok else f"\n           {hint}"))
    row(f"Python {sys.version.split()[0]} (needs 3.11+)", sys.version_info >= (3, 11), True, "Install Python 3.11 or newer.")
    row("git", shutil.which("git") is not None, True, "Install Git.")
    env_path = tool_env()["PATH"]
    row("uv / uvx (runs the checking tools)", shutil.which("uvx", path=env_path) is not None, True, "Delete the .venv folder and run ./vr again.")
    try:
        import tree_sitter_language_pack  # noqa: F401
        ok_ts = True
    except ImportError:
        ok_ts = False
    row("tree-sitter-language-pack (maps for non-Python languages)", ok_ts, True, "Delete the .venv folder and run ./vr again.")
    row("node / npx (JavaScript and TypeScript maps)", shutil.which("npx") is not None, False, "Install Node.js only if the project has JS/TS code.")
    say("\n  AI (only for `report` and `fix`; maps and checks need none):")
    row("claude (Claude Code)", shutil.which("claude") is not None, False, "Option A. Install Claude Code and log in, then ./vr ai claude")
    row("codex (Codex)", shutil.which("codex") is not None, False, "Option A. Install Codex and log in (used as the second checker).")
    cfg = ROOT / "config.local.toml"
    row("config.local.toml (which AI plays which role)", cfg.exists(), False, "Run ./vr ai claude   or   ./vr ai openai --url URL --model MODEL")
    row("VIBE_AGENT_API_KEY set (only for option B, hosted OpenAI-style servers)", bool(os.environ.get("VIBE_AGENT_API_KEY")), False,
        "Option B. Type it into your terminal, never into a file:  read -rsp 'Key: ' VIBE_AGENT_API_KEY; export VIBE_AGENT_API_KEY")
    say("\n" + ("Ready: ./vr explore PROJECT" if all(rows) else "Fix the MISSING items above, then run ./vr doctor again."))
    return 0 if all(rows) else 2


def cmd_explore(a):
    project = resolve_project(a.project)
    out = out_dir(project)
    say(f"Exploring {project}\n  results: {out}")
    state = load_state(out)
    logs = out / "logs"
    logs.mkdir(exist_ok=True)
    ok1, _, rc1 = step("map of every language (atlas)", [sys.executable, str(SCRIPTS / "logic_atlas.py"), "--target", str(project), "--outdir", str(out / "atlas")],
                       logs / "atlas.log", ok_codes=(0, 2))
    if (out / "atlas").exists():
        step("graph queries: hubs, callers, impact (static)",
             [sys.executable, str(SCRIPTS / "graph_query.py"), "index",
              "--atlas", str(out / "atlas"), "--out", str(out / "graph" / "INDEX.md")],
             logs / "graph.log", ok_codes=(0, 2))
        step("agent context (graph/CONTEXT.md)",
             [sys.executable, str(SCRIPTS / "graph_query.py"), "context",
              "--atlas", str(out / "atlas"), "--out", str(out / "graph" / "CONTEXT.md"),
              "--repo", project.name],
             logs / "context.log", ok_codes=(0, 2))
    summary = {}
    if has_python(project):
        ok2, _, _ = step("team handoff and architecture map (Python)", [sys.executable, str(SCRIPTS / "repo_explorer.py"), "--generic", "--root", str(project), "--sources", ".",
                                                                       "--out", str(out / "source-explorer.html")], logs / "explorer.log", ok_codes=(0, 2))
        arch = out / "architecture.json"
        if ok2 and arch.exists():
            data = json.loads(arch.read_text(encoding="utf-8"))
            summary = {"code_files": data.get("coverage", {}).get("code_files"), "blocks": len(data.get("blocks", [])), "journeys": len(data.get("journeys", []))}
    else:
        ok2 = True
        say("  [skip] team handoff: this generic handoff covers Python only; see atlas/INDEX.md for the other languages")
    if ok1 and rc1 == 2:
        say("  note: the map is partial (exit code 2). Open atlas/manifest.json to see which parts are missing.")
    if ok1 and ok2:
        state["explore"] = summary or {"code_files": "n/a", "blocks": "n/a", "journeys": "n/a"}
        save_state(out, state)
        say(f"\nDone. Open {out / 'START_HERE.md'}")
        say("Next: ./vr check " + str(project))
        return 0
    return 1


def read_check(project, out):
    base = project / ".rescue" / "voyage"
    fj = base / "prove" / "findings.json"
    res = {"total": 0, "counts": {}, "top": [], "not_checked": []}
    if fj.exists():
        data = json.loads(fj.read_text(encoding="utf-8"))
        findings = data.get("findings", data if isinstance(data, list) else [])
        for f in findings:
            res["counts"][f.get("severity", "low")] = res["counts"].get(f.get("severity", "low"), 0) + 1
        res["total"] = len(findings)
        res["top"] = [f"- [{f.get('severity')}] {f.get('file')}:{f.get('line')} {f.get('rule')}: {str(f.get('message'))[:100]}" for f in findings[:5]]
        status = (data.get("meta", {}) if isinstance(data, dict) else {}).get("tool_status", {})
        res["not_checked"] = sorted(t for t, st in status.items() if st not in ("ok",))
    dest = out / "check"
    dest.mkdir(exist_ok=True)
    for name in ("findings.md", "run.summary.json"):
        if (base / "prove" / name).exists():
            shutil.copy(base / "prove" / name, dest / name)
    return res


def cmd_check(a):
    project = resolve_project(a.project)
    out = out_dir(project)
    tools = a.tools or (PY_TOOLS if has_python(project) else "")
    if not tools:
        say("vr: no Python files found, so there is no default set of checking tools. Choose some:  ./vr check PROJECT --tools jscpd,knip   (needs Node)")
        return 2
    say(f"Checking {project} with: {tools}\n  results: {out / 'check'}")
    (out / "logs").mkdir(exist_ok=True)
    ok, _, _ = step("map and find problems", [sys.executable, str(SCRIPTS / "rescue_voyage.py"), "--path", str(project), "--stages", "map,prove", "--tools", tools],
                    out / "logs" / "check.log", ok_codes=(0,))
    out_dir(project)                                    # .rescue/ exists now: make it ignore itself, also after a failure
    if not ok:
        return 1
    state = load_state(out)
    state["check"] = read_check(project, out)
    save_state(out, state)
    c = state["check"]
    say(f"\n{c['total']} findings." + (f" NOT checked: {', '.join(c['not_checked'])}." if c["not_checked"] else ""))
    say(f"Read {out / 'check' / 'findings.md'}  (summary: {out / 'START_HERE.md'})")
    say("The first run saves a baseline of today's problems; later runs show only what is new.")
    return 0


def ai_config():
    env_cfg = os.environ.get("VIBE_LLM_CONFIG")
    if env_cfg and Path(env_cfg).exists():
        return Path(env_cfg)
    cfg = ROOT / "config.local.toml"
    return cfg if cfg.exists() else None


def need_ai():
    cfg = ai_config()
    if cfg:
        return cfg
    say("vr: no AI is configured yet. Maps and checks need none; report and fix do. Pick one (about 1 minute):")
    say("  A) Claude Code (and Codex as the second checker), already installed and logged in:   ./vr ai claude")
    say("  B) any OpenAI-style server, open models you host or any hosted model:")
    say("       ./vr ai openai --url https://your-server/v1 --model YOUR-WRITER-MODEL --checker-model YOUR-OTHER-MODEL")
    say("       read -rsp 'Key: ' VIBE_AGENT_API_KEY; export VIBE_AGENT_API_KEY      (a local server may need no key)")
    say("  Then run this command again. ./vr doctor shows what is ready.")
    sys.exit(2)


def cmd_ai(a):
    cfg = ROOT / "config.local.toml"
    if cfg.exists() and not a.force:
        say(f"vr: {cfg} already exists. Use --force to overwrite it.")
        return 2
    if a.kind == "claude":
        body = "".join(f'[roles.{r}]\ncli = "{c}"\nmodel = ""\nextra_args = []\n\n' for r, c in (("write", "claude"), ("audit", "claude"), ("verify", "codex")))
    else:
        if not a.url or not a.model:
            say("vr: option B needs --url and --model (the exact id your server lists at /v1/models).")
            return 2
        checker = a.checker_model or a.model
        extra = f'["--base-url", "{a.url}"' + (', "--allow-http"]' if a.allow_http else "]")
        body = "".join(f'[roles.{r}]\ncli = "openai"\nmodel = "{m}"\nextra_args = {extra}\n\n' for r, m in (("write", a.model), ("audit", a.model), ("verify", checker)))
        if checker == a.model:
            say("note: writer and checker are the same model; a different model for --checker-model gives a real second opinion.")
    cfg.write_text(body, encoding="utf-8")
    say(f"Wrote {cfg} (no key inside; it is ignored by Git).")
    if a.kind == "openai":
        say("Now type the key into this terminal only (a local server may need none):")
        say("  read -rsp 'Key: ' VIBE_AGENT_API_KEY; export VIBE_AGENT_API_KEY")
    return 0


def voyage_env(cfg):
    env = tool_env()
    env["VIBE_LLM_CONFIG"] = str(cfg)
    return env


def cmd_report(a):
    cfg = need_ai()
    project = resolve_project(a.project)
    out = out_dir(project)
    tools = a.tools or (PY_TOOLS if has_python(project) else "ruff")
    say(f"AI report for {project}  (the AI you configured receives code and findings; stop now if that is not allowed)")
    (out / "logs").mkdir(exist_ok=True)
    log = out / "logs" / "report.log"
    ok, _, _ = step("map, find problems, AI report", [sys.executable, str(SCRIPTS / "rescue_voyage.py"), "--path", str(project), "--stages", "map,prove,review", "--tools", tools],
                    log, env=voyage_env(cfg))
    out_dir(project)
    if not ok:
        return 1
    review = project / ".rescue" / "voyage" / "review"
    dest = out / "report"
    dest.mkdir(exist_ok=True)
    for name in ("README.md", "PROPOSALS.md"):
        if (review / name).exists():
            shutil.copy(review / name, dest / name)
    if (review / "EVIDENCE").is_dir():
        shutil.copytree(review / "EVIDENCE", dest / "EVIDENCE", dirs_exist_ok=True)
    wrote = "agent_wrote=True" in log.read_text(encoding="utf-8", errors="replace")
    state = load_state(out)
    state["check"] = read_check(project, out)
    state["report"] = {"agent_wrote": wrote}
    save_state(out, state)
    say(f"\nAI wrote the report: {wrote}" + ("" if wrote else "  (False = a fill-in template from the machine results; check ./vr doctor and the AI setup)"))
    say(f"Read {dest / 'README.md'} then {dest / 'PROPOSALS.md'}")
    return 0 if wrote else 1


def cmd_fix(a):
    cfg = need_ai()
    project = resolve_project(a.project)
    out_dir(project)
    if not a.test:
        say('vr: fix needs a safety command that proves the project works today, for example:  ./vr fix PROJECT --test "python -m pytest -q"')
        say("    It must pass BEFORE any change and must not leave new files behind (for example __pycache__/); add those to the project's .gitignore.")
        return 2
    tools = a.tools or (PY_TOOLS if has_python(project) else "ruff")
    say(f"Fixing {project} with your approval at every gate: plan, start of repair, merge. Silence stops the run.")
    say("The fix is made on a separate branch; a backup tag is created first; REVERT.md tells you how to undo a merge.\n")
    cmd = [sys.executable, str(SCRIPTS / "rescue_voyage.py"), "--path", str(project), "--stages", "map,prove,review,plan,repair", "--tools", tools,
           "--probe", a.test, "--owner", "interactive"]
    rc = subprocess.run(cmd, env=voyage_env(cfg), check=False).returncode
    say("\nSession folder: " + str(project / ".rescue" / "voyage"))
    return rc


def cmd_note(a):
    project = resolve_project(a.project)
    out = out_dir(project)
    sys.path.insert(0, str(ROOT))
    from scripts import learnings
    entry = learnings.add(out, " ".join(a.text), files=a.file, project=project)
    say(f"Recorded: {entry['text']}")
    say(f"  read: {out / 'learnings' / 'LEARNINGS.md'}")
    return 0


def cmd_learnings(a):
    project = resolve_project(a.project)
    out = out_dir(project)
    sys.path.insert(0, str(ROOT))
    from scripts import learnings
    if a.check:
        changed = [line[3:].split(" -> ")[-1].strip('"')
                   for line in git(project, "status", "--porcelain").stdout.splitlines()
                   if len(line) > 3]
        hits = learnings.check(out, changed)
        if not hits:
            say(f"No learning mentions the {len(changed)} changed path(s).")
            return 0
        say(f"{len(hits)} learning(s) mention changed paths — read before editing:")
        for entry in hits:
            say(f"- {entry['text']}  [{', '.join(entry['files'])}]")
        return 0
    entries = learnings.recent(out, a.limit)
    if not entries:
        say('Nothing recorded yet. Add one: ./vr note "what you worked out"')
        return 0
    for entry in entries:
        where = f"  [{', '.join(entry['files'])}]" if entry["files"] else ""
        say(f"- {entry['at']} {entry['text']}{where}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="vr", description="Vibe Rescue: understand a messy codebase, then clean it up safely. Nothing changes without your yes.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor", help="what is installed, what is missing, how to fix it").set_defaults(f=cmd_doctor)
    e = sub.add_parser("explore", help="map the project and write a team handoff (no AI)")
    e.add_argument("project", nargs="?", default=".")
    e.set_defaults(f=cmd_explore)
    c = sub.add_parser("check", help="find concrete problems with free checking tools (no AI)")
    c.add_argument("project", nargs="?", default=".")
    c.add_argument("--tools", help=f"comma list; default for Python projects: {PY_TOOLS}")
    c.set_defaults(f=cmd_check)
    r = sub.add_parser("report", help="an AI explains the findings in plain words (needs an AI)")
    r.add_argument("project", nargs="?", default=".")
    r.add_argument("--tools")
    r.set_defaults(f=cmd_report)
    x = sub.add_parser("fix", help="plan, fix on a separate branch, second check; you approve every gate (needs an AI)")
    x.add_argument("project", nargs="?", default=".")
    x.add_argument("--test", help='safety command that must pass before and after, e.g. "python -m pytest -q"')
    x.add_argument("--tools")
    x.set_defaults(f=cmd_fix)
    q = sub.add_parser("ai", help="write config.local.toml for the AI you chose (never stores a key)")
    q.add_argument("kind", choices=("claude", "openai"))
    q.add_argument("--url", help="OpenAI-style base URL, ending in /v1")
    q.add_argument("--model", help="exact model id from /v1/models")
    q.add_argument("--checker-model", help="a different model for the second check")
    q.add_argument("--allow-http", action="store_true", help="allow plain http to a trusted non-local server")
    q.add_argument("--force", action="store_true")
    q.set_defaults(f=cmd_ai)
    n = sub.add_parser("note", help="record what the team worked out (no AI)")
    n.add_argument("project", nargs="?", default=".")
    n.add_argument("text", nargs="+", help="the learning, in one or more words")
    n.add_argument("--file", action="append", default=[], help="file this learning is about (repeatable)")
    n.set_defaults(f=cmd_note)
    ln = sub.add_parser("learnings", help="list learnings, or check them against the working tree")
    ln.add_argument("project", nargs="?", default=".")
    ln.add_argument("--check", action="store_true", help="show learnings that mention changed files")
    ln.add_argument("--limit", type=int, default=10)
    ln.set_defaults(f=cmd_learnings)
    a = p.parse_args(argv)
    return a.f(a)


if __name__ == "__main__":
    raise SystemExit(main())
