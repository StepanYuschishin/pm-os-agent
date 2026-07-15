# Loop Spec: Cortex PM Chief-of-Staff Agent

> Module 2 · Loop Engineering, ★ Deliverable 2
>
> Your one-page blueprint for how the work you handed to the agent (M1) actually *runs*.
> An agent is just a prompt that fires itself, this spec says when it fires, what "done" means, and what it needs to do the job. Living document; refine as the course progresses.

## 1. Trigger & loop type

**Chosen type:** Hook (with daily cron backup)

_Why this type? (e.g. a Monday-morning cron that assembles the weekly update, plus a hook on a new PRD to propose stories.)_
Primary trigger: Hook on inbound PM task.
Backup trigger: Daily 9:00 AM cron sweep.

Justification:
Inbound PM work is event-driven, so a hook provides the fastest and cheapest response.
A daily cron sweep catches missed or duplicate events.

## 2. Goal / definition of done

_What outcome is this loop responsible for? For a goal loop, what validation says "done"? (e.g. a status update grounded in real activity, queued for review, nothing posted.)_
Done means a validated draft status update or story proposal is prepared and handed to a human for review without publishing or committing anything.

## 3. Stop conditions

| Condition | What it looks like | What happens |
|---|---|---|
| **Success** | Draft prepared and validated | Hand off to human |
| **Stuck / give up** | Revision cap reached, repeated tool failures, or no progress after several iterations. | Escalate |
| **Escalate to human** | Missing/conflicting data, project not found, approval or posting required | HITL checkpoint |

## 4. State

_What persists across iterations, and what's the scope? (e.g. per-project context and last week's update; no cross-project confidential leakage.)_
Per-project state including previous updates, project context, roadmap decisions, and iteration history.

## 5. The five things every loop needs

| Component | For Cortex |
|---|---|
| **Work tree** (isolated workspace per run) | Separate workspace for each run. |
| **Skills** (reusable capabilities) | Draft status updates, generate story proposals, validate outputs. |
| **Plugins / connectors** (tools & access) | Project activity, roadmap, team norms, past updates. |
| **Subagents** (delegated / validation) | Critic / Validator. |
| **State tracking** | Previous updates, project context, roadmap decisions, and iteration history across runs. |

## 6. Context plan

_What context is written / selected / compressed / isolated each iteration? (Full depth in M4.)_
Write:
- Current draft
- Decisions made
- Revision history

Select:
- Project activity
- Past updates
- Roadmap
- Team norms

Compress:
- Older revision history into summaries

Isolate:
- Large documents and noisy context outside the main loop

## 7. Hand-off to bounds & evals

_Placeholder → M5 `bounds-and-evals.md`: max iterations, timeout, budget, queue cap, kill switch._
See M5 bounds-and-evals.md for max iterations, timeout, budget, queue cap, and kill switch.

## Link to live loop

_[path to your agent in `00-build/`]_
