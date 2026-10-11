---
name: project-design
description: Create comprehensive PROJECT_PLAN.md and ARCHITECTURE.md documents for software projects. Use this skill when the user wants to design a new project, plan system architecture, create development roadmaps, define project phases, establish technical specifications, or set up project documentation. This skill triggers on mentions of "project plan", "architecture doc", "system design", "roadmap", "tech spec", "design document", or when the user is starting a new project and needs planning structure. Also use when iterating on existing project documentation or adding new phases to an ongoing project plan.
---

# Project Design Skill

A skill for creating and maintaining two core project documents:

1. **PROJECT_PLAN.md** — Phase-by-phase progress tracker with acceptance criteria
2. **ARCHITECTURE.md** — System design, tech stack, and technical decisions

These documents serve as the single source of truth for:
- What the project is building
- How the system is architected  
- Where we are in the development timeline
- What remains to be done

## When to Use This Skill

Use this skill when:
- Starting a greenfield project and need structure
- The user says "design this system" or "plan this project"
- Adding new capabilities to an existing project
- Re-architecting or refactoring existing systems
- Creating onboarding docs for new team members
- Preparing project documentation for stakeholders

## Output Format

Always produce **both** documents (even if the user only asks for one):

```
project-root/
├── PROJECT_PLAN.md    # Progress tracker + phase checklist
├── ARCHITECTURE.md    # System design + tech decisions
└── (other project files)
```

These files are living documents — update them as the project evolves.

## Workflow

### Step 1: Gather Requirements

Before writing, understand:

1. **Project goal** — What problem does this solve? Who are the users?
2. **Constraints** — Budget, timeline, team size, existing tech stack
3. **Scope boundaries** — What's in v1? What's explicitly deferred?
4. **Integration points** — External APIs, databases, services
5. **Non-functional requirements** — Performance, security, scale targets

Ask the user these questions if not already answered in context.

### Step 2: Write ARCHITECTURE.md First

The architecture document informs the project plan. Structure it as:

```markdown
# [Project Name] — Architecture

## 1. Goals & Non-Goals
### Goals (what we WILL build)
### Non-Goals (what we WON'T build — prevents scope creep)

## 2. Core Principles
1. [Guiding principle, e.g. "Markdown is the universal intermediate format"]
2. [Another principle]

## 3. System Overview
[ASCII diagram or description of data flow]

## 4. Tech Stack
| Component | Library | Role |
|---|---|---|
| [e.g. Vector DB] | [e.g. Qdrant] | [what it does] |

## 5. Project Structure
```
src/
├── module/
│   └── file.py
```

## 6-15. [Domain-specific sections]
- Ingestion Pipeline
- Data Model
- API Design
- Authentication
- etc.

## 16. Implementation Status
| Phase | Status | Description |

## 17. Decision Log
| Decision | Chosen | Rejected | Reason |

## 18. Future Work
[Stretch goals and Phase N items]
```

**Key rules for ARCHITECTURE.md:**
- Every decision MUST have a reason (tradeoffs documented in Decision Log)
- Include ASCII diagrams for data flow — they survive copy-paste better than images
- Tech stack table includes versions and explicit "avoided" alternatives
- Project structure shows the actual file tree, not abstract modules
- Configuration table lists every tunable with defaults

### Step 3: Write PROJECT_PLAN.md

The project plan is the execution tracker. Structure it as:

```markdown
# [Project Name] — Project Plan & Progress Tracker

## Phase 0 — Project Setup [STATUS]
- [x] Task 1
- [ ] Task 2

## Phase 1 — [Feature Area] [STATUS]
**Goal:** One-sentence objective

### New modules
- `src/path/file.py` — responsibility

### Acceptance
1. [Testable criterion]
2. [Testable criterion]

## Phase 2 — [Next Feature] [STATUS]
...

## Phase N — Stretch Goals [⏸️]
[Optional features, only if time permits]

## Currently Working On
[What phase is active right now]

## Quick Status
| Phase | Status | % |
```

**Status legend:** ✅ done · 🚧 in progress · ⬜ pending · ⏸️ deferred · ❌ cancelled

**Key rules for PROJECT_PLAN.md:**
- Each phase has a single-sentence **Goal** — if you can't state it in one sentence, split the phase
- Every phase has **Acceptance** criteria — how do we know it's done?
- Module paths are relative to project root (`src/...` not `core/...`)
- Dependencies are called out explicitly (what new packages are needed)
- "Deferred to Phase N" notes prevent scope creep — acknowledge the idea, park it
- "Known limitations" are honest, not apologetic — document workarounds

### Step 4: Maintain Both Documents

As implementation progresses:

1. **Update PROJECT_PLAN.md** — Mark tasks done, move to next phase, update percentages
2. **Update ARCHITECTURE.md** — Add Decision Log entries for new choices, update Implementation Status, document surprises
3. **Cross-reference** — ARCHITECTURE.md links to PROJECT_PLAN.md for details; PROJECT_PLAN.md links to ARCHITECTURE.md for design rationale

## Progressive Disclosure

This skill bundles reference files for detailed guidance:

- `references/PROJECT_PLAN.md` — Full example of a completed project plan
- `references/ARCHITECTURE.md` — Full example of a completed architecture document

Read these when:
- You need to see what a "good" document looks like
- You're unsure how to structure a specific section
- The user wants production-grade documentation

## Patterns

### For greenfield projects
1. Start with ARCHITECTURE.md Sections 1-5 (Goals, Principles, Overview, Stack, Structure)
2. Then PROJECT_PLAN.md Phases 0-2 (Setup + first features)
3. Defer deep sections (Eval, Observability) until the architecture stabilizes

### For existing projects
1. Read current docs first — don't overwrite without understanding
2. Update ARCHITECTURE.md Decision Log with new choices
3. Append new phases to PROJECT_PLAN.md, don't restructure old ones

### For architecture reviews
1. Read existing ARCHITECTURE.md
2. Check if Decision Log captures the review context
3. Update Implementation Status if recommendations change priorities

## Writing Tips

- **Be specific** in acceptance criteria — "Upload works" is bad; "Upload PDF → see markdown → download .md" is good
- **Document non-decisions** — "We didn't add Redis because BackgroundTasks is sufficient" prevents repeated discussion
- **Version your stack** — `library>=1.2` not just `library`
- **Show, don't tell** — ASCII diagrams > prose descriptions for system flow
- **Honest status** — If Phase 3 is 80% done, say so; don't mark it ✅ until acceptance criteria pass

## Example Trigger Phrases

- "Design a RAG system for our docs"
- "Create a project plan for the migration"
- "I need an architecture document for this API"
- "Plan out the phases for this feature"
- "What's the system design for our chatbot?"
- "Write the tech spec for the new service"
- "Update the roadmap with Phase 4"
