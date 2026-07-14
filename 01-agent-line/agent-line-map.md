# Agent Line Map: Cortex PM Chief-of-Staff Agent

> Module 1 · The Agent Line

## The workflow, decision by decision

List every discrete decision or action in your agent's workflow, then score each one and place it **above** the line (a human owns it) or **below** (the agent owns it). Borderline calls get an HITL checkpoint.

| Decision / action | Reversibility (H/M/L) | Blast radius (H/M/L) | Measurability (H/M/L) | Above / Below | HITL? |
|---|---|---|---|---|---|
| Identify the target project and requested deliverables from the inbound task brief |H |L |H | | |
| Look up the project record (status, flags, linked PRD) |H |L |H | | |
| Pull recent engineering activity (merged PRs, open issues, Sev-1s) |M |L |M | | |
| Search past updates for tone and precedent |H |L |M | | |
| Load team norms / PM playbook |H |L |M | | |
| Draft the weekly leadership status update grounded in pulled data |H |L |L | | |
| Queue next-sprint story proposals within the auto-queue cap |H |L |M | | |
| Post the approved update to leadership / commit a public ship date |L |H |H | | |

## Agent anatomy (sketch)

- **Model:** _your default fast model + when you escalate to a frontier model, and why_
- **Tools:** _project + activity lookup (read) · past-update search · roadmap · team norms · story proposal (capped) …_
- **Memory:** _what persists across runs (roadmap, decisions, norms) vs. purged_
- **Loop:** _placeholder, defined in M2 loop-spec.md_
- **Bounds:** _placeholder, defined in M5 bounds-and-evals.md_
- **Evals:** _placeholder, defined in M5 bounds-and-evals.md_

## The golden rule, applied

_One sentence per above-the-line decision: why it stays human (which of reversibility / blast radius / measurability failed)._

## Hardest call

_Your toughest "above vs below" decision and how you resolved it. (Share this in `#cohort-channel`.)_
