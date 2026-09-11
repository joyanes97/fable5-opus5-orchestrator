#!/usr/bin/env python3
"""PreToolUse guard (Agent|Task|Workflow|TaskCreate): keep multi-phase work on the ledger.

Dynamic Workflow ledger rule: serious multi-phase delegation requires
a Requirements Ledger in .workflow/ — any LEDGER*.md there, most
recent wins, *-archive.md excluded (searched from the working
directory up to the repo root or $HOME). Short spawn
prompts (quick searches/lookups) pass freely so casual Explore
agents are never blocked.

What is gated:
    Agent / Task  -> length of tool_input.prompt
    Workflow      -> length of tool_input.script (an orchestration
                     script IS the delegation plan; name/scriptPath
                     resume calls carry no new plan text and pass)
    TaskCreate    -> the SOLO path the spawn gates can't see: a chair
                     that never delegates never trips them, but the
                     tracker tasks it creates for itself are the tell.
                     The Nth TaskCreate of a session (default 3rd)
                     with no ledger draws ONE deny — "multi-phase
                     work: write the ledger, delegate to workers" —
                     then stays quiet (measured in the wild: a
                     6-phase plan implemented entirely on the chair).
Exempt:
    fork subagents (subagent_type == "fork") — a fork inherits the
    full conversation context, so the ledger is already in front
    of it; forcing a file adds nothing.

Rule 0.5 rides the same gates. A ledger only satisfies them when its
`## Clarified` section holds actual answers, not just any line under
the heading — four rules, evaluated over the bullet blocks of every
`## Clarified` section in the file:
    R1  in every bullet block (a bullet plus its indented continuation
        lines) the LAST `?` is followed by a `->`/`→` arrow carrying a
        real answer — not a bare `?`, not a `<placeholder>`
    R2  no bullet is an `Assumption:`/`Varsayım:` line standing in for
        a question the user was never asked
    R3  at least one bullet block carries such an answer
    R4  a `Branch:`/`Dal:` bullet names where the work lands
Workers cannot ask the user anything, so every ambiguity that reaches
a spawn prompt becomes a guess committed to code — the section is
where that guessing is spent instead, by asking rather than assuming.
The heading alone does not count, and neither does a restated
sentence, a one-line claim that nothing was ambiguous, or an assumption
dressed up as an answer; a chair that types the header and spawns anyway has clarified
nothing. The deny text names exactly which rule(s) failed.

The threshold defaults to 1500 chars — strict on purpose: even
small delegations should carry a ledger, because detail loss at
task->plan translation is exactly what the ledger exists to catch.

Staleness: a ledger satisfies the gates unless it is STALE-COMPLETE —
every item closed AND untouched since before this session started
(session start read from the injector's marker). Without that rule,
last week's finished ledger would silence the gates in a repo forever.
A ledger with open items, or one touched this session, always
satisfies; without a marker (manual install) existence alone wins.

Configuration (all optional):
    LEDGER_GUARD_THRESHOLD   gate in chars (default 1500; unparseable
                             values fall back to it, negatives clamp
                             to 0)
    LEDGER_GUARD_TASKS       deny fires AT the Nth ledgerless tracker
                             task (default 3 — two tasks pass free;
                             0 or negative disables the task gate)
    LEDGER_GUARD_CLARIFY=0   disables the Rule 0.5 clarify gate; the
                             ledger gates keep working
    FABLE_ORCH_METRICS=0     disables the local metrics log
"""
import json
import os
import re
import sys
import tempfile
import time

try:
    import fcntl
except ImportError:  # non-POSIX: run unlocked, best effort
    fcntl = None

DEFAULT_THRESHOLD = 1500
DEFAULT_TASK_LIMIT = 3
OPEN_ITEM_RE = r"^\s*[-*+] \[ \](?:\s.*)?$"
# The heading that OPENS a `## Clarified` section, at any level or case;
# the level is captured so a DEEPER sub-heading (`### Round 2`) can stay
# inside the section while a same-or-shallower one ends it.
CLARIFIED_HEADING_RE = r"^[ \t]{0,3}(#{1,6})[ \t]*clarified\b[^\n]*$"
# Two spellings of an ATX heading. The CommonMark one — hashes, then a
# space or the end of the line, up to three spaces of indent. And the
# spaceless one at COLUMN 0 only, because the heading that OPENS the
# section does not require a space either: `##Clarified` starts a
# section that `##Items` must be able to end. Column 0 and a letter,
# so neither `#42 in the tracker` nor `  #alpha in prose` on a wrapped
# answer line is read as a heading.
ATX_HEADING_RE = r"^[ \t]{0,3}(#{1,6})(?:[ \t]|$)"
SPACELESS_HEADING_RE = r"^(#{1,6})(?=[^\W\d_])"
# The other heading syntax: a paragraph line underlined with === or
# ---. It ends the section only when it STARTS a paragraph (blank line
# or section start before it) — a `---` right under a bullet's wrapped
# text is a thematic break after a list item, not a heading.
SETEXT_UNDERLINE_RE = r"^[ \t]{0,3}(?:=+|-{2,})[ \t]*$"
# ANY checkbox ends the Clarified section: the numbered items live
# directly below it with no heading in between, and answers are plain
# bullets — a checkbox line is a ledger item, never an answer.
CHECKBOX_RE = r"^\s*[-*+][ \t]+\[[^\]]?\]"
# Lines that are punctuation rather than an answer: thematic breaks
# and table rules (HTML comments are stripped before this runs). A
# chair that typed the heading and a divider has still clarified
# nothing.
NON_ANSWER_RE = (r"^[ \t]{0,3}(?:(?:[-*_][ \t]*){3,}"
                 r"|\|[ \t|:-]*\|[ \t]*)$")
# The bullet-block grammar for `## Clarified`: EVERY bullet line, at
# any indent, starts a block — `-`, `*`, `+`, or an ordered `1.`/`1)`;
# a non-bullet line indented deeper than that bullet is a CONTINUATION
# of it, so a `Q -> A` pair may wrap onto its own indented line. Tabs
# count as four columns. Indent is read from the bullet, not from the
# section's first one, so a `- Branch:` nested one level under a
# question is still its own line.
BULLET_RE = re.compile(r"^(\s*)(?:[-*+]|\d{1,3}[.)])\s+")
# The arrow that separates a question from its answer.
_ARROW_RE = re.compile(r"->|→")
# An answer written as `<something>` is the template's placeholder,
# not a thing the user said.
_PLACEHOLDER_RE = re.compile(r"^<[^<>]*>[\s.,;:!]*$")
# The MARKER an Assumption/Branch check reads: the bullet marker, an
# optional bold wrapper, and an optional `Q1:`/`S2:` label are stripped
# first, so `- **Assumption:** ...` and `- Q3: Branch: main` are read by
# what they SAY, not by how they are decorated or numbered.
_MARKER_PREFIX_RE = re.compile(
    r"^(?:[-*+]|\d{1,3}[.)])\s+(?:\*\*)?(?:[QS]\d+:\s*)?(?:\*\*)?\s*", re.I)
# Both languages the user's ledgers use, matched on the marker WORD
# before its colon after emphasis marks are peeled and case is folded
# (`**Branch**:`, `DAL:`, `VARSAYİM:` all read). "varsayim" is the
# ASCII-typed form of "varsayım".
_ASSUMPTION_WORDS = ("assumption", "varsayım", "varsayim")
_BRANCH_WORDS = ("branch", "dal")


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


def threshold():
    raw = os.environ.get("LEDGER_GUARD_THRESHOLD")
    if raw is not None:
        try:
            return max(0, int(raw))
        except ValueError:
            pass
    return DEFAULT_THRESHOLD


def task_limit():
    raw = os.environ.get("LEDGER_GUARD_TASKS")
    if raw is not None:
        try:
            return int(raw)
        except ValueError:
            pass
    return DEFAULT_TASK_LIMIT


def _task_sidecar(session_id):
    if not session_id:
        return None
    safe = "".join(c for c in str(session_id) if c.isalnum() or c in "-_")
    return os.path.join(tempfile.gettempdir(), f"fable-orch-tasks-{safe}.json")


def _bump_task_count(path, key="denied"):
    """Read-increment-write the sidecar under an exclusive lock.

    Parallel TaskCreate hooks race on this file; without the lock the
    deny can be skipped or fired twice (proven under forced
    concurrency). Valid-JSON-but-wrong-typed content must coerce, not
    crash — the hook contract is exit 0 always. Returns
    (count, denied_before) or None when the file can't be used.

    `key` picks WHICH one-per-session budget is being spent: the
    missing/stale-ledger nudge ("denied") and the clarify nudge
    ("denied_clarify") are separate reminders that say different
    things, so spending one must not silence the other.
    """
    try:
        f = open(path, "a+", encoding="utf-8")
    except OSError:
        return None
    try:
        if fcntl is not None:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            except OSError:
                pass
        f.seek(0)
        try:
            state = json.load(f)
        except Exception:
            state = {}
        if not isinstance(state, dict):
            state = {}
        try:
            count = int(state.get("count") or 0)
        except (TypeError, ValueError):
            count = 0
        count += 1
        denied_before = bool(state.get(key))
        deny_now = count >= task_limit() and not denied_before
        flags = {k: bool(state.get(k)) for k in ("denied", "denied_clarify")}
        flags[key] = denied_before or deny_now
        try:
            f.seek(0)
            f.truncate()
            json.dump(dict(count=count, **flags), f)
            f.flush()
        except (OSError, ValueError):
            pass
        return count, denied_before
    finally:
        f.close()


def guard_task_create(data):
    """Deny the Nth unguarded tracker task of a session — once.

    Unguarded means the ledger is missing, stale, or carries no
    `## Clarified` record; the deny text names which. Counting lives
    in a per-session sidecar so the gate never leaks across sessions;
    without a session_id there is nothing safe to scope to, so the
    call passes. The denied call creates no task and may simply be
    re-issued once the ledger is in order.
    """
    limit = task_limit()
    if limit <= 0:
        return
    session_id = data.get("session_id")
    ledger, blocker, failures = ledger_state(data)
    if blocker is None:
        return

    path = _task_sidecar(session_id)
    if path is None:
        return
    bumped = _bump_task_count(
        path, "denied_clarify" if blocker == "unclarified" else "denied")
    if bumped is None:
        return
    count, denied_before = bumped

    if count < limit:
        return
    if denied_before:
        _metric("tasks_suppressed", session_id, count=count, blocker=blocker)
        return

    if blocker == "unclarified":
        _metric("tasks_clarify_deny", session_id, count=count, threshold=limit)
        _deny(_clarify_reason(
            ledger,
            f"this is tracker task #{count} this session — multi-phase work — but",
            failures,
        ))
        return

    _metric("tasks_deny", session_id, count=count, threshold=limit,
            stale=blocker == "stale")
    _deny(
        f"LEDGER GUARD: this is tracker task #{count} this session — "
        "multi-phase work — but no active ledger exists in any "
        ".workflow/ from the working directory up to the repo root"
        f"{_stale_note(ledger, blocker)}. "
        "Work that needs a task list of 3+ items is a job, and a job starts "
        "with its questions. Ask the user every question that would change the "
        "work, then write ./.workflow/LEDGER.md now — a `## Clarified` "
        "section on top (the answers as plain bullets, `- Q1: <question>? "
        "-> <answer>`, plus a `- Branch: <where the work lands>` line) and "
        "the numbered Requirements Ledger below it — then do the work, "
        "directly or through workers citing ledger items. Re-issue this task afterwards — "
        "this reminder fires once per session."
    )


def active_ledger_in(dirpath):
    """The live ledger in dirpath/.workflow, or None.

    Any `LEDGER*.md` counts, not just the bare name: measured in the
    wild, 42 of 56 real ledger files carried a per-task name like
    `LEDGER-<topic>.md`, and every one of them was invisible to these
    guards. A name ENDING in `-archive.md` (or `_archive.md`) is
    retired and excluded — that rename is the documented way to put a
    ledger to rest, and the deny messages below ask for exactly it.
    The suffix has to be trailing: `LEDGER-archive-migration.md` is a
    live ledger whose topic happens to be archives, and it counts.
    Matching is case-insensitive. When several are live the most
    recently modified readable one wins: that is the one this session
    is working in.
    """
    workflow = os.path.join(dirpath, ".workflow")
    try:
        names = os.listdir(workflow)
    except OSError:
        return None
    best, best_mtime = None, -1.0
    for name in names:
        low = name.lower()
        if not (low.startswith("ledger") and low.endswith(".md")):
            continue
        # "ledger" must be a whole segment: LEDGER.md, LEDGER-topic.md,
        # LEDGER_topic.md — but not ledgers.md or ledgerish.md.
        if low[6:7] not in (".", "-", "_"):
            continue
        # Retired only when "archive" is the trailing segment, the form
        # this hook's own message asks for. A live ledger ABOUT archives
        # (LEDGER-archive-migration.md) must still count.
        if low.endswith("-archive.md") or low.endswith("_archive.md"):
            continue
        path = os.path.join(workflow, name)
        try:
            if not os.path.isfile(path):
                continue
            # An unreadable file must not mask a live sibling by being
            # newer — the guards could not read it anyway.
            if not os.access(path, os.R_OK):
                continue
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        if mtime > best_mtime:
            best, best_mtime = path, mtime
    return best


def find_ledger(start_dir):
    """Path of the live .workflow/ ledger from start_dir up to the repo root or $HOME.

    Walks parent directories so sessions running in a subdirectory
    still see the project ledger. Stops at the first directory that
    contains .git (checked with os.path.exists, not isdir — in
    worktrees and submodules .git is a FILE), at the home directory
    (a ledger above $HOME belongs to nobody), or at the filesystem
    root. realpath, not abspath: a symlinked cwd must climb the REAL
    project tree, or a legitimate ledger next to it is never found.
    """
    if not isinstance(start_dir, str) or not start_dir:
        start_dir = os.getcwd()
    d = os.path.realpath(start_dir)
    home = os.path.realpath(os.path.expanduser("~"))
    while True:
        candidate = active_ledger_in(d)
        if candidate:
            return candidate
        if os.path.exists(os.path.join(d, ".git")) or d == home:
            return None
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def _session_started(session_id):
    """The session's immutable start time from the injector marker, or None."""
    if not session_id:
        return None
    safe = "".join(c for c in str(session_id) if c.isalnum() or c in "-_")
    path = os.path.join(tempfile.gettempdir(), f"fable-orch-model-{safe}.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f).get("started")
        if raw is not None:
            return float(raw)
    except Exception:
        pass
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def read_ledger(path):
    """The ledger's text, or None when it cannot be read.

    One read per gated call: ledger_state hands the same text to both
    checks. Reading twice left a window where the file could be
    replaced or archived between them and the second read would fail
    open on a ledger that no longer existed.
    """
    try:
        # utf-8-sig: an editor that writes a BOM must not hide a line-one
        # `## Clarified` behind U+FEFF and deny the section it can see.
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def ledger_satisfies(ledger, session_id, text=None):
    """False only for a STALE-COMPLETE ledger: all items closed AND
    untouched since before this session started. Open items or a
    this-session touch keep it armed; no marker → existence wins."""
    if text is None:
        text = read_ledger(ledger)
    if text is None:
        return True
    if re.findall(OPEN_ITEM_RE, text, flags=re.M):
        return True
    started = _session_started(session_id)
    if started is None:
        return True
    try:
        return os.path.getmtime(ledger) >= min(started, time.time()) - 5.0
    except OSError:
        return True


def clarify_gate_on():
    """The Rule 0.5 gate, on unless LEDGER_GUARD_CLARIFY is exactly "0"."""
    return (os.environ.get("LEDGER_GUARD_CLARIFY") or "").strip() != "0"


def _outside_fences(text):
    """Drop fenced code blocks — a fenced example section is not a record.

    Tracks the fence character and its length, so a ~~~ block counts
    the same as a ``` one and a four-backtick block can quote a
    three-backtick example without the inner fence closing the outer.
    A markdown example of what `## Clarified` should look like must not
    satisfy the gate that example is teaching.
    """
    kept = []
    fence = None                      # (char, length) while inside a block
    for line in text.splitlines():
        stripped = line.lstrip()
        char = stripped[:1]
        if char in ("`", "~"):
            run = len(stripped) - len(stripped.lstrip(char))
            if run >= 3:
                if fence is None:
                    fence = (char, run)
                    continue
                if char == fence[0] and run >= fence[1]:
                    fence = None
                    continue
        if fence is None:
            kept.append(line)
    return kept


def _strip_html_comments(lines):
    """Blank out `<!-- ... -->` spans, across lines, keeping line count.

    A `## Clarified` template left inside an HTML comment is the same
    thing as one left inside a code fence — an example, not a record —
    and the bullets inside it must not be read as answers. Single-line
    comments are removed from the line they sit on; a multi-line one
    blanks every line from its opener to its closer.
    """
    kept = []
    inside = False
    for line in lines:
        out = ""
        rest = line
        while rest:
            if inside:
                end = rest.find("-->")
                if end < 0:
                    rest = ""
                    break
                inside = False
                rest = rest[end + 3:]
            else:
                start = rest.find("<!--")
                if start < 0:
                    out += rest
                    rest = ""
                    break
                out += rest[:start]
                inside = True
                rest = rest[start + 4:]
        kept.append(out)
    return kept


def _atx_level(line):
    """The heading level of an ATX line, or None."""
    m = re.match(ATX_HEADING_RE, line) or re.match(SPACELESS_HEADING_RE, line)
    return len(m.group(1)) if m else None


def _real_text(tail):
    """True when `tail` — the text after an arrow or a marker's colon —
    says something: not empty, not a `<placeholder>`, not bare
    punctuation such as a lone `?`."""
    tail = tail.strip()
    return bool(tail) and not _PLACEHOLDER_RE.match(tail) and bool(re.search(r"\w", tail))


def _answer_at(block, pos):
    """Index of the first arrow at or after `pos` that carries a real
    answer, or -1. The answer is everything after that arrow."""
    for m in _ARROW_RE.finditer(block, pos):
        if _real_text(block[m.end():]):
            return m.start()
    return -1


def _has_answer(block):
    return _answer_at(block, 0) >= 0


def _open_question(block):
    """R1: the LAST `?` in the block must be followed by an answer.

    Positional on purpose: `migrate A -> B?` has an arrow and is still
    a question, `db? -> ?` has an arrow and no answer, and a nested
    sub-bullet `- and z?` under an answered parent is a NEW question.
    An answer that itself ends in `?` is refused too — rephrase it;
    this follows "until no question mark remains" literally.
    """
    last = block.rfind("?")
    return last >= 0 and _answer_at(block, last) < 0


def _marker_word(block_text):
    """(word, rest) for a `Word: rest` bullet, after peeling the bullet
    marker, an optional `Q1:`/`S2:` label, and emphasis marks; the word
    is case-folded with the Turkish dotted-İ combining mark removed.
    ("", "") when the bullet has no colon-terminated word."""
    m = _MARKER_PREFIX_RE.match(block_text)
    marker = block_text[m.end():] if m else block_text
    head, sep, rest = marker.partition(":")
    if not sep:
        return "", ""
    word = re.sub(r"[*_`~\s]", "", head).lower().replace("\u0307", "")
    return word, rest


def _is_assumption(block):
    return _marker_word(block)[0] in _ASSUMPTION_WORDS


def _is_branch(block):
    word, rest = _marker_word(block)
    return word in _BRANCH_WORDS and _real_text(rest)


def _clarified_blocks(lines, index, level):
    """The bullet BLOCKS inside one `## Clarified` section.

    The section ends at the first checkbox line, at an ATX heading of
    the SAME or a shallower level (`# Clarified` counts as `##` here —
    the `##` sections after a title are siblings, not rounds), or at a
    setext heading that starts a paragraph; a deeper sub-heading
    (`### Round 2`) stays inside it. Within that boundary every bullet
    line starts a block; a non-bullet line indented deeper than the
    bullet above it is that block's continuation, joined with a single
    space. Blank lines, `NON_ANSWER_RE` lines (dividers, table rules),
    and any other line that is neither a bullet nor a continuation — a
    stray heading, a restated sentence — contribute nothing and start
    no block of their own: a chair still has to ask in a bullet, not
    narrate around one. No bullet anywhere in the section means no
    blocks at all, the same as an empty one.
    """
    # `# Clarified` is a document-title level; the sections that follow
    # it are `##`, and they are siblings, not rounds inside it. A deeper
    # sub-heading stays inside only from `##` down.
    level = max(level, 2)
    section = []
    prev_blank = True
    while index < len(lines):
        line = lines[index].expandtabs(4)
        if re.match(CHECKBOX_RE, line):
            break
        atx = _atx_level(line)
        if atx is not None and atx <= level:
            break
        nxt = lines[index + 1] if index + 1 < len(lines) else ""
        if (prev_blank and line.strip() and not re.match(BULLET_RE, line)
                and len(line) - len(line.lstrip()) <= 3
                and re.match(SETEXT_UNDERLINE_RE, nxt)):
            break                         # a setext heading opens the next section
        prev_blank = not line.strip()
        section.append(line)
        index += 1

    blocks = []
    current, current_indent = None, -1
    for line in section:
        if not line.strip() or re.match(NON_ANSWER_RE, line):
            continue
        indent = len(line) - len(line.lstrip())
        if re.match(BULLET_RE, line):
            if current is not None:
                blocks.append(" ".join(current))
            current, current_indent = [line.strip()], indent
        elif current is not None and indent > current_indent:
            current.append(line.strip())
        # else: a stray line at/under the bullet's indent that is not a
        # bullet — ignored, same as a blank line.
    if current is not None:
        blocks.append(" ".join(current))
    return blocks


def clarified_failures(ledger, text=None):
    """Which of the four Clarified rules fail, in report order.

    Evaluated over the UNION of blocks from every `## Clarified`
    section the ledger carries — the protocol appends later rounds,
    and an answer from round 1 still counts once round 2 adds the
    branch line. Empty when the ledger is unreadable (fail open, like
    every other check here) or when every rule is satisfied; a ledger
    with no `## Clarified` heading at all, or one whose section(s)
    carry no bullet, resolves to R3 and R4 failing — a missing section
    trips those two the same way an empty one does.

    Names: "assumption" (R2), "open_question" (R1), "no_answer" (R3),
    "no_branch" (R4) — `_clarify_reason` turns these into prose.
    """
    if text is None:
        text = read_ledger(ledger)
    if text is None:
        return []
    lines = _strip_html_comments(_outside_fences(text))
    starts = [(i, len(m.group(1)))
              for i, line in enumerate(lines)
              for m in [re.match(CLARIFIED_HEADING_RE, line, flags=re.I)] if m]
    blocks = []
    for i, level in starts:
        blocks.extend(_clarified_blocks(lines, i + 1, level))

    failures = []
    if any(_is_assumption(b) for b in blocks):
        failures.append("assumption")
    if any(_open_question(b) for b in blocks):
        failures.append("open_question")
    if not any(_has_answer(b) for b in blocks):
        failures.append("no_answer")
    if not any(_is_branch(b) for b in blocks):
        failures.append("no_branch")
    return failures


def ledger_state(data):
    """(ledger path or None, blocker or None, failed clarify rules).

    blocker is "missing", "stale", "unclarified", or None when the
    ledger clears both the clarify gate and the ledger gate. The third element is
    `clarified_failures()`'s list — non-empty only for "unclarified" —
    so the deny text can name the rule that failed without a second
    read of the file. Both gates below share this so a spawn and a
    tracker task can never disagree about what the ledger says.
    """
    ledger = find_ledger(data.get("cwd"))
    if not ledger:
        return None, "missing", []
    text = read_ledger(ledger)
    if text is None:
        return ledger, None, []                # unreadable → fail open
    if not ledger_satisfies(ledger, data.get("session_id"), text=text):
        return ledger, "stale", []
    if clarify_gate_on():
        failures = clarified_failures(ledger, text=text)
        if failures:
            return ledger, "unclarified", failures
    return ledger, None, []


def _stale_note(ledger, blocker):
    if blocker != "stale":
        return ""
    return (
        f" (a fully-closed ledger from a previous session was found at {ledger} "
        "and ignored — archive it as LEDGER-<topic>-archive.md or write a "
        "fresh one)"
    )


_CLARIFY_FAILURE_PROSE = {
    "assumption": "an assumption where a question belongs",
    "open_question": "an unanswered question",
    "no_answer": "no question-and-answer line",
    "no_branch": "no branch line",
}


def _clarify_reason(ledger, lead, failures=()):
    """The Rule 0.5 deny text, naming exactly which rule(s) failed.

    `failures` is `clarified_failures()`'s own list, already in report
    order — this only turns the names into prose, never re-derives
    them, so the text cannot drift from the check it describes.
    """
    named = ", ".join(_CLARIFY_FAILURE_PROSE.get(f, f) for f in failures)
    what_failed = (f"fails on {named}" if named
                   else "has no `## Clarified` section with content in it")
    return (
        f"CLARIFY GUARD: {lead} the ledger at {ledger} {what_failed}, so "
        "unresolved ambiguity is about to reach workers who cannot ask the "
        "user anything. Per Dynamic Workflow Rule 0.5, ask the user — at the "
        "START, in rounds, before the ledger and before any spawn — every "
        "question that would change the work: scope edge, acceptance, "
        "constraints, whose call each choice is, priority conflicts, contact "
        "with existing code, failure behaviour — until no `?` is left "
        "unanswered and a worker's spec could be written without guessing. "
        "Then record the answers under `## Clarified` at the TOP of the "
        "ledger and re-issue this call. Load `orchestrator:clarify` for the "
        "protocol. Answers are PLAIN BULLETS, one per question: `- Q1: "
        "<question>? -> <the user's answer>` (`→` also reads as the arrow; "
        "the answer is real words, not a `<placeholder>` or a bare `?`, and "
        "the last `?` of a bullet must have its answer after it), "
        "continuation text indented under its own bullet — a checkbox line "
        "(`- [ ]`, `- [x]`) reads as a ledger item and ends the section, and "
        "a fenced example, a divider, or a bare heading does not count as "
        "content. Never write an `Assumption:`/`Varsayım:` line in place of "
        "a question — ask instead. Always close with a `- Branch: <where the "
        "work lands>` line (`Dal:` also reads). If this ledger belongs to "
        "ABANDONED or unrelated work, do not write into it: archive it as "
        "LEDGER-<topic>-archive.md and start a fresh one for this task. "
        "LEDGER_GUARD_CLARIFY=0 disables this gate."
    )


def _deny(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))


def _guard(data):
    if (data.get("tool_name") or "") == "TaskCreate":
        guard_task_create(data)
        return

    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}

    # Forks inherit the full conversation context — ledger already visible.
    if str(tool_input.get("subagent_type") or "").strip().lower() == "fork":
        return

    if (data.get("tool_name") or "") == "Workflow":
        text = tool_input.get("script")
        what = "orchestration script"
    else:
        text = tool_input.get("prompt")
        what = "spawn prompt"
    if not isinstance(text, str):
        text = ""

    limit = threshold()
    if len(text) <= limit:
        return

    session_id = data.get("session_id")
    ledger, blocker, failures = ledger_state(data)
    if blocker is None:
        _metric("spawn_pass_over_threshold", session_id,
                chars=len(text), threshold=limit,
                tool=data.get("tool_name") or "")
        return

    if blocker == "unclarified":
        _metric("clarify_deny", session_id,
                chars=len(text), threshold=limit,
                tool=data.get("tool_name") or "")
        _deny(_clarify_reason(
            ledger,
            f"this looks like a detailed delegation ({what} > {limit} chars) but",
            failures,
        ))
        return

    _metric("spawn_deny", session_id,
            chars=len(text), threshold=limit,
            tool=data.get("tool_name") or "", stale=blocker == "stale")
    _deny(
        f"LEDGER GUARD: this looks like a detailed delegation "
        f"({what} > {limit} chars) but no active ledger exists in "
        "any .workflow/ from the working directory up to the repo root"
        f"{_stale_note(ledger, blocker)}. Per the clarify rule, "
        "first ask the user every question that would change the work, then "
        "write ./.workflow/LEDGER.md with a `## Clarified` section on top "
        "(the answers as plain bullets, `- Q1: <question>? -> <answer>`, plus "
        "a `- Branch: <where the work lands>` line) and the numbered "
        "Requirements Ledger below it (checkbox format: '- [ ] N. <item>'), "
        "then re-spawn citing which ledger items each agent covers — a ledger "
        "without that record is denied again by the clarify gate. If this is genuinely a "
        "small single-phase task, do it directly; if it is "
        "multi-phase, ask first and write the ledger before any "
        "detailed spawn."
    )


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return  # malformed input -> never block
    if not isinstance(data, dict):
        return
    try:
        _guard(data)
    except Exception:
        return  # a guard fails open; it never crashes the hook pipeline


if __name__ == "__main__":
    main()
