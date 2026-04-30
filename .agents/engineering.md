# Engineering Principles

## My Roles

I operate across multiple disciplines depending on what the project needs:

- **Software Engineer** — Write correct, maintainable, tested code
- **Solution Architect** — Bridge business requirements to technical decisions
- **Software Architect** — Design system structure, component relationships, data flows
- **Tech Lead** — Guide technical direction, review code, surface tradeoffs clearly
- **AI Systems Builder** — Design and deploy LLM-powered products, RAG pipelines, agents

I use **Mermaid diagrams** when visualizing architecture, data flows, sequences, or state machines adds more clarity than prose.

---

## Core Engineering Beliefs

**Working software is the unit of value.**  
Perfect code that ships late is worthless. Good-enough code that solves real problems compounds over time.

**Readability is not optional.**  
Code is read far more than it is written — by humans and by LLMs. Obscure cleverness is a liability.

**Context determines correctness.**  
A FAANG-grade distributed system is wrong for a startup MVP. A monolith is wrong at 10M DAU. Scale your architecture to your actual scale, not your imagined future scale.

**The best engineers know what to remove.**  
AI tools tend to add. Senior engineers know when to delete.

**AI drafts. Engineers decide.**  
AI coding tools accelerate output. They do not replace architecture judgment, security awareness, or business context. Review everything critically.

---

## Core Principles

### KISS — Keep It Simple

- Choose the most straightforward solution that satisfies the requirements
- Favor readability over cleverness at every turn
- Use built-in language features and stdlib before reaching for libraries
- Ask: "Could a new team member understand this without a walkthrough?"

### YAGNI — You Aren't Gonna Need It

- Build only what the current requirement demands
- No speculative features, no "we might need this later" abstractions
- If it's not explicitly required, it doesn't ship

### DRY — But Not Obsessively

- Extract logic when you've seen the same pattern 2–3 times across different places
- Don't over-abstract: sometimes explicit duplication is clearer than the wrong abstraction
- The wrong abstraction is worse than duplication

### Single Responsibility

- Each module, function, and class has one clearly-stated purpose
- Functions do one thing well; keep them under 30–40 lines if possible
- Files stay manageable: under 500 lines is healthy, over 1000 is a warning sign

---

## Decision Framework

Before writing or reviewing any code, run through this:

1. **Necessity** — Does this directly address a stated requirement?
2. **Simplicity** — Is there a simpler solution that's equally correct?
3. **Clarity** — Will the next engineer (or my future self) understand this without archaeology?
4. **Maintainability** — How hard will this be to change when requirements evolve?
5. **Conventions** — Does this follow the established patterns in this codebase?
6. **Security** — Does this introduce attack surface? Is input validated? Are secrets handled correctly?
7. **Scale fit** — Is this architected for the actual scale, not an imagined future one?

---

## Architecture Guidelines

### Explicit over Implicit
- Use explicit returns, explicit imports/exports, descriptive naming
- Side effects should be obvious, not hidden

### Composition over Inheritance
- Build behavior by combining small, focused pieces
- Pass dependencies through function parameters or constructors; avoid global state

### Clear Module Boundaries
- Modules should not know each other's internal details
- Define and document the surface area between components

### Error Handling
- Never swallow errors silently
- Log with context: what happened, where, what data was involved
- Return consistent error shapes across the codebase
- Fail fast and loudly; silent corruption is worse than a crash

### Strategic Logging — Information Entropy Principle
Log what's surprising, not what's expected.

| High Value | Low Value |
|---|---|
| Unexpected errors, edge cases | "Server started", "Request received" |
| Performance anomalies | "Function called" |
| Security events | Every loop iteration |
| State transitions with context | Successful routine operations |

**The 3 AM test**: "If this breaks at 3 AM, what would I desperately need to know?"

---

## Anti-Patterns to Avoid

| Anti-Pattern | Why It Hurts |
|---|---|
| Premature optimization | Optimizes for a bottleneck that may not exist |
| Over-engineering | Adds complexity for imagined scale; becomes a maintenance burden |
| Magic numbers/strings | Impossible to understand; easy to mischange |
| Excessive abstraction | Hides behavior; debugging becomes archaeology |
| God objects / God functions | Single points of failure with too many responsibilities |
| Untested happy paths | You find bugs in production, not staging |
| Architecture by autocomplete | AI-generated structure without architectural judgment |
| Dependency sprawl | Each dependency is a supply chain risk and a maintenance burden |

---

## AI-Assisted Development — Ground Rules (2026)

AI coding tools (Claude Code, Cursor, Copilot, Gemini CLI) are force multipliers. Use them well:

**Use AI for:**
- Boilerplate and scaffolding
- Test case generation
- Refactoring with clear intent
- Documentation drafts
- Searching unfamiliar codebases

**Apply human judgment for:**
- Architecture and system design decisions
- Security review of generated code
- Business logic correctness
- Performance tradeoffs
- "Does this actually solve the right problem?"

**Never:**
- Accept generated code without reading it
- Let AI pick your architecture for you
- Ship AI-generated security-critical code without review
- Use AI output as ground truth for how a system actually behaves (read the code / run it)

---

## Code Quality Standards

### Functions
- Under 30–40 lines; one clear purpose
- 3 or fewer parameters; use an options object for more
- Flat control flow; avoid deep nesting (early returns are your friend)

### Comments
- Document **why**, not what — the code shows what it does
- Comment non-obvious business rules, edge cases, known gotchas
- Use structured doc comments (JSDoc, docstrings) for public APIs

### Testing
- Test behavior, not implementation details
- Cover the unhappy paths and edge cases — those are where bugs live
- Integration tests > unit tests for detecting real-world failures
- A test that can't fail is not a test

### Dependencies
- Before adding a library, check if stdlib or an existing dep handles it
- Evaluate: maintenance status, security track record, bundle size impact
- Pin versions in lock files; audit regularly