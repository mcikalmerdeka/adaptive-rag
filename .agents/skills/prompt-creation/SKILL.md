---
name: prompt-creation
description: Generates a complete, self-contained implementation prompt (a markdown file) for handing to another AI to execute. Use when the user asks to "generate a prompt", "write an improvement prompt", or to prepare a handoff task for a "more advanced AI" — e.g. AI-to-AI prompt handoffs, improvement briefs, refactoring/editing instructions targeted at a specific subsystem. Triggers: "prompt for the AI", "improvement prompt", "hand this to an advanced AI", "create a prompt I can copy", "prompt file". Covers repo auditing, pinpointing exact files to edit, hard-contract detection, brief writing, and acceptance criteria so the receiving AI needs zero repo exploration.
---

# Prompt Creation Skill

A skill for writing **high-quality, copy-paste-ready prompts** that hand a specific implementation task to another (typically stronger or specialized) AI. The goal: the receiving AI lands in the target repo and works **only in the files it was told to work in**, without needing to search or re-derive context the auditor already gathered.

Reference of target quality: `PROMPT_3D_IMPROVEMENT.md` (root of CityCode) — an audit-backed, file-pinned, constraint-complete improvement prompt.

## When to Use

- "Generate a prompt I can pass to an advanced AI to implement X"
- "Prepare an improvement brief for the 3D/rendering/frontend/specialized layer"
- The user explicitly wants only analysis + prompt generation, **not** implementation

Hard rule: when the user asks for a prompt only, do **not** implement anything. Output is analysis + one markdown deliverable.

## Workflow

### Step 1 — Scope Lock (clarify before exploring)

Confirm or infer three things from the user's request; ask ONE question if ambiguous:

1. **Target domain** — which part of the codebase (e.g. "the 3D layer", "the API layer").
2. **Intent** — improvement, new feature, refactor, or repair.
3. **Destination** — where to store the prompt file (ask; default: a new markdown file in the repo root, `PROMPT_<TOPIC>.md`).

### Step 2 — Audit the Target Domain

Do the real exploration yourself — an un-audited prompt produces hallucinated file paths and the receiving AI wastes its budget on repo-wide searching that you already paid for.

Requirements:

- **Read every file in scope end-to-end** — headers, state, wiring, exports, and comments that encode design contracts (e.g. "color is reserved", "deterministic").
- **Map the pipeline** — list the layers and the data flow: source → transforms → consumers. Note what each layer must not change.
- **Pinpoint exact files/paths** — no glob patterns, no "somewhere in components/". Also list "do not touch" paths explicitly.
- **Note cross-file contracts** — exported constants other files depend on, keyed-remount hacks, store-coupled wiring, test-covered invariants. These become the prompt's "hard constraints".
- **Capture environment facts** — framework/library versions from `package.json`, scripts (`lint`/`typecheck`/`test`/`build`), package manager, OS quirks.

### Step 3 — Draft the Prompt File (write-as-you-go — save to disk immediately, do not draft in reasoning)

Store the deliverable as one markdown file with a short preamble and a "PROMPT — copy everything below this line" cut marker, so the human copies everything below it.

The prompt body MUST contain these sections (in this order):

1. **Role & framing** — one paragraph: what the target app/project does at a product level, what the receiving AI is implementing, and that scope is restricted to the listed files.
2. **Environment** — framework + library versions, package manager, OS, dev-command set. One sentence of audit provenance ("facts below are from an actual audit of the repo as of YYYY-MM").
3. **Current architecture** — the data pipeline as numbered pipeline bullets + key types/state shapes verbatim (interface excerpts are worth more than prose). End with an honest "state of things today and why it must improve" paragraph, including design contracts the receiving AI must preserve such as reserved visual channels or determinism requirements.
4. **Files you WILL edit (and only these)** — a three-column table: `File` · `Current responsibility` · `Your changes`. Follow with an explicit "Do not touch" list. Flag "extension only / minor wiring only" files distinctly.
5. **Hard constraints** — numbered list (aim 5–8) of invariants the receiver must not break, each stating the *observable consequence* of violating them (regression tests, platform bugs, visual contracts). Constraints beat instructions — the receiving AI follows these no matter what it innovates around them.
6. **The improvement brief** — the core. Organize by subsystem directories (e.g. "Scene", "Buildings", "Roads"), each item: **bold what it is** + concrete implementation approach (name specific APIs/patterns/techniques) + perf/quality notes + where it lives. Make choices rather than listing options where possible; where genuinely open, offer exactly two paths with a decision rule ("measure, then choose; document in header").
7. **Quality bar & verification** — the exact commands to run and what pass looks like, a manual smoke checklist (user-facing flows to verify once), and behavioral rules (write-as-you-go, no `as any`/`@ts-ignore`).
8. **Explicit non-goals** — bullets of tempting-but-out-of-scope work (redesigns of adjacent UI, new toggles, network assets…), each with a one-phrase reason if not obvious.

Close the prompt with a one-line **Deliverable** sentence stating what "done" looks like in product terms, not just gate terms.

### Step 4 — Self-Check Before Delivering

Run the receiving-AI simulation: "If I had never seen this repo and only this prompt, could I produce `lsp/compile`-clean code touching exactly the right files?"

- [ ] Every file edit is pinned to an exact path; ≤ 1 vague reference. Aim for zero.
- [ ] Hard constraints cover every contract found in the audit (comments, keying hacks, exported constant dependencies, test targets).
- [ ] A "Do not touch" list exists (this is what stops the receiver from "helpfully" refactoring adjacent layers).
- [ ] Environment versions and commands are correct (read from `package.json` / scripts).
- [ ] Improvement brief items name concrete techniques and follow patterns found in the actual code (cite the file/code pattern the receiver should follow — e.g. "reuse the existing `slotFor()` path-hash pattern for stable 'randomness'").
- [ ] Section order matches the spec above; prompt is self-contained (no depends-on-session context).
- [ ] Prompt file stored at the requested destination; the header outside the cut line explains what the file is and that everything below it is copy-verbatim.
- [ ] No implementation was shipped — analysis + file only.

## Template (Condensed; see the Step 3 spec for full field lists)

Quick skeleton:

```markdown
# <Project> — <Topic> Improvement Prompt

> Purpose-of-document line. Everything copied verbatim to the implementing AI.

---

## PROMPT (copy everything below this line)

<role framing + scope restriction>

**Environment:** versionX / Y / Z · OS · package manager · audit provenance

### 1. Current architecture
### 1. Current architecture
<numbered pipeline bullets + verbatim shapes + honest "today" description, including contracts to preserve>

### 2. Files you WILL edit (and only these)
<3-column table + Do-not-touch list>

### 3. Hard constraints
<numbered list of invariants + consequences>

### 4. The improvement brief
<by-subsystem items with technique + location>

### 5. Quality bar & verification
<exact commands + manual smoke checklist + write-as-you-go>

### 6. Explicit non-goals
<bulleted>

**Deliverable:** <product-level one-liner>.
```

## Antipatterns

- **Prompt without audit** — the receiving AI gets vague "in components/", re-derives everything, and edits the wrong file.
- **No hard-contract section** — the receiver breaks deterministic layouts/remount keys/invariants and the change ships broken.
- **Options instead of choices** — "use A, B, C or whatever you like" is indecisive; prefer decisive instructions with a fallback decision rule and a place to leave a note.
- **No verification section** — without an explicit quality bar the receiver assumes "done" means "compiles". Always state the verification commands and that they must prove results.
- **No explicit "Do not touch" set** — capable receivers will refactor adjacent code if not forbidden.
- **Non-self-contained content** — the prompt must never depend on this session's conversation context; everything the receiver needs reads from the file alone.
- **Implementing anyway** — when the user asked for a prompt only, shipping a code change breaks the boundary the user defined.
