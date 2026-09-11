#!/usr/bin/env python3
"""SessionStart hook: inject the Dynamic Workflow instructions.

One core, `instructions/dynamic-workflow.md`, goes to every CHAIR
session start: the clarify rule (every question to the user, at the
start, in rounds) and the shape of the ledger the guard hooks read.
There is no per-model profile: the same text is injected whatever
model holds the chair.

TEAMMATE sessions are skipped entirely. Named agent-teams workers are
full claude sessions and fire SessionStart like the chair does — but the
core is written for the chair alone: injected into a worker it invites
it to run the question phase against a user it cannot reach. Detection
is the same ancestor walk the stop guard uses (`--agent-id` on the
nearest claude ancestor); the session marker is still written so the
other guards keep working. FABLE_ORCH_TEAMMATE_INJECT=1 restores the
old inject-everyone behaviour.

The hook also maintains the per-session marker the Stop and SessionEnd
hooks rely on: its immutable `started` timestamp survives the re-runs
SessionStart gets on resume/clear/compact, and the stop guard compares
ledger mtimes against it to decide ownership. `model` keeps the last
non-empty model the payload named, for the metrics log.
"""
import json
import os
import subprocess
import sys
import tempfile
import time


def session_model_cache_path(session_id):
    """Per-session marker file the stop/cleanup hooks read. None if no id."""
    if not session_id:
        return None
    safe = "".join(c for c in str(session_id) if c.isalnum() or c in "-_")
    return os.path.join(tempfile.gettempdir(), f"fable-orch-model-{safe}.json")


def _metric(event, session_id=None, **extra):
    """Append one event line to ~/.claude/fable-orch/metrics.jsonl (best effort)."""
    if (os.environ.get("FABLE_ORCH_METRICS") or "").strip() == "0":
        return
    try:
        d = os.path.join(os.path.expanduser("~"), ".claude", "fable-orch")
        os.makedirs(d, exist_ok=True)
        rec = {"ts": round(time.time(), 3), "event": event}
        if session_id:
            rec["session"] = str(session_id)[:8]
        rec.update(extra)
        with open(os.path.join(d, "metrics.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass



def _read_marker(cache):
    """(started, model) from the marker; (None, None) if unreadable."""
    if not cache:
        return None, None
    try:
        with open(cache, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            return d.get("started"), d.get("model")
    except Exception:
        pass
    return None, None


TEAMMATE_DETECT_BUDGET = 1.5  # seconds; the walk measures ~5ms in practice


def _budget(deadline, cap=5.0):
    """Seconds a subprocess may run without overshooting the deadline.

    Monotonic, exactly as in the stop guard: a wall clock can step
    backwards (NTP, a manual change) and would then hand back a budget
    that never expires, defeating the bound entirely."""
    if deadline is None:
        return cap
    return max(0.2, min(cap, deadline - time.monotonic()))


def _is_teammate_session(max_hops=12):
    """True when this hook is running inside a named teammate.

    Teammates are launched with `--agent-id`. The core belongs to the
    CHAIR: a worker that receives it is told to run the question phase
    against a user it cannot reach. Walks
    up to the first claude ancestor and answers from its argv; same
    logic as the stop guard's copy, kept verbatim so a future common
    module can unify them.

    HARD-BUDGETED because SessionStart must never hang a session open:
    on budget exhaustion the answer is False — "assume chair", so the
    core is still delivered. That failure costs one teammate carrying
    the core (the pre-fix behaviour for every teammate); the opposite
    default would strip the chair of its instructions.
    """
    deadline = time.monotonic() + TEAMMATE_DETECT_BUDGET
    pid = os.getpid()
    for _ in range(max_hops):
        if time.monotonic() > deadline:
            return False
        try:
            out = subprocess.run(
                ["ps", "-o", "ppid=,command=", "-p", str(pid)],
                capture_output=True, text=True, timeout=_budget(deadline),
            ).stdout.strip()
            bits = (out.splitlines()[0] if out else "").split(None, 1)
            ppid = int(bits[0])
        except Exception:
            return False
        command = bits[1] if len(bits) > 1 else ""
        for tok in command.split():
            base = os.path.basename(tok.strip("\"'"))
            if base == "claude" or "claude-code" in tok or base.startswith("2."):
                return "--agent-id" in command
        if ppid <= 1:
            return False
        pid = ppid
    return False



def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}

    model = data.get("model")  # optional; the harness omits it on some fires
    session_id = data.get("session_id")
    cache = session_model_cache_path(session_id)
    prev_started, prev_model = _read_marker(cache)
    filename = "dynamic-workflow.md"

    # The core is chair-only; a teammate session skips the injection
    # but still gets its marker below — stop, spawn, and cleanup key off
    # it.
    teammate = False
    if (os.environ.get("FABLE_ORCH_TEAMMATE_INJECT") or "").strip() != "1":
        teammate = _is_teammate_session()

    text = None
    if not teammate:
        root = os.environ.get("CLAUDE_PLUGIN_ROOT") or os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
        )
        path = os.path.join(root, "instructions", filename)
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except Exception:
            return  # never break session start

    # Session marker for the guards (best effort; never fatal).
    # `started` marks the session's FIRST start and must survive the
    # re-runs SessionStart gets on resume/clear/compact — the stop guard
    # compares ledger mtimes against it to decide ownership, so it can
    # never move forward. `model` keeps the last NON-EMPTY model seen, so
    # a later null-payload fire stays sticky instead of forgetting the
    # chair.
    try:
        if cache:
            started = prev_started
            try:
                started = float(started)
            except (TypeError, ValueError):
                # Marker from an older version (no `started`) or corrupt:
                # fall back to the file's mtime — NEVER to "now", which
                # would disown every ledger touched before this re-run.
                try:
                    started = os.path.getmtime(cache)
                except OSError:
                    started = time.time()
            stored_model = model if str(model or "").strip() else prev_model
            # Atomic replace: a crash mid-write must never leave a
            # truncated marker. The tmp name keeps the fable-orch-*.json
            # shape so an orphan from a crash still matches the 96h sweep.
            tmp = f"{cache}.{os.getpid()}.tmp.json"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(
                    {"model": stored_model, "session_id": session_id,
                     "started": round(started, 3)},
                    f,
                )
            os.replace(tmp, cache)
    except Exception:
        pass

    if teammate:
        _metric("inject_skipped", session_id, model=model, reason="teammate")
        return

    _metric("inject", session_id, model=model)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": text,
        }
    }))


if __name__ == "__main__":
    main()
