---
name: clarify
description: Clarification protocol — grill a request into a Requirements Ledger before any delegation, all questions at the START. The chair MUST load this when a job arrives that will be delegated; Rule 0.5 in the injected core only summarizes it.
---

# Clarify Before You Delegate

A worker cannot ask the user anything. Every ambiguity you carry into
a spawn prompt becomes a guess the worker commits to code, and you pay
for it twice — once building the wrong thing, once rebuilding it.
Every question is asked at the START of the job; none in the middle.

Chair only. A subagent that hits an ambiguity reports it to the chair
with SendMessage and waits.

## The gate

Nothing is delegated, planned, or edited until every ambiguity that
would change the work is resolved by the USER'S ANSWER — never by an
assumption. `## Clarified` in the ledger is the record, and the spawn
guard denies without it.

## Read first, then ask

Never ask what the repo answers: open the files the request touches
before the first question. Code shows what IS, never what they WANT —
reading feeds the questions, it answers none of them.

## Scan — seven axes, at EVERY size

Each axis that is unresolved AND would change the work is a question:

1. **Scope edge** — what is deliberately OUT? The unnamed neighbour is
   where scope creep lives.
2. **Acceptance** — how is "done" observed? Name the test, the
   command, the screen.
3. **Constraints** — backward compatibility, dependencies, budget,
   what must not move.
4. **Ownership of choices** — whose taste is each decision? Guessing
   on taste is expensive.
5. **Priority conflict** — when speed, correctness, and token cost
   disagree, which wins here?
6. **Contact with what exists** — which current file, pattern, or
   contract does this touch? Read first.
7. **Failure behaviour** — what happens on error, and what does
   rollback look like?

## Filter — ask only what changes the work

Before asking: *would a different answer produce different code?* If
no, it goes unasked and unwritten. This filter is what makes an
uncapped question loop safe.

## Always asked — where the work lands

One question is exempt from the filter and asked at EVERY size: does
this land on the branch checked out now, or a new one? You cannot
infer it — the branch you happen to be on is where the user was
working, not a decision about this task.

## Ask in rounds, at the start

Front-load. Put every currently open question into as FEW messages as
possible: `AskUserQuestion` carries up to four, `multiSelect` covers
scope choices. Answers re-shape the map — they close some axes and
open others — so the next round is DERIVED from them, and the loop
runs again. No cap on rounds.

Stop condition, literal: no `?` is left unanswered under `## Clarified`
AND you could write the spec for a worker who cannot ask you anything
without guessing at any part of it. "The scan turned up nothing" is
what a clean request and a lazy look produce alike, so it is no test.

Each question: one plain sentence, plus one line saying what changes
depending on the answer. Nameable choices (2-4) → concrete options,
your recommendation first and marked, with its reason. Genuinely
open → your reading and its reason: "I would go with X because Y —
right?" A recommendation is a PROPOSAL, never a recorded answer:
`## Clarified` holds what the USER picked.

## Record, then delegate

Write `## Clarified` at the TOP of ./.workflow/LEDGER*.md, above the
numbered items:

```markdown
## Clarified
- Q1: <question>? -> <the user's answer>
- Q2: <question>? -> <the user's answer>
- Branch: <where the work lands>
```

Then the `- [ ] N.` items, each traceable to an answer. Worker specs
cite items, the items carry the answers, and no worker has to guess.
A later round is appended as a second `## Clarified` block; the hook
reads the union.

The hook denies the spawn on any bullet with a `?` and no `->`/`→`
answer, on an `Assumption:`/`Varsayım:` bullet, on a section with no
`Q -> A` line, and on a missing `Branch:`/`Dal:` line. Answers are
**plain bullets**: ANY checkbox line reads as a ledger item and ends
the section; a `## Clarified` inside a fenced code block is an
example, not a record; a divider or a comment is not an answer.

## After the go, the window is CLOSED

Every question is asked BEFORE the first spawn. If a genuine unknown
appears anyway, STOP: hold the work, ask the user, append the answer
under `## Clarified`, and name it a clarify MISS in the close report —
the signal that the scan or the read was too narrow.

## Red flags

| Thought | Reality |
|---------|---------|
| "I get the gist, I'll start" | The gist is the part you already knew. The ambiguity is the rest. |
| "I'll infer it from the code" | Code shows what IS, never what they WANT. |
| "I'll write it as an assumption" | An assumption is a question you chose not to ask. Ask it. |
| "Asking looks slow" | One round costs a message. A wrong build costs the session. |
| "I'll ask when I get there" | You get there with three workers running. Ask before the go. |
| "The worker will figure it out" | Workers cannot reach the user. Your ambiguity becomes their guess. |
| "Nothing here is ambiguous" | The branch question is still asked and recorded — the section is never empty. |
