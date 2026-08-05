# Project Context

- **NEVER push directly to `main` (or any protected branch).** Always work on a branch and open a PR — even for one-line fixes, even when a direct push would technically succeed (e.g. because branch protection is misconfigured). If you notice branch protection would allow a direct push, that is not permission to use it — open a PR anyway.
- **Stack:** Python
- Prefer package/app source directories (`scripts/`, `scripts/lib/`, `config/`, `templates/`, `.github/workflows/`).
- Commits must be blocked by pre-commit hooks running static analysis (e.g. `ruff`, `mypy`).
- **Do not read** these paths unless they are the direct subject of the task:
  `.venv/`, `venv/`, `env/`, `__pycache__/`, `*.py[cod]`, `*.so`,
  `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/`, `.tox/`, `.hypothesis/`,
  `.pytype/`, `.ipynb_checkpoints/`, `*.egg-info/`, `.eggs/`, `.uv/`,
  `htmlcov/`, `conda-meta/`, `dist/`, `build/`, lock files.
- Cursor users: see `.cursorignore` for indexing exclusions (separate from `.gitignore`).

## Codebase-Memory-MCP

- **Critical rule:** For code discovery, navigation, and impact analysis, use `codebase-memory-mcp` first. Do not start with grep/glob for code symbols.

### Discovery Order (Mandatory)

1. `search_graph` — find functions, classes, routes, and variables by name/pattern
2. `trace_call_path` — identify callers/callees and impact
3. `get_code_snippet` — read implementation for exact qualified names
4. `query_graph` — use for multi-hop or aggregate questions
5. `get_architecture` — use for high-level structure when needed

### Fallback Rules (Only When Needed)

Use grep/glob/file search only for:

- string literals, error messages, and config values
- non-code files (`Dockerfile`, YAML/TOML/JSON configs, shell scripts, docs)
- cases where MCP returns insufficient results

### Required Self-Check Before Finalizing

- Confirm MCP graph tools were used for code discovery
- If fallback search was used, explicitly state why MCP was insufficient
- Keep evidence concise: symbol queried, tool used, and result

### MCP Query Tips (Tests)

- In many repos, code files (including tests) are represented primarily as `Module` nodes rather than `File` nodes.
- For test discovery, start with:
  - `search_graph(label="Module", name_pattern=".*test.*")`
  - `search_graph(label="Function", name_pattern="test_.*")`
- `search_code` is content-based grep; it is not a filename index.
- If `label="File"` looks sparse, retry with `label="Module"` before using grep/glob fallback.

# Tokenify — Context & Token Optimization

## Goal
Minimize token consumption and prevent context window pollution while maintaining high accuracy in code generation and task execution.

## Operational Rules

### 1. Context Minimization (Surgical Mentions)
- **Do not read entire directories** unless specifically instructed.
- **Selective Reading:** Before reading a file, check if a summary or the file structure (tree) is sufficient.
- **Exclude Noise:** Automatically ignore lock files (`package-lock.json`, `pnpm-lock.yaml`), build artifacts, and large static assets unless they are the direct subject of the task.

### 2. Information Density
- **Log Pruning:** When analyzing errors, do not ingest entire terminal outputs. Extract only the stack trace and the specific error message.
- **Concise Responses:** Avoid conversational filler ("Certainly!", "I have updated the file..."). Provide the direct solution or the diff.
- **Diffs over Rewrites:** Whenever possible, output only the modified lines (diff format) rather than rewriting a 500-line file to change two variables.

### 3. Task Segmentation
- **Sub-tasking:** If a request is complex (e.g., "Build the API and the UI"), decompose it. Propose to handle the API first, then "Reset" or start a new context for the UI.
- **The "Clean Slate" Protocol:** If a bug remains unresolved after 3 attempts, signal the user to "Hard Reset" the chat to purge the accumulated "hallucination debt" in the current context.

### 4. Modular Thinking
- **Encourage Refactoring:** If a file exceeds 300 lines, proactively suggest breaking it into smaller modules. This makes future edits cheaper and more accurate.
- **Spec-First Workflow:** Always request or generate a minimal test case/spec before implementation. This prevents "shotgun debugging" which wastes thousands of tokens.

### 5. Resource Allocation (Model Matching)
- **Tiered Processing:**
    - Use "Flash" or smaller models for boilerplate, documentation, and simple refactors.
    - Reserve "Pro/Sonnet" models for architectural changes and complex logic.
- **MCP Management:** Deactivate Model Context Protocol (MCP) tools that are not relevant to the current file type (e.g., disable SQL tools when editing CSS).

## Trigger Phrases
- "Applying Tokenify Protocol": When the agent starts pruning context.
- "Context Warning": When the agent detects the chat history is becoming too "heavy" and suggests a new session.

# Behavioral Guidelines (Karpathy)

## 1. Think Before Coding
**Don't assume. Don't hide confusion. Surface tradeoffs.**
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.

## 2. Simplicity First
**Minimum code that solves the problem. Nothing speculative.**
- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- If you write 200 lines and it could be 50, rewrite it.

## 3. Surgical Changes
**Touch only what you must. Clean up only your own mess.**
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution
**Define success criteria. Loop until verified.**
- Transform tasks into verifiable goals (e.g. "Add validation" → "Write tests for invalid inputs, then make them pass").
- For multi-step tasks, state a brief plan and verify each step.

## Parallel work (git worktrees)

- **Do not** run two write agents in the same working tree. `git checkout` / `git switch` in one session moves `HEAD` for every session sharing that directory.
- Prefer one linked worktree per concurrent branch under `.worktrees/<slug>/` (must be gitignored). Keep the primary checkout on `main` (or one stable integration branch).
- Bind each write session’s cwd / workspace root to its worktree path — not the primary checkout.
- Write subagents must receive an absolute worktree path and must not `checkout` / `switch` in the parent tree. Read-only explore/review may share the parent tree.
- Prefer harness-native isolation when already present; otherwise `git worktree add`. Full playbook: skill companion `project-onboarding/WORKTREES.md` (or repo docs that mirror it).

## STANDARDS.md

- Global standards: `~/.skills/STANDARDS.md` (authoritative for patterns)
- Project-specific: `./STANDARDS.md` (local copy, authoritative for this repo)
- Agents: Check STANDARDS.md before blocking on architectural questions; use pre-flight checklist for blocker detection
- Planning-system IDs (`ADR-*`, `T-NNN`, `AP-*`, etc.) belong in commit messages / PR threads, not committed prose

## Available MCP Tools

- **codebase-memory-mcp** — graph-first code discovery (see block above)
- **user-github** — PRs, issues, file contents on GitHub
- **user-atlassian** — Jira / Confluence
