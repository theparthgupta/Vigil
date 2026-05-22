---
name: explain-change
description: Use when the user asks for a feature or fix and wants it explained, or says "explain this change". Produces a structured record of what changed, why, what the concept is, why it matters here, drawbacks, alternatives, and how to verify — written to DECISIONS.md and the commit body, not dumped into chat.
---

# explain-change

Goal: leave a durable, teachable record of every meaningful change, so the whole
project can be understood end-to-end later — WITHOUT flooding the live chat (which
costs tokens and degrades context).

## Where the output goes
1. Append the full explanation to `DECISIONS.md` (create the file if it's missing).
2. Put a condensed version in the git commit body.
3. In chat, write ONLY: a 2-3 line summary + "-> logged to DECISIONS.md (entry: <title>)".

Do NOT paste the full template into chat unless the user explicitly says
"show me the full explanation here".

## DECISIONS.md entry template
Use this exact structure. Be concrete; keep each section to 2-5 tight sentences. No filler.

---
### <YYYY-MM-DD> — <short title>
**What changed:** files touched + the actual change, in plain language.
**Why:** the problem it solves / the need that triggered it.
**What this is:** 1-2 sentence explanation of the concept, library, or pattern used,
written for someone seeing it for the first time.
**Why it matters here:** what it unlocks or prevents in THIS project specifically.
**Drawbacks / risks:** the real costs — complexity, performance, lock-in, edge cases
left unhandled.
**Alternatives considered:** 1-3 other options, each with a one-line reason it lost.
**How to verify:** the test, command, or observation that proves it works.
---

## Rules
- One entry per logical change, mirroring one commit.
- If the change is trivial (typo, rename, log line), SKIP this skill — a normal commit
  message is enough. Don't manufacture drawbacks/alternatives for non-decisions.
- If you genuinely don't know which alternative is best, list them and ASK before
  implementing rather than guessing.
- DECISIONS.md is append-only and chronological. It is the project's narrative — never
  rewrite past entries.
