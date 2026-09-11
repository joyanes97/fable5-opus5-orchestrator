"""Rule 0.5: a ledger only disarms the spawn gates once it is CLARIFIED.

The ledger gates ask "did you write the requirements down?". These ask
the question before it: "did you find out what the requirements ARE?"
Workers cannot reach the user, so an ambiguity that survives into a
spawn prompt is a guess that ships — the `## Clarified` section is
where the chair spends that ambiguity instead.

What counts as clarified is four rules over the section's bullets:
R1 every `?` bullet carries a `->`/`→` answer, R2 no bullet is an
`Assumption:`/`Varsayım:` line, R3 at least one bullet carries an
answer, R4 a `Branch:`/`Dal:` bullet exists. "Any non-empty line under
the heading" was the previous predicate, and a restated user sentence
or a `- No ambiguity:` claim satisfied it without a question asked.
"""
from conftest import CLARIFIED, run_hook, write_ledger
from test_spawn_guard import (
    LONG,
    VERY_LONG,
    is_deny,
    run_tasks,
    spawn_payload,
    task_payload,
    write_marker,
)
import time

SCRIPT = "ledger_guard_spawn.py"
ITEMS = "- [ ] 1. item\n"


def reason(result):
    return result["hookSpecificOutput"]["permissionDecisionReason"]


def write_raw_ledger(repo, body=ITEMS):
    """Write the body EXACTLY as given — no record prepended.

    Named for what it does, not for what the gate will make of it:
    several of these bodies supply their own `## Clarified` and are
    scored as clarified, which a helper called `unclarified` would
    have contradicted right beside the assertion that depends on it.
    """
    return write_ledger(repo, body, clarified=False)


# --- the gate itself ---

def test_clarified_ledger_passes(repo_dir):
    write_ledger(repo_dir)
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


def test_unclarified_ledger_denied(repo_dir):
    write_raw_ledger(repo_dir)
    result = run_hook(SCRIPT, spawn_payload(repo_dir))
    assert is_deny(result)
    assert "CLARIFY GUARD" in reason(result)
    assert "orchestrator:clarify" in reason(result)


def test_heading_alone_is_not_a_record(repo_dir):
    # A chair that types the header and spawns anyway has clarified
    # nothing — the section has to carry content.
    write_raw_ledger(repo_dir, "## Clarified\n\n" + ITEMS)
    result = run_hook(SCRIPT, spawn_payload(repo_dir))
    assert is_deny(result) and "CLARIFY GUARD" in reason(result)


def test_empty_section_followed_by_heading_denied(repo_dir):
    write_raw_ledger(repo_dir, "## Clarified\n\n## Items\n" + ITEMS)
    result = run_hook(SCRIPT, spawn_payload(repo_dir))
    assert is_deny(result) and "CLARIFY GUARD" in reason(result), reason(result)


def test_section_at_end_of_file_with_content_passes(repo_dir):
    write_raw_ledger(repo_dir,
                     ITEMS + "\n## Clarified\n- Q1: scope -> all of it\n- Branch: main\n")
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


def test_heading_level_and_case_are_free(repo_dir):
    # The rule is about the record existing, not markdown depth.
    for heading in ("## Clarified", "### clarified", "###### CLARIFIED"):
        write_raw_ledger(
            repo_dir,
            f"{heading}\n- Q1: scope? -> the whole thing\n- Branch: main\n" + ITEMS)
        assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None, heading


def test_no_ambiguity_line_no_longer_satisfies_the_gate(repo_dir):
    # The old one-line escape is gone: every unknown is asked, not
    # declared away. `- No ambiguity: <why>` carries no `->`/`→` answer
    # and no `- Branch:` line, so it trips R3 and R4 the same as an
    # empty section would.
    write_raw_ledger(repo_dir, "## Clarified\n- No ambiguity: rename is exact\n" + ITEMS)
    result = run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG))
    assert is_deny(result)
    assert "no question-and-answer line" in reason(result)
    assert "no branch line" in reason(result)


# --- the four rules: the Clarified predicate is a bullet-block one,
# not "any non-punctuation line" — one behaviour per test.

def test_open_question_bullet_with_no_arrow_denies(repo_dir):
    write_raw_ledger(repo_dir,
                     "## Clarified\n- Q1: what should the retry limit be?\n- Branch: main\n")
    result = run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG))
    assert is_deny(result) and "CLARIFY GUARD" in reason(result)
    assert "an unanswered question" in reason(result)


def test_answer_wrapped_over_an_indented_continuation_line_passes(repo_dir):
    write_raw_ledger(repo_dir,
                     "## Clarified\n- Q1: what should the retry limit be?\n"
                     "  -> 3, matching the existing timeout\n- Branch: main\n")
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


def test_unicode_arrow_counts_as_an_answer(repo_dir):
    write_raw_ledger(repo_dir, "## Clarified\n- Q1: devam mı? → evet\n- Branch: main\n")
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


def test_arrow_with_nothing_after_it_is_not_an_answer(repo_dir):
    write_raw_ledger(repo_dir, "## Clarified\n- Q1: scope? ->\n- Branch: main\n")
    result = run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG))
    assert is_deny(result) and "an unanswered question" in reason(result)


def test_varsayim_bullet_denies(repo_dir):
    write_raw_ledger(repo_dir,
                     "## Clarified\n- Q1: scope? -> all of it\n"
                     "- Varsayım: geri kalanı aynı kalıyor\n- Branch: main\n")
    result = run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG))
    assert is_deny(result)
    assert "an assumption where a question belongs" in reason(result)


def test_assumption_bullet_denies_case_insensitively_and_bolded(repo_dir):
    for line in ("- assumption: nothing else changes",
                 "- ASSUMPTION: nothing else changes",
                 "- **Assumption:** nothing else changes",
                 "- varsayim: ascii-typed"):
        write_raw_ledger(repo_dir,
                         f"## Clarified\n- Q1: scope? -> all of it\n{line}\n- Branch: main\n")
        result = run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG))
        assert is_deny(result), line
        assert "an assumption where a question belongs" in reason(result), line


def test_missing_branch_line_denies(repo_dir):
    write_raw_ledger(repo_dir, "## Clarified\n- Q1: scope? -> all of it\n")
    result = run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG))
    assert is_deny(result) and "no branch line" in reason(result)


def test_dal_marker_passes(repo_dir):
    write_raw_ledger(repo_dir, "## Clarified\n- Q1: scope? -> all of it\n- Dal: main\n")
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


def test_branch_line_wearing_a_question_label_still_counts(repo_dir):
    # The label prefix (`Q<n>:`/`S<n>:`) is stripped from the MARKER
    # before the branch check runs, so a chair that numbers the branch
    # line like its questions has not thereby failed to answer it.
    write_raw_ledger(repo_dir, "## Clarified\n- Q1: scope? -> all of it\n- Q3: Branch: main\n")
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


def test_fenced_varsayim_example_is_ignored(repo_dir):
    write_raw_ledger(repo_dir,
                     "## Clarified\n- Q1: scope? -> all of it\n- Branch: main\n\n"
                     "```markdown\n## Clarified\n- Varsayım: <something>\n```\n")
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


def test_question_mark_after_the_answer_is_an_open_question(repo_dir):
    # R1 is positional: the LAST `?` of a block needs its answer after
    # it. An answer that ends in `?` is refused — rephrase it; "until no
    # question mark remains" is read literally, and it is what closes
    # the nested sub-question hole below.
    write_raw_ledger(repo_dir, "## Clarified\n- Q1: devam mı? -> evet, ama x?\n- Branch: main\n")
    result = run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG))
    assert is_deny(result) and "an unanswered question" in reason(result)


def test_arrow_inside_the_question_is_not_an_answer(repo_dir):
    write_raw_ledger(repo_dir, "## Clarified\n- Q1: migrate A -> B?\n- Branch: main\n")
    result = run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG))
    assert is_deny(result) and "an unanswered question" in reason(result)


def test_bare_question_mark_after_the_arrow_is_not_an_answer(repo_dir):
    write_raw_ledger(repo_dir, "## Clarified\n- Q1: db? -> ?\n- Branch: main\n")
    result = run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG))
    assert is_deny(result) and "an unanswered question" in reason(result)


def test_template_placeholders_are_not_answers(repo_dir):
    # The skill's example pasted verbatim, outside any fence.
    write_raw_ledger(repo_dir,
                     "## Clarified\n- Q1: <question>? -> <answer>\n- Branch: <where the work lands>\n")
    result = run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG))
    assert is_deny(result)
    assert "an unanswered question" in reason(result)
    assert "no question-and-answer line" in reason(result)
    assert "no branch line" in reason(result)


def test_nested_sub_question_under_an_answered_parent_is_open(repo_dir):
    write_raw_ledger(repo_dir,
                     "## Clarified\n- Q1: x? -> y\n  - and what about z?\n- Branch: main\n")
    result = run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG))
    assert is_deny(result) and "an unanswered question" in reason(result)


def test_nested_branch_bullet_still_counts(repo_dir):
    # Every bullet starts its own block, whatever its indent.
    write_raw_ledger(repo_dir, "## Clarified\n- Q1: x? -> y\n  - Branch: main\n")
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


def test_tab_indented_bullets_read_like_spaces(repo_dir):
    write_raw_ledger(repo_dir, "## Clarified\n\t- Q1: x?\n\t\t-> y\n  - Branch: main\n")
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


def test_ordered_list_bullets_count(repo_dir):
    write_raw_ledger(repo_dir, "## Clarified\n1. Q1: x? -> y\n2) Branch: main\n")
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


def test_emphasis_around_the_marker_word_is_peeled(repo_dir):
    for branch in ("- **Branch**: main", "- __Branch__: main", "- `Branch`: main", "- *Branch:* main"):
        write_raw_ledger(repo_dir, f"## Clarified\n- Q1: x? -> y\n{branch}\n")
        assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None, branch
    for assumption in ("- **Assumption**: z", "- VARSAYİM: z", "- Assumption : z"):
        write_raw_ledger(repo_dir, f"## Clarified\n- Q1: x? -> y\n{assumption}\n- Branch: main\n")
        result = run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG))
        assert is_deny(result) and "an assumption where a question belongs" in reason(result), assumption


def test_branch_line_with_no_value_is_not_a_branch_line(repo_dir):
    write_raw_ledger(repo_dir, "## Clarified\n- Q1: x? -> y\n- Branch:\n")
    result = run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG))
    assert is_deny(result) and "no branch line" in reason(result)


def test_deny_text_names_every_failed_rule(repo_dir):
    write_raw_ledger(repo_dir, "## Clarified\n- Varsayım: nothing else changes\n")
    result = run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG))
    text = reason(result)
    assert is_deny(result)
    assert "an assumption where a question belongs" in text
    assert "no question-and-answer line" in text
    assert "no branch line" in text


def test_second_clarified_round_completes_the_first(repo_dir):
    # Neither round alone carries both an answered question and a
    # branch line; the rules run over the UNION of every round's
    # blocks, so together they satisfy the gate.
    write_raw_ledger(repo_dir,
                     "## Clarified\n- Q1: scope? -> all of it\n\n## Clarified\n- Branch: main\n")
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


def test_restated_request_shaped_ledger_is_denied_naming_each_rule(repo_dir):
    # The real shape measured 2026-08-30/31: restated user sentences, a
    # `Varsayım:` line, and an open question marked "to be asked"
    # instead of answered. Zero questions were asked.
    write_raw_ledger(repo_dir,
                     "## Clarified\n"
                     "Kullanıcı mirror kaydının sadece bir kere çalışmasını istiyor.\n"
                     "- Varsayım: reconcile mantığı değişmiyor\n"
                     "- (açık) hangi alan çakışma sayılır? — sorulacak\n")
    result = run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG))
    text = reason(result)
    assert is_deny(result)
    assert "an assumption where a question belongs" in text
    assert "an unanswered question" in text


def test_crlf_ledger_still_reads_as_clarified(repo_dir):
    d = repo_dir / ".workflow"
    d.mkdir(parents=True, exist_ok=True)
    (d / "LEDGER.md").write_bytes(
        b"## Clarified\r\n- Q1: scope -> all\r\n- Branch: main\r\n\r\n- [ ] 1. open\r\n")
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


def test_lookalike_heading_does_not_satisfy(repo_dir):
    # "Clarifications pending" is not the record; the word has to be
    # the whole heading token.
    write_raw_ledger(repo_dir, "## Clarifying later\n- soon\n" + ITEMS)
    result = run_hook(SCRIPT, spawn_payload(repo_dir))
    assert is_deny(result) and "CLARIFY GUARD" in reason(result), reason(result)


# --- scope: the gate rides the EXISTING thresholds, it does not widen them ---

def test_short_prompt_still_passes_unclarified(repo_dir):
    # Quick lookups were never gated and still are not.
    write_raw_ledger(repo_dir)
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt="where is the config")) is None


def test_fork_still_exempt(repo_dir):
    write_raw_ledger(repo_dir)
    payload = spawn_payload(repo_dir, prompt=VERY_LONG, tool_input={"subagent_type": "fork"})
    assert run_hook(SCRIPT, payload) is None


def test_workflow_script_gated_on_clarification(repo_dir):
    write_raw_ledger(repo_dir)
    payload = spawn_payload(repo_dir, tool="Workflow")
    payload["tool_input"] = {"script": "y" * 5000}
    result = run_hook(SCRIPT, payload)
    assert is_deny(result) and "CLARIFY GUARD" in reason(result)


def test_threshold_env_still_applies(repo_dir):
    write_raw_ledger(repo_dir)
    assert run_hook(
        SCRIPT, spawn_payload(repo_dir, prompt=LONG),
        env_extra={"LEDGER_GUARD_THRESHOLD": "3000"},
    ) is None


# --- precedence: a missing or stale ledger is still a LEDGER problem ---

def test_missing_ledger_reports_the_ledger_gate(repo_dir):
    result = run_hook(SCRIPT, spawn_payload(repo_dir))
    assert is_deny(result)
    assert "LEDGER GUARD" in reason(result) and "CLARIFY GUARD" not in reason(result)


def test_stale_clarified_ledger_reports_staleness(repo_dir, tmp_path):
    import os
    write_marker(tmp_path, time.time())
    ledger = write_ledger(repo_dir, "- [x] 1. done\n- [x] 2. checked\n")
    old = time.time() - 3600
    os.utime(ledger, (old, old))
    result = run_hook(SCRIPT, spawn_payload(repo_dir), tmpdir=tmp_path)
    assert is_deny(result) and "previous session" in reason(result)


# --- the tracker-task gate carries the same rule ---

def test_third_task_on_unclarified_ledger_denied(repo_dir, tmp_path):
    write_raw_ledger(repo_dir)
    results = run_tasks(repo_dir, tmp_path, 4)
    assert results[0] is None and results[1] is None
    assert is_deny(results[2])
    assert "CLARIFY GUARD" in results[2]["hookSpecificOutput"]["permissionDecisionReason"]
    assert results[3] is None          # still fires once per session


def test_task_deny_names_the_failed_rule_too(repo_dir, tmp_path):
    write_raw_ledger(repo_dir, "## Clarified\n- Varsayım: nothing else changes\n" + ITEMS)
    results = run_tasks(repo_dir, tmp_path, 3)
    text = results[2]["hookSpecificOutput"]["permissionDecisionReason"]
    assert "an assumption where a question belongs" in text


def test_tasks_pass_freely_on_a_clarified_ledger(repo_dir, tmp_path):
    write_ledger(repo_dir)
    assert run_tasks(repo_dir, tmp_path, 5) == [None] * 5


# --- the escape hatch ---

def test_clarify_guard_disabled_by_zero(repo_dir):
    write_raw_ledger(repo_dir)
    assert run_hook(
        SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG),
        env_extra={"LEDGER_GUARD_CLARIFY": "0"},
    ) is None


def test_clarify_guard_only_zero_disables(repo_dir):
    write_raw_ledger(repo_dir)
    for value in ("", "1", "off", "false"):
        result = run_hook(
            SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG),
            env_extra={"LEDGER_GUARD_CLARIFY": value},
        )
        assert is_deny(result), value


def test_disabled_gate_leaves_the_ledger_gate_armed(repo_dir):
    assert is_deny(run_hook(
        SCRIPT, spawn_payload(repo_dir),
        env_extra={"LEDGER_GUARD_CLARIFY": "0"},
    ))


# --- a guard never crashes the pipeline ---

def test_malformed_input_never_blocks():
    assert run_hook(SCRIPT, raw="{not json") is None


def test_binary_ledger_denies_rather_than_crashing(repo_dir):
    # The junk bytes decode to replacement characters ON the heading
    # line, so the heading does not match and the gate denies.
    d = repo_dir / ".workflow"
    d.mkdir(parents=True, exist_ok=True)
    (d / "LEDGER.md").write_bytes(b"\xff\xfe\x00## Clarified\n- Q1: x\n\n- [ ] 1. open\n")
    result = run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG))
    assert is_deny(result) and "CLARIFY GUARD" in reason(result)


def test_clarified_constant_matches_the_documented_shape(repo_dir):
    # The fixture and the skill have to agree on what a record looks
    # like, or the suite passes on a shape the plugin never ships.
    assert CLARIFIED.startswith("## Clarified\n")
    assert "-> " in CLARIFIED and "- Branch:" in CLARIFIED
    write_raw_ledger(repo_dir, CLARIFIED + ITEMS)
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


# --- what counts as an ANSWER ---

def test_any_checkbox_ends_the_section(repo_dir):
    # Answers are plain bullets. Recognising only NUMBERED checkboxes
    # let an empty heading above ordinary `- [ ] fix login` items pass
    # as if the ledger's own requirements were the answers — a silent
    # bypass of the whole gate. Every checkbox form ends the section,
    # and the deny text says so instead of claiming the file is empty.
    for bullet in ("- [ ] 1. item", "* [x] 2. done", "+ [~] 3. deferred: ok",
                   "- [x] 2. checked", "- [ ] fix login", "- [x] Q1: beside it",
                   "-  [ ] 1. two spaces", "- [>] 1. odd marker"):
        write_raw_ledger(repo_dir, f"## Clarified\n\n{bullet}\n")
        result = run_hook(SCRIPT, spawn_payload(repo_dir))
        assert is_deny(result), bullet
        assert "PLAIN BULLETS" in reason(result), bullet


def test_checkbox_shaped_answers_no_longer_count(repo_dir):
    # v0.16.0 accepted `- [x] Q1: ... -> ...` as an answer. A checkbox
    # is a ledger item: an OPEN one (`- [ ] Q2: still waiting`) matched
    # OPEN_ITEM_RE, so the ledger could never go stale and every close
    # was held forever. Ending the section on any checkbox closes it.
    write_raw_ledger(repo_dir,
                     "## Clarified\n"
                     "- [x] Q1: replace the old exporter? -> beside it, one release\n"
                     "- [ ] Q2: still waiting on the user\n\n" + ITEMS)
    result = run_hook(SCRIPT, spawn_payload(repo_dir))
    assert is_deny(result) and "CLARIFY GUARD" in reason(result), reason(result)


def test_sub_heading_stays_inside_the_section(repo_dir):
    # The protocol appends later rounds, and `### Round 1` is how a
    # chair files them. Ending the section at ANY heading denied a
    # ledger full of answers, with nothing in the message to act on.
    write_raw_ledger(repo_dir,
                     "## Clarified\n### Round 1\n- Q1: replace it? -> beside it\n"
                     "- Branch: main\n\n" + ITEMS)
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


def test_same_level_heading_ends_the_section(repo_dir):
    write_raw_ledger(repo_dir, "## Clarified\n\n## Items\n- something -> else\n- Branch: main\n" + ITEMS)
    result = run_hook(SCRIPT, spawn_payload(repo_dir))
    assert is_deny(result) and "CLARIFY GUARD" in reason(result), reason(result)


def test_spaceless_heading_ends_a_section_it_could_start(repo_dir):
    # `##Clarified` opens a section, so `##Items` has to be able to
    # close one — otherwise an empty section runs past the ledger's own
    # headings hunting for content.
    write_raw_ledger(repo_dir, "## Clarified\n\n##Items\n- x -> y\n- Branch: main\n" + ITEMS)
    result = run_hook(SCRIPT, spawn_payload(repo_dir))
    assert is_deny(result) and "CLARIFY GUARD" in reason(result), reason(result)
    write_raw_ledger(repo_dir, "##Clarified\n- Q1: scope -> all of it\n- Branch: main\n\n" + ITEMS)
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


def test_setext_heading_ends_an_empty_section(repo_dir):
    # The other heading syntax opens the NEXT section, so an empty
    # `## Clarified` must not read that section's bullets as answers.
    write_raw_ledger(repo_dir,
                     "## Clarified\n\nDecisions\n---------\n- a -> b\n- Branch: main\n" + ITEMS)
    result = run_hook(SCRIPT, spawn_payload(repo_dir))
    assert is_deny(result) and "no question-and-answer line" in reason(result)


def test_wrapped_answer_then_divider_is_not_a_setext_heading(repo_dir):
    # `---` right under a bullet's continuation text is a thematic
    # break after a list item, not a heading over it.
    write_raw_ledger(repo_dir,
                     "## Clarified\n- Q1: scope? -> all of it,\n  every module\n---\n"
                     "- Branch: main\n\n" + ITEMS)
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


def test_h1_record_ends_at_the_next_h2(repo_dir):
    # `# Clarified` is a title level; the `##` sections after it are
    # siblings, so an empty H1 record must not swallow their bullets.
    write_raw_ledger(repo_dir,
                     "# Clarified\n\n## Decisions\n- a -> b\n- Branch: main\n" + ITEMS)
    result = run_hook(SCRIPT, spawn_payload(repo_dir))
    assert is_deny(result) and "no question-and-answer line" in reason(result)


def test_multi_line_html_comment_template_is_not_a_record(repo_dir):
    # A template left inside `<!-- -->` is an example, exactly like one
    # inside a code fence — its bullets are not answers.
    write_raw_ledger(repo_dir,
                     "## Clarified\n<!-- fill in:\n- Q1: <question>? -> <answer>\n"
                     "- Branch: <branch>\n-->\n" + ITEMS)
    result = run_hook(SCRIPT, spawn_payload(repo_dir))
    assert is_deny(result) and "no question-and-answer line" in reason(result)
    # ...and a commented-out heading opens nothing.
    write_raw_ledger(repo_dir, "<!--\n## Clarified\n- Q1: x? -> y\n- Branch: main\n-->\n" + ITEMS)
    result = run_hook(SCRIPT, spawn_payload(repo_dir))
    assert is_deny(result) and "CLARIFY GUARD" in reason(result)


def test_inline_html_comment_does_not_eat_the_answer(repo_dir):
    write_raw_ledger(repo_dir,
                     "## Clarified\n- Q1: scope? -> all of it <!-- confirmed twice -->\n"
                     "- Branch: main\n\n" + ITEMS)
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


def test_hash_on_a_continuation_line_is_not_a_heading(repo_dir):
    # `#42` is an issue number and `  #alpha` is indented prose: neither
    # is an ATX heading (CommonMark wants a space after the hashes; the
    # spaceless `##Items` form is honoured at column 0 only), so neither
    # ends the section before the branch line.
    for cont in ("  #42 in the tracker", "  #alpha in prose"):
        write_raw_ledger(repo_dir,
                         f"## Clarified\n- Q1: which issue? -> the retry one,\n{cont}\n"
                         "- Branch: main\n\n" + ITEMS)
        assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None, cont


def test_tilde_and_longer_fences_hide_examples_too(repo_dir):
    write_raw_ledger(repo_dir,
                     "## Clarified\n~~~markdown\n- Q1: <q>? -> real\n- Branch: main\n~~~\n" + ITEMS)
    result = run_hook(SCRIPT, spawn_payload(repo_dir))
    assert is_deny(result) and "CLARIFY GUARD" in reason(result), reason(result)
    write_raw_ledger(repo_dir,
                     "## Clarified\n````markdown\n```\n- Q1: q? -> real\n- Branch: main\n```\n````\n" + ITEMS)
    result = run_hook(SCRIPT, spawn_payload(repo_dir))
    assert is_deny(result) and "CLARIFY GUARD" in reason(result), reason(result)


def test_setext_heading_does_not_count_as_content(repo_dir):
    # The other markdown heading syntax is not an answer either.
    write_raw_ledger(repo_dir, "## Clarified\n\nRequirements\n------------\n" + ITEMS)
    result = run_hook(SCRIPT, spawn_payload(repo_dir))
    assert is_deny(result) and "CLARIFY GUARD" in reason(result), reason(result)


def test_divider_after_a_bullet_does_not_break_the_block(repo_dir):
    # A thematic break right after a bullet is punctuation, not
    # continuation text and not a new block — `NON_ANSWER_RE` lines
    # are simply skipped, exactly like a blank line.
    write_raw_ledger(repo_dir,
                     "## Clarified\n- Q1: scope? -> all of it\n---\n- Branch: main\n\n" + ITEMS)
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


def test_punctuation_alone_is_not_an_answer(repo_dir):
    # Typing the heading and a divider is the "clarified nothing" case.
    for filler in ("---", "***", "___", "<!-- TODO fill this in -->", "|  |"):
        write_raw_ledger(repo_dir, f"## Clarified\n\n{filler}\n\n" + ITEMS)
        result = run_hook(SCRIPT, spawn_payload(repo_dir))
        assert is_deny(result), filler
        assert "CLARIFY GUARD" in reason(result), (filler, reason(result))


def test_restated_prose_without_a_bullet_is_not_an_answer(repo_dir):
    # A paragraph that happens to contain an arrow and the word Branch
    # is narration, not a record: only bullets are read.
    write_raw_ledger(repo_dir,
                     "## Clarified\nThe user wants X -> so we do Y. Branch: main.\n\n" + ITEMS)
    result = run_hook(SCRIPT, spawn_payload(repo_dir))
    assert is_deny(result) and "no question-and-answer line" in reason(result)


def test_fenced_example_is_not_a_record(repo_dir):
    # The skill's own markdown example of the section must not satisfy
    # the gate it is teaching — same rule as the close guard's fences.
    write_raw_ledger(repo_dir,
                     "## Notes\nCopy this shape:\n\n```markdown\n## Clarified\n"
                     "- Q1: <question> -> <answer>\n- Branch: main\n```\n\n" + ITEMS)
    result = run_hook(SCRIPT, spawn_payload(repo_dir))
    assert is_deny(result) and "CLARIFY GUARD" in reason(result), reason(result)


def test_fenced_example_beside_a_real_record_passes(repo_dir):
    write_raw_ledger(repo_dir,
                     "## Clarified\n- Q1: scope -> all of it\n- Branch: main\n\n"
                     "```markdown\n## Clarified\n- Q1: <question>\n```\n\n" + ITEMS)
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


def test_a_filled_section_below_an_empty_one_passes(repo_dir):
    # The protocol appends later answers, so every heading is checked.
    write_raw_ledger(repo_dir,
                     "## Clarified\n\n" + ITEMS +
                     "\n## Clarified\n- Q2: round two -> yes\n- Branch: main\n")
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


def test_the_raw_fixture_keeps_line_one_on_line_one(repo_dir):
    # Every line-one pin in this module — `# Clarified` at the top,
    # `##Clarified` with no space, the BOM in front of it — is only a
    # pin while the fixture writes the body it was handed.
    path = write_raw_ledger(repo_dir, "# Clarified\n- Q1: scope -> all of it\n")
    assert path.read_text(encoding="utf-8").splitlines()[0] == "# Clarified"


def test_h1_clarified_counts(repo_dir):
    write_raw_ledger(repo_dir, "# Clarified\n- Q1: scope -> all of it\n- Branch: main\n\n" + ITEMS)
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


def test_byte_order_mark_does_not_hide_a_line_one_heading(repo_dir):
    # An editor that writes a BOM puts U+FEFF in front of `## Clarified`;
    # the fenced-line scan reads it, so the heading still matches.
    d = repo_dir / ".workflow"
    d.mkdir(parents=True, exist_ok=True)
    (d / "LEDGER.md").write_bytes(
        b"\xef\xbb\xbf## Clarified\n- Q1: scope -> all of it\n- Branch: main\n\n- [ ] 1. open\n")
    assert run_hook(SCRIPT, spawn_payload(repo_dir, prompt=VERY_LONG)) is None


# --- the deny texts have to be actionable in ONE round trip ---

def test_ledger_deny_names_the_clarified_section(repo_dir):
    # Following the old text exactly — write the numbered ledger, re-spawn —
    # walked straight into a clarify deny. Two round trips for obeying.
    result = run_hook(SCRIPT, spawn_payload(repo_dir))
    assert is_deny(result) and "`## Clarified`" in reason(result)
    assert "Branch:" in reason(result)


def test_task_deny_names_the_clarified_section(repo_dir, tmp_path):
    results = run_tasks(repo_dir, tmp_path, 3)
    assert "`## Clarified`" in results[2]["hookSpecificOutput"]["permissionDecisionReason"]


def test_clarify_deny_offers_the_archive_remedy(repo_dir):
    # An abandoned ledger with one never-closed item is never "stale",
    # so it falls through to the clarify deny — which used to tell the
    # chair to write this session's answers into a foreign file.
    write_raw_ledger(repo_dir, "- [ ] 2. something from six months ago\n")
    result = run_hook(SCRIPT, spawn_payload(repo_dir))
    assert is_deny(result) and "archive" in reason(result).lower()


def test_clarify_deny_never_offers_the_no_ambiguity_hatch(repo_dir):
    write_raw_ledger(repo_dir)
    result = run_hook(SCRIPT, spawn_payload(repo_dir))
    assert is_deny(result)
    assert "no ambiguity" not in reason(result).lower()
    assert "Assumption:" in reason(result) and "Branch:" in reason(result)


# --- the two tracker-task reminders are separate budgets ---

def test_clarify_nudge_does_not_spend_the_ledger_nudge(repo_dir, tmp_path):
    import shutil
    write_raw_ledger(repo_dir)
    results = run_tasks(repo_dir, tmp_path, 3)
    assert is_deny(results[2])
    assert "CLARIFY GUARD" in results[2]["hookSpecificOutput"]["permissionDecisionReason"]

    shutil.rmtree(repo_dir / ".workflow")          # now the ledger is gone
    more = run_tasks(repo_dir, tmp_path, 2)
    assert is_deny(more[0]), "the missing-ledger nudge was silenced by the clarify one"
    assert "LEDGER GUARD" in more[0]["hookSpecificOutput"]["permissionDecisionReason"]
    assert more[1] is None                          # still once per session, per kind


# --- metrics and the summary they feed ---

def test_clarify_metrics_reach_the_stats_summary(repo_dir, tmp_path):
    import json
    import subprocess
    import sys
    from conftest import REPO

    home = tmp_path / "home"
    home.mkdir()
    env = {"FABLE_ORCH_METRICS": "1", "HOME": str(home)}
    write_raw_ledger(repo_dir)
    run_hook(SCRIPT, spawn_payload(repo_dir), env_extra=env, tmpdir=tmp_path)
    for _ in range(3):
        run_hook(SCRIPT, task_payload(repo_dir), env_extra=env, tmpdir=tmp_path)

    log = home / ".claude" / "fable-orch" / "metrics.jsonl"
    events = [json.loads(line) for line in log.read_text().splitlines()]
    assert sum(1 for e in events if e["event"] == "clarify_deny") == 1
    assert sum(1 for e in events if e["event"] == "tasks_clarify_deny") == 1

    stats = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "stats.py"), str(log)],
        capture_output=True, text=True, timeout=30,
    )
    assert stats.returncode == 0, stats.stderr
    assert "1 denied by the clarify gate" in stats.stdout
    assert "1 denied for clarification" in stats.stdout
