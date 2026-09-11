import json
import os
import re

from conftest import REPO, run_hook

INJECT = "inject_instructions.py"
CLEANUP = "cleanup_session_cache.py"


def context_of(result):
    assert result["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    return result["hookSpecificOutput"]["additionalContext"]


CORE = "dynamic-workflow.md"
CLARIFY = ("skills", "clarify", "SKILL.md")


def _core():
    return (REPO / "instructions" / CORE).read_text(encoding="utf-8")


def _clarify():
    return REPO.joinpath(*CLARIFY).read_text(encoding="utf-8")


def _flat(text):
    """Collapse every whitespace run to one space.

    The core is hard-wrapped prose, so a pinned phrase can sit across a
    line break. Content pins compare meaning, not line breaks."""
    return " ".join(text.split())


def test_core_stays_on_the_token_diet():
    # Claude Code caps hook output at 10,000 chars, and the core is
    # prepended to EVERY chair session, so every char is paid on every
    # start. v0.25.0 cut the core to the question phase alone: Rule 0.5
    # plus the ledger shape the hooks read, ~1.7k chars. The pin keeps
    # it a summary — the seven axes and the question form stay in the
    # clarify skill.
    text = _core()
    assert len(text) < 2500, f"{CORE} is {len(text)} chars — over the 2.5k core diet"


def test_only_one_core_and_no_switch_notes():
    # v0.25.0 user decision: one core, whatever model holds the chair.
    # The per-model profiles and the mid-session switch deltas are gone;
    # a second instructions file means the split came back.
    names = sorted(p.name for p in (REPO / "instructions").iterdir()
                   if p.suffix == ".md")
    assert names == [CORE], names


def test_playbook_skill_is_gone():
    # The delegation playbook (research pipeline, report contract, fork
    # cap, teammate lifecycle) left with the routing rules. Only the
    # clarify skill remains.
    skills = sorted(p.name for p in (REPO / "skills").iterdir() if p.is_dir())
    assert skills == ["clarify"], skills
    assert "playbook" not in _core().lower()


def test_core_is_clarify_only():
    # The user's 2026-09-12 decision: the chair's injected text is the
    # question phase and nothing else. Routing tiers, effort scale,
    # spawn discipline, worktree policy, report diet, fresh-eyes
    # verifier — any of these coming back is a regression.
    text = _flat(_core()).lower()
    for banned in ("sonnet", "opus", "haiku", "routing", "effort", "fork",
                   "worktree", "≤40 lines", "fresh", "verif", "v. ",
                   "shutdown_request", "tmux"):
        assert banned not in text, f"core carries `{banned}` again"
    assert "./.workflow/LEDGER*.md" in _core()
    assert "`- [ ] N. <item>`" in _core()
    assert "`- [~] deferred: <reason>`" in _flat(_core())


def test_clarify_skill_exists_and_stays_bounded():
    # Rule 0.5's detail lives here: the core summarizes, the skill
    # carries the protocol, and neither becomes a dumping ground.
    path = REPO.joinpath(*CLARIFY)
    assert path.is_file(), f"missing clarify skill: {path}"
    text = path.read_text(encoding="utf-8")
    assert len(text) < 6500, f"SKILL.md is {len(text)} chars — over the 6.5k budget"
    assert "name: clarify" in text


def test_clarify_skill_carries_the_user_decisions():
    # User decisions: every question at the START, in rounds, none
    # mid-implementation (2026-08-30 — one question per message across
    # turns was the interruption the project exists to remove); no cap
    # on the loop; the "does the answer change the work" filter that
    # makes an uncapped loop safe; the record landing in the ledger;
    # no assumption in place of a question (2026-08-31); the branch
    # question asked at every size; the literal stop condition. A
    # rewrite that drops one of these is a regression, not an edit.
    text = _flat(_clarify())
    assert "Ask in rounds, at the start" in text
    assert "AskUserQuestion" in text
    assert "No cap on rounds." in text
    assert "would a different answer produce different code?" in text
    assert "`## Clarified`" in text
    assert "SendMessage" in text          # subagents escalate, never ask the user
    assert "no `?` is left unanswered" in text
    assert "- Branch: <where the work lands>" in text
    assert "`Assumption:`/`Varsayım:` bullet" in text
    assert "After the go, the window is CLOSED" in text


def test_the_no_ambiguity_hatch_is_gone_everywhere():
    # The one-line `- No ambiguity: <why>` record was the escape the
    # chair took instead of asking (measured 2026-08-30/31: four live
    # ledgers, zero questions). It is gone from the skill, the core,
    # the README, and the spawn guard's own deny text.
    sources = {"core": _core(), "clarify": _clarify()}
    sources["README"] = (REPO / "README.md").read_text(encoding="utf-8")
    sources["guard"] = (REPO / "scripts" / "ledger_guard_spawn.py").read_text(encoding="utf-8")
    for name, text in sources.items():
        assert "no ambiguity" not in text.lower(), name


def test_core_requires_clarification_before_delegation():
    # The gate is hook-enforced, but the core still has to TELL the
    # chair what the hook wants — a deny the chair cannot act on is a
    # loop, not a guard.
    text = _flat(_core())
    assert "orchestrator:clarify" in text
    assert "`## Clarified`" in text
    assert "at the START" in text
    assert "Ask in ROUNDS" in text
    assert "no `?` is left unanswered" in text
    assert "Never an assumption in place of a question" in text
    assert "does this land on the branch checked out now, or a new one?" in text
    assert "`- Branch: <where it lands>`" in text
    assert "AFTER the go no question is asked mid-work" in text


def test_core_names_no_dated_model_id():
    # A dated or versioned model id goes stale on every release.
    dated = re.compile(r"\b(opus|sonnet|fable|haiku)[ -]?\d+[.-]\d+", re.IGNORECASE)
    hit = dated.search(_flat(_core()))
    assert not hit, hit.group(0) if hit else ""


def test_readme_carries_no_price_or_cost_figures():
    # User decision: the README sells the DISCIPLINE, not a number. Any
    # concrete price/spend figure dates instantly (tier prices move) and
    # invites a "is that still true?" the plugin cannot answer.
    text = (REPO / "README.md").read_text(encoding="utf-8")
    assert not re.search(r"\$\s?\d", text)
    assert not re.search(r"\b\d+(\.\d+)?\s?(x|×)\s?(cheaper|more expensive|the price)", text, re.I)


def _inject(tmp_path, payload, **env):
    env.setdefault("CLAUDE_PLUGIN_ROOT", str(REPO))
    return run_hook(INJECT, payload, env_extra=env, tmpdir=tmp_path)


def test_injects_the_core(tmp_path):
    result = _inject(tmp_path, {"model": "claude-fable-5", "session_id": "s-fable"})
    assert "Clarify First" in context_of(result)
    cache = tmp_path / "fable-orch-model-s-fable.json"
    assert cache.is_file()
    data = json.loads(cache.read_text())
    assert data["model"] == "claude-fable-5"
    assert "started" in data
    assert "profile" not in data   # v0.25.0: no per-model profile to record


def test_every_chair_model_gets_the_same_core(tmp_path):
    # One core for every chair: the text does not depend on the model.
    texts = set()
    for i, model in enumerate(("claude-fable-5", "claude-opus-5", "opus[1m]",
                               "claude-sonnet-5", "Opus 5 (1M context)")):
        texts.add(context_of(_inject(tmp_path, {"model": model, "session_id": f"s-m{i}"})))
    assert len(texts) == 1


def test_profile_env_override_is_ignored(tmp_path):
    # FABLE_ORCH_PROFILE was the per-model pin; with one core it is inert
    # and must not break the injection.
    r = _inject(tmp_path, {"model": "claude-fable-5", "session_id": "s-env"},
                FABLE_ORCH_PROFILE="opus")
    assert "Clarify First" in context_of(r)


def test_every_fire_source_gets_the_full_core(tmp_path):
    # There is no delta any more: resume, compact, clear and unknown
    # sources all receive the whole core, model change or not.
    _inject(tmp_path, {"model": "claude-fable-5", "session_id": "s-fire"})
    for fire in ("resume", "compact", "clear", "startup", "some-future-fire"):
        text = context_of(_inject(tmp_path, {"model": "claude-opus-5",
                                             "session_id": "s-fire",
                                             "source": fire}))
        assert "Clarify First" in text, fire
        assert "Profile switch" not in text, fire


def test_marker_keeps_model_sticky_on_null_payload(tmp_path):
    # A later null-payload resume must not overwrite the remembered
    # model with null.
    _inject(tmp_path, {"model": "claude-opus-4-8", "session_id": "s7"})
    marker = tmp_path / "fable-orch-model-s7.json"
    assert json.loads(marker.read_text())["model"] == "claude-opus-4-8"
    assert "Clarify First" in context_of(_inject(tmp_path, {"session_id": "s7"}))
    assert json.loads(marker.read_text())["model"] == "claude-opus-4-8"


def test_missing_model_still_injects(tmp_path):
    result = _inject(tmp_path, {"session_id": "s-nomodel"})
    assert "Clarify First" in context_of(result)
    cache = tmp_path / "fable-orch-model-s-nomodel.json"
    assert "started" in json.loads(cache.read_text())


def test_plugin_root_fallback_to_script_location(tmp_path):
    # No CLAUDE_PLUGIN_ROOT: the script resolves the repo from its own path.
    result = run_hook(INJECT, {"model": "claude-fable-5", "session_id": "s-fallback"},
                      tmpdir=tmp_path)
    assert "Clarify First" in context_of(result)


def test_metrics_written_when_enabled(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    _inject(tmp_path, {"model": "claude-fable-5", "session_id": "s-metrics"},
            HOME=str(home), FABLE_ORCH_METRICS="1")
    log = home / ".claude" / "fable-orch" / "metrics.jsonl"
    assert log.is_file()
    rec = json.loads(log.read_text(encoding="utf-8").strip().splitlines()[0])
    assert rec["event"] == "inject"
    assert rec["model"] == "claude-fable-5"
    assert "profile" not in rec


def test_stats_reads_legacy_switch_events_without_crashing(tmp_path):
    # Old logs still carry inject_switch lines from the two-profile
    # era; stats.py must keep reading them. Mixed old + new events, one
    # malformed line.
    import subprocess
    import sys

    log = tmp_path / "metrics.jsonl"
    log.write_text("\n".join([
        json.dumps({"ts": 1.0, "event": "inject", "profile": "fable"}),
        json.dumps({"ts": 2.0, "event": "inject_switch", "profile": "opus",
                    "from_profile": "fable", "fire": "compact"}),
        json.dumps({"ts": 3.0, "event": "inject_skipped", "reason": "teammate"}),
        json.dumps({"ts": 4.0, "event": "inject", "model": "claude-fable-5"}),
        "{not json",
    ]) + "\n", encoding="utf-8")
    proc = subprocess.run([sys.executable, str(REPO / "scripts" / "stats.py"),
                           str(log)], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    assert "mid-session profile switches: 1" in proc.stdout


def test_metrics_optout(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    _inject(tmp_path, {"model": "claude-fable-5", "session_id": "s-nometrics"},
            HOME=str(home), FABLE_ORCH_METRICS="0")
    assert not (home / ".claude" / "fable-orch" / "metrics.jsonl").exists()


def test_inject_preserves_started_across_reruns(tmp_path):
    _inject(tmp_path, {"model": "claude-fable-5", "session_id": "s-started"})
    cache = tmp_path / "fable-orch-model-s-started.json"
    data = json.loads(cache.read_text(encoding="utf-8"))
    assert "started" in data
    data["started"] = 123.0  # pretend the session started long ago
    cache.write_text(json.dumps(data), encoding="utf-8")
    # Re-injection (resume/clear/compact) must not move `started` forward.
    _inject(tmp_path, {"model": "claude-fable-5", "session_id": "s-started"})
    assert json.loads(cache.read_text(encoding="utf-8"))["started"] == 123.0


def _fake_ps_env(tmp_path, argv_line):
    """A fake `ps` on PATH: its one output line is the ancestor walk's
    first hop — the same fixture the stop guard's teammate tests use."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    ps = bin_dir / "ps"
    ps.write_text(
        "#!/usr/bin/env python3\nprint(%r)\n" % argv_line, encoding="utf-8")
    os.chmod(ps, 0o755)
    return {"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
            "CLAUDE_PLUGIN_ROOT": str(REPO)}


def test_teammate_session_gets_no_core(tmp_path):
    # Teammates fire SessionStart like any session, but the core is
    # chair-only: injected into a worker it tells it to run the question
    # phase against a user it cannot reach. Measured before the fix: 172
    # of 270 injected sessions were teammates.
    env = _fake_ps_env(
        tmp_path, "1 claude --agent-id worker@session-t --agent-name worker")
    result = run_hook(INJECT, {"model": "claude-sonnet-5", "session_id": "s-tm"},
                      env_extra=env, tmpdir=tmp_path)
    assert result is None
    # The marker is still written: stop, spawn, and cleanup key off it.
    cache = tmp_path / "fable-orch-model-s-tm.json"
    assert cache.is_file()
    assert json.loads(cache.read_text(encoding="utf-8"))["model"] == "claude-sonnet-5"


def test_teammate_skip_records_metric(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    env = _fake_ps_env(tmp_path, "1 claude --agent-id w@s --agent-name w")
    env.update({"HOME": str(home), "FABLE_ORCH_METRICS": "1"})
    run_hook(INJECT, {"model": "claude-sonnet-5", "session_id": "s-tm-m"},
             env_extra=env, tmpdir=tmp_path)
    log = home / ".claude" / "fable-orch" / "metrics.jsonl"
    rec = json.loads(log.read_text(encoding="utf-8").strip().splitlines()[0])
    assert rec["event"] == "inject_skipped"
    assert rec["reason"] == "teammate"


def test_teammate_inject_escape_hatch(tmp_path):
    # FABLE_ORCH_TEAMMATE_INJECT=1 restores the old inject-everyone
    # behaviour, mirroring FABLE_ORCH_TEAMMATE_STOP on the close guard.
    env = _fake_ps_env(tmp_path, "1 claude --agent-id w@s --agent-name w")
    env["FABLE_ORCH_TEAMMATE_INJECT"] = "1"
    result = run_hook(INJECT, {"model": "claude-sonnet-5", "session_id": "s-tm-e"},
                      env_extra=env, tmpdir=tmp_path)
    assert "Clarify First" in context_of(result)


def test_chair_still_injected_when_ancestor_is_plain_claude(tmp_path):
    # Same fake ps, no --agent-id: this is the chair and must keep
    # receiving the core.
    env = _fake_ps_env(tmp_path, "1 claude")
    result = run_hook(INJECT, {"model": "claude-fable-5", "session_id": "s-chair"},
                      env_extra=env, tmpdir=tmp_path)
    assert "Clarify First" in context_of(result)


def test_metrics_rotation_caps_the_log(tmp_path):
    home = tmp_path / "home"
    d = home / ".claude" / "fable-orch"
    d.mkdir(parents=True)
    log = d / "metrics.jsonl"
    log.write_bytes(b"x" * (5 * 1024 * 1024 + 1))
    run_hook(CLEANUP, {"session_id": "s-rot"},
             env_extra={"HOME": str(home), "FABLE_ORCH_METRICS": "1"},
             tmpdir=tmp_path)
    assert (d / "metrics.jsonl.old").is_file()
    assert log.is_file() and b"cleanup" in log.read_bytes()


def test_cleanup_removes_cache(tmp_path):
    cache = tmp_path / "fable-orch-model-s-clean.json"
    cache.write_text(json.dumps({"profile": "fable"}), encoding="utf-8")
    assert run_hook(CLEANUP, {"session_id": "s-clean"}, tmpdir=tmp_path) is None
    assert not cache.exists()


def test_cleanup_removes_stop_sidecar_and_sweeps_old(tmp_path):
    import os
    import time

    cache = tmp_path / "fable-orch-model-s-clean.json"
    cache.write_text("{}", encoding="utf-8")
    sidecar = tmp_path / "fable-orch-stop-s-clean.json"
    sidecar.write_text("{}", encoding="utf-8")
    tasks = tmp_path / "fable-orch-tasks-s-clean.json"
    tasks.write_text('{"count": 2}', encoding="utf-8")
    stale = tmp_path / "fable-orch-model-dead-session.json"
    stale.write_text("{}", encoding="utf-8")
    old = time.time() - 120 * 3600  # past the 96h sweep window
    os.utime(stale, (old, old))
    fresh = tmp_path / "fable-orch-model-alive.json"
    fresh.write_text("{}", encoding="utf-8")

    assert run_hook(CLEANUP, {"session_id": "s-clean"}, tmpdir=tmp_path) is None
    assert not cache.exists()
    assert not sidecar.exists()
    assert not tasks.exists()  # the task-gate counter dies with the session
    assert not stale.exists()  # older than the 96h sweep window
    assert fresh.exists()      # other live sessions' files stay


FAKE_TMUX = """#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
sock = args[1] if len(args) > 1 and args[0] == "-S" else ""
cmd = args[2] if len(args) > 2 else ""
if os.environ.get("FAKE_TMUX_DEAD") == "1":
    sys.stderr.write("no server running\\n")
    sys.exit(1)
if os.environ.get("FAKE_TMUX_MISMATCH") == "1":
    sys.stderr.write("protocol version mismatch (client 3.4, server 3.3)\\n")
    sys.exit(1)
if cmd == "list-panes":
    print(os.environ.get("FAKE_PANES", "%1 12345"))
elif cmd == "list-windows":
    print(os.environ.get("FAKE_WINDOW_ACTIVITY", "0"))
elif cmd == "kill-pane":
    with open(os.environ["FAKE_KILL_LOG"], "a") as f:
        f.write("pane " + sock + " " + " ".join(args[3:]) + "\\n")
elif cmd == "kill-server":
    with open(os.environ["FAKE_KILL_LOG"], "a") as f:
        f.write(sock + "\\n")
sys.exit(0)
"""

FAKE_PS = """#!/usr/bin/env python3
import json, os, sys
log = os.environ.get("FAKE_PS_LOG")
if log:
    with open(log, "a") as f:
        f.write(" ".join(sys.argv[1:]) + "\\n")
if "ppid=,command=" in sys.argv:
    # nearest-claude ancestor walk: "<ppid> <command of queried pid>"
    anc = os.environ.get("FAKE_ANCESTRY")
    if anc:
        m = json.loads(anc)
        print(m.get(sys.argv[-1], m.get("default", "1 init")))
    else:
        print(os.environ.get("FAKE_PPID", "1") + " claude")
elif "ppid=" in sys.argv:
    print(os.environ.get("FAKE_PPID", "1"))   # legacy ancestor walk
elif any("cputime" in a for a in sys.argv):
    print(os.environ.get("FAKE_PS_PANE",       # pane idle sampling
          "12345 0:05.00 claude --agent-id w@session-t --agent-name w"))
else:
    print(os.environ.get("FAKE_PS_OUTPUT", ""))  # command lookup
"""


def _swarm_fixture(tmp_path):
    """Fake tmux/ps on PATH + a fake socket dir with one swarm socket."""
    import os as _os

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("tmux", FAKE_TMUX), ("ps", FAKE_PS)):
        p = bin_dir / name
        p.write_text(body, encoding="utf-8")
        _os.chmod(p, 0o755)
    swarm_root = tmp_path / "tmuxroot"
    sock_dir = swarm_root / f"tmux-{_os.getuid()}"
    sock_dir.mkdir(parents=True)
    (sock_dir / "claude-swarm-111").write_text("", encoding="utf-8")
    kill_log = tmp_path / "kills.log"
    env = {
        "PATH": f"{bin_dir}:{_os.environ.get('PATH', '')}",
        "TMUX_TMPDIR": str(swarm_root),
        "FABLE_ORCH_SWARM_CLEANUP": "1",
        "FAKE_KILL_LOG": str(kill_log),
        "FAKE_PS_LOG": str(tmp_path / "ps.log"),
    }
    return env, kill_log


def test_cleanup_reaps_own_swarm(tmp_path):
    env, kill_log = _swarm_fixture(tmp_path)
    env["FAKE_PS_OUTPUT"] = "claude --agent-id worker@session-s-swarm- --agent-name worker"
    import time
    env["FAKE_WINDOW_ACTIVITY"] = str(int(time.time()))  # fresh — sweep must not fire
    assert run_hook(CLEANUP, {"session_id": "s-swarm-123"}, env_extra=env, tmpdir=tmp_path) is None
    assert kill_log.is_file()
    assert "claude-swarm-111" in kill_log.read_text()
    # The tag matcher must actually query ps with the pane pids it collected.
    ps_log = tmp_path / "ps.log"
    assert ps_log.is_file() and "-p 12345" in ps_log.read_text()


def test_cleanup_leaves_other_sessions_swarm(tmp_path):
    env, kill_log = _swarm_fixture(tmp_path)
    env["FAKE_PS_OUTPUT"] = "claude --agent-id worker@session-deadbeef --agent-name worker"
    import time
    env["FAKE_WINDOW_ACTIVITY"] = str(int(time.time()))
    assert run_hook(CLEANUP, {"session_id": "s-swarm-123"}, env_extra=env, tmpdir=tmp_path) is None
    assert not kill_log.exists()


def test_cleanup_sweeps_idle_swarm(tmp_path):
    env, kill_log = _swarm_fixture(tmp_path)
    env["FAKE_PS_OUTPUT"] = "claude --agent-id worker@session-deadbeef --agent-name worker"
    env["FAKE_WINDOW_ACTIVITY"] = "1000"  # ancient — way past the 48h window
    assert run_hook(CLEANUP, {"session_id": "s-swarm-123"}, env_extra=env, tmpdir=tmp_path) is None
    assert kill_log.is_file()
    assert "claude-swarm-111" in kill_log.read_text()


def test_cleanup_reaps_by_ancestor_pid_socket(tmp_path):
    # Current Claude Code tags teammates with a per-team id, not the parent
    # session id — the reaper must still find OUR server via its socket
    # name, claude-swarm-<main pid>, using the hook's ancestor chain.
    import os
    import time

    env, kill_log = _swarm_fixture(tmp_path)
    sock_dir = tmp_path / "tmuxroot" / f"tmux-{os.getuid()}"
    own = sock_dir / f"claude-swarm-{os.getpid()}"  # test process = hook's parent
    own.write_text("", encoding="utf-8")
    env["FAKE_PPID"] = str(os.getpid())
    env["FAKE_PS_OUTPUT"] = "claude --agent-id worker@session-otherteam --agent-name w"
    env["FAKE_WINDOW_ACTIVITY"] = str(int(time.time()))
    assert run_hook(CLEANUP, {"session_id": "s-swarm-123"}, env_extra=env, tmpdir=tmp_path) is None
    text = kill_log.read_text(encoding="utf-8") if kill_log.exists() else ""
    assert f"claude-swarm-{os.getpid()}" in text   # ours: killed via pid match
    assert "claude-swarm-111" not in text          # foreign tag + fresh: untouched


def test_swarm_idle_sweep_disabled_by_zero(tmp_path):
    # MAX_IDLE_H=0 turns off the idle kill even for ancient servers;
    # own-session reaping is a separate switch and stays available.
    import time

    env, kill_log = _swarm_fixture(tmp_path)
    env["FABLE_ORCH_SWARM_MAX_IDLE_H"] = "0"
    env["FAKE_PS_OUTPUT"] = "claude --agent-id worker@session-deadbeef --agent-name w"
    env["FAKE_WINDOW_ACTIVITY"] = "1000"  # ancient, but the sweep is off
    assert run_hook(CLEANUP, {"session_id": "s-swarm-123"}, env_extra=env, tmpdir=tmp_path) is None
    assert not kill_log.exists()


def test_inject_started_falls_back_to_mtime_for_legacy_cache(tmp_path):
    # A cache written by an older plugin version has no `started`. On the
    # next re-injection (compact/resume) the injector must anchor to the
    # file's mtime — never to "now", which would disown the session's
    # pre-compaction ledgers.
    import os
    import time

    cache = tmp_path / "fable-orch-model-s-legacy.json"
    cache.write_text(json.dumps({"profile": "fable"}), encoding="utf-8")
    old = time.time() - 7200
    os.utime(cache, (old, old))
    run_hook(INJECT, {"model": "claude-fable-5", "session_id": "s-legacy"},
             env_extra={"CLAUDE_PLUGIN_ROOT": str(REPO)}, tmpdir=tmp_path)
    started = json.loads(cache.read_text(encoding="utf-8"))["started"]
    assert abs(started - old) < 5


def test_swarm_cleanup_optout(tmp_path):
    env, kill_log = _swarm_fixture(tmp_path)
    env["FABLE_ORCH_SWARM_CLEANUP"] = "0"
    env["FAKE_PS_OUTPUT"] = "claude --agent-id worker@session-s-swarm- --agent-name worker"
    env["FAKE_WINDOW_ACTIVITY"] = "1000"
    assert run_hook(CLEANUP, {"session_id": "s-swarm-123"}, env_extra=env, tmpdir=tmp_path) is None
    assert not kill_log.exists()


def test_cleanup_unlinks_dead_socket(tmp_path):
    env, kill_log = _swarm_fixture(tmp_path)
    env["FAKE_TMUX_DEAD"] = "1"
    sock = tmp_path / "tmuxroot" / f"tmux-{__import__('os').getuid()}" / "claude-swarm-111"
    assert run_hook(CLEANUP, {"session_id": "s-swarm-123"}, env_extra=env, tmpdir=tmp_path) is None
    assert not sock.exists()
    assert not kill_log.exists()


def test_cleanup_without_session_id_is_noop(tmp_path):
    assert run_hook(CLEANUP, {}, tmpdir=tmp_path) is None


def test_cleanup_malformed_input_is_noop():
    assert run_hook(CLEANUP, raw="not json") is None


def test_non_object_stdin_never_crashes(tmp_path):
    # Valid JSON that isn't an object: both hooks stay on the contract.
    assert run_hook(CLEANUP, raw="[1, 2]", tmpdir=tmp_path) is None
    result = run_hook(INJECT, raw="[1, 2]",
                      env_extra={"CLAUDE_PLUGIN_ROOT": str(REPO)},
                      tmpdir=tmp_path)
    assert "Clarify First" in context_of(result)  # still injects


def test_nested_claude_does_not_kill_outer_swarm(tmp_path):
    # A nested `claude -p` (fusion helpers, scripts) ends: its hook's
    # ancestor chain CONTAINS the outer session's claude. Matching every
    # ancestor used to kill the outer session's LIVE team — only the
    # NEAREST claude ancestor (pid 900, the inner session) may match.
    import time

    env, kill_log = _swarm_fixture(tmp_path)
    sock_dir = tmp_path / "tmuxroot" / f"tmux-{__import__('os').getuid()}"
    (sock_dir / "claude-swarm-900").write_text("", encoding="utf-8")  # inner's team
    (sock_dir / "claude-swarm-500").write_text("", encoding="utf-8")  # OUTER's team
    env["FAKE_ANCESTRY"] = json.dumps({
        "default": "900 python3 hook.py",   # hook's parent is the inner claude
        "900": "800 claude -p run this",    # inner claude — NEAREST match
        "800": "500 -bash",                 # shell between the two sessions
        "500": "1 claude",                  # outer interactive claude
    })
    env["FAKE_PS_OUTPUT"] = "claude --agent-id w@session-otherteam --agent-name w"
    env["FAKE_WINDOW_ACTIVITY"] = str(int(time.time()))
    assert run_hook(CLEANUP, {"session_id": "s-nested"}, env_extra=env, tmpdir=tmp_path) is None
    text = kill_log.read_text(encoding="utf-8") if kill_log.exists() else ""
    assert "claude-swarm-900" in text      # the inner session's own team dies
    assert "claude-swarm-500" not in text  # the outer session's team LIVES


def test_session_end_kills_own_panes_in_default_server(tmp_path):
    # Current layout: teammates are panes inside the USER'S default tmux
    # server, tagged with --parent-session-id. SessionEnd must kill the
    # session's own PANES there — and must NEVER kill-server a non-swarm
    # socket.
    import time

    env, kill_log = _swarm_fixture(tmp_path)
    sock_dir = tmp_path / "tmuxroot" / f"tmux-{__import__('os').getuid()}"
    default_sock = sock_dir / "default"
    default_sock.write_text("", encoding="utf-8")
    env["FAKE_PS_OUTPUT"] = (
        "12345 claude --agent-id w@session-team1 --agent-name w "
        "--parent-session-id s-own-full-id"
    )
    env["FAKE_WINDOW_ACTIVITY"] = str(int(time.time()))
    assert run_hook(CLEANUP, {"session_id": "s-own-full-id"}, env_extra=env, tmpdir=tmp_path) is None
    lines = kill_log.read_text(encoding="utf-8").splitlines() if kill_log.exists() else []
    assert any("pane" in l and "default -t %1" in l for l in lines)
    assert not any(l.strip() == str(default_sock) for l in lines)  # no kill-server on default


def test_session_end_leaves_other_sessions_panes(tmp_path):
    import time

    env, kill_log = _swarm_fixture(tmp_path)
    sock_dir = tmp_path / "tmuxroot" / f"tmux-{__import__('os').getuid()}"
    (sock_dir / "default").write_text("", encoding="utf-8")
    env["FAKE_PS_OUTPUT"] = (
        "12345 claude --agent-id w@session-team1 --agent-name w "
        "--parent-session-id another-sessions-id"
    )
    env["FAKE_WINDOW_ACTIVITY"] = str(int(time.time()))
    assert run_hook(CLEANUP, {"session_id": "s-own-full-id"}, env_extra=env, tmpdir=tmp_path) is None
    log = kill_log.read_text(encoding="utf-8") if kill_log.exists() else ""
    assert "default" not in log  # the other session's pane lives


def test_session_id_prefix_collision_does_not_kill(tmp_path):
    # Session "s-own" must not claim a teammate of "s-own-full-id":
    # the --parent-session-id match is token-exact, not substring.
    import time

    env, kill_log = _swarm_fixture(tmp_path)
    sock_dir = tmp_path / "tmuxroot" / f"tmux-{__import__('os').getuid()}"
    (sock_dir / "default").write_text("", encoding="utf-8")
    env["FAKE_PS_OUTPUT"] = (
        "12345 claude --agent-id w@session-team1 --agent-name w "
        "--parent-session-id s-own-full-id"
    )
    env["FAKE_WINDOW_ACTIVITY"] = str(int(time.time()))
    assert run_hook(CLEANUP, {"session_id": "s-own"}, env_extra=env, tmpdir=tmp_path) is None
    log = kill_log.read_text(encoding="utf-8") if kill_log.exists() else ""
    assert "default" not in log


def test_protocol_mismatch_socket_survives(tmp_path):
    # tmux binary upgraded mid-flight: the server answers rc=1 with
    # "protocol version mismatch" but is ALIVE — unlinking its socket
    # would orphan it forever. Only truly dead sockets get removed.
    env, kill_log = _swarm_fixture(tmp_path)
    env["FAKE_TMUX_MISMATCH"] = "1"
    sock = tmp_path / "tmuxroot" / f"tmux-{__import__('os').getuid()}" / "claude-swarm-111"
    assert run_hook(CLEANUP, {"session_id": "s-mismatch"}, env_extra=env, tmpdir=tmp_path) is None
    assert sock.exists()
    assert not kill_log.exists()
