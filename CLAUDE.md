# CLAUDE.md

Project rules for Claude Code. Keep this file LEAN — it is re-read on every turn,
so every line here is a tax. If a rule doesn't change Claude's behavior, delete it.

## Core working style
- Think before coding. State assumptions first; if uncertain, ASK before implementing.
- If multiple approaches exist, name them + the one-line tradeoff. Don't silently pick.
- Simplest thing that works. No speculative features, abstractions, config knobs, or
  error handling for impossible cases. If 200 lines could be 50, write 50.
- Surgical edits only. Touch only what the task needs. Don't refactor, reformat, or
  "improve" adjacent code. Match the existing style even if you'd do it differently.
- Only delete dead code that YOUR change created. Mention pre-existing dead code,
  don't remove it unasked.
- Every changed line must trace directly to my request.

## Verify your work (highest-leverage rule)
- Turn tasks into checks: "add validation" -> write failing tests for bad input, then
  make them pass. "fix bug" -> write a test that reproduces it, then fix.
- Run the SINGLE relevant test, not the whole suite, after a change. Typecheck/lint
  before saying you're done.
- If you can't verify something, say so. Never claim success you didn't actually check.

## Output discipline (saves tokens AND my attention)
- Default to concise. Do the work, then explain briefly. No "Here's what I'll do" preambles.
- Don't paste large files or full command output back to me. Summarize and reference
  paths + line numbers instead.
- For anything that requires reading many files (codebase research, "how does X work"),
  use a SUBAGENT so the exploration doesn't fill our main context.

## Explaining changes (the learning log)
When I ask for a feature/fix, OR when I say "explain this change":
- Follow the `explain-change` skill format.
- Write the full explanation to DECISIONS.md (append) and into the commit body.
- In chat, give me only a 2-3 line summary + "-> logged to DECISIONS.md".
- Only dump the full explanation into chat if I explicitly say "show it here".

## Commits
- One logical change per commit. Conventional Commits: `type(scope): subject` (<=50 chars).
- Commit body explains WHY, not what. Point to the matching DECISIONS.md entry.
- Don't commit unless I ask or I've said "commit when done".

## Repo hygiene — do not read or edit these
node_modules/, dist/, build/, .next/, out/, vendor/, coverage/, *.lock, *.min.js
- Ask before adding a new dependency. Prefer the standard library / existing deps.

## Commands
- Install: `pip install -r requirements.txt`
- Run / dev (API + UI): `uvicorn api.main:app --reload` (UI served at http://localhost:8000/)
- Test (single file): `pytest tests/test_<module>.py -v`
- Lint / format: `ruff check . && ruff format --check .`
- Typecheck: `mypy . --ignore-missing-imports`
