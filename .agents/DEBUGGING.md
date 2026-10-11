# Debugging Methodology

## The Golden Rule of Debugging

**Never guess. Always observe.**

Debugging is not about being smart — it's about being systematic. The fastest way to fix a bug is to understand it completely before touching code.

---

## The Debugging Protocol

### Phase 1: Reproduction
1. **Can you reproduce it consistently?** If not, find the pattern.
2. **What are the exact steps?** Document them precisely.
3. **What is the smallest input that triggers it?** Minimize the reproduction case.
4. **When did it last work?** Use `git bisect` to find the offending commit.

### Phase 2: Observation
1. **Read the error message carefully** — not just the first line, the full stack trace
2. **Check the obvious first** — null pointers, off-by-one, typos, recent changes
3. **Inspect the state** — print/LOG variables at key points; don't assume you know their values
4. **Trace the data flow** — where does the bad value come from?
5. **Check boundaries** — empty collections, first/last items, zero, null, max values
6. **Check the environment** — different OS, different Node version, different database state

### Phase 3: Hypothesis
1. **Form a specific, testable hypothesis** — "The bug is caused by X because Y"
2. **Design an experiment to prove or disprove it** — a test, a log, a minimal change
3. **If disproven, discard and form a new hypothesis** — don't cling to wrong theories
4. **If proven, fix the root cause** — not the symptom

### Phase 4: Fix & Verify
1. **Fix the root cause, not the symptom** — suppressing the error message is not fixing the bug
2. **Verify the fix** — run the reproduction case; it should pass
3. **Verify you didn't break anything else** — run the full test suite
4. **Add a regression test** — ensure this bug never returns
5. **Document what you learned** — if it was tricky, save the next engineer the trouble

---

## Debugging Techniques

### Binary Search (Divide and Conquer)
When you don't know where the bug is:
1. Add a check/log at the midpoint of the suspected code path
2. Determine if the bug is before or after that point
3. Repeat, halving the search space each time

### Rubber Duck Debugging
Explain the bug out loud (or in writing) to an inanimate object. Forcing yourself to articulate the problem often reveals the solution.

### Git Bisect
When you know it worked before:
```bash
git bisect start
git bisect bad HEAD
git bisect good <last-known-good-commit>
# Git will checkout commits; test and mark good/bad until it finds the culprit
```

### Backwards from the Error
Start at the crash/error and trace backwards:
1. What function threw the error?
2. What called that function?
3. What data was passed?
4. Where did that data come from?

### Isolate Variables
Change one thing at a time:
- Does it fail on a different machine?
- Does it fail with a different database?
- Does it fail with different input?
- Does it fail with the previous commit?

---

## Common Bug Categories & Patterns

| Symptom | Likely Causes |
|---|---|
| Works on my machine | Environment differences, missing env vars, different versions |
| Intermittent failure | Race condition, timing issue, external dependency flakiness |
| Works after restart | Memory leak, state corruption, resource exhaustion |
| Only fails with large data | Buffer overflow, timeout, memory limit, algorithmic complexity |
| Works in tests, fails in prod | Different data, different config, different permissions |
| Works in prod, fails in tests | Test isolation, mock mismatch, different environment setup |

---

## Anti-Patterns to Avoid

| Anti-Pattern | Why It Fails |
|---|---|
| **Shotgun debugging** | Randomly changing things hoping something works. You learn nothing and introduce new bugs. |
| **Print-driven development** | Adding `console.log` everywhere instead of understanding the flow. Clutters code and output. |
| **Commenting out code** | "Maybe if I disable this..." You hide the symptom without fixing the cause. |
| **Blaming the compiler/framework** | It's almost never the compiler. Check your assumptions first. |
| **Ignoring the stack trace** | The answer is usually in the stack trace. Read it fully. |
| **Fixing without reproducing** | If you can't reproduce it, you can't verify your fix. |
| **Not adding a regression test** | The same bug will come back. Guaranteed. |

---

## Debugging Tools

- **Stack traces** — Read bottom-up: the error is at the bottom, the call chain above it
- **Breakpoints** — Pause execution and inspect state (better than print statements)
- **Diff tools** — Compare working vs broken state (files, configs, database dumps)
- **Log aggregation** — Centralized logs for tracing requests across services
- **Request tracing** — Trace IDs to follow a single request through multiple services

---

## When to Ask for Help

Stop and escalate when:
- You've spent 30+ minutes without progress
- The bug involves a third-party library you don't control
- It requires access to production data or systems you don't have
- You're tempted to add a hack/workaround instead of a real fix
- The fix would change security-critical code

**Debugging is a skill. The more methodical you are, the faster you solve problems.**
