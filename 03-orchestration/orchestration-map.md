# Orchestration Map: Cortex PM Chief-of-Staff Agent

> Module 3 · Orchestration & Subagents, ★ Deliverable 3
>
> Builds on your M2 Loop Spec. Only split one agent into a team when there's a real reason, coordination has a cost.

## 1. Why split? (or why not)

_Run the default-to-simple check. Do you actually need subagents/a fleet? What's the real reason (separation of concerns · parallelism · independent validation · context-window pressure)? If not, say so and stop here._
**Current design:** Cortex is a hook loop triggered by an inbound PM task. It retrieves project context and activity, drafts a status update, proposes backlog stories, and stops for human approval.

| Reason to split | Applies? | Why / why not |
| --- | --- | --- |
| Separation of concerns | No | Drafting the update and proposing stories can remain within one agent because they use the same project context and contribute to one deliverable. |
| Parallelism | No | The current tasks are short and mostly sequential, so parallel execution would add coordination cost without meaningful time savings. |
| Independent validation | Yes | A separate critic should review the draft because the agent that created the output may inherit its own blind spots. |
| Context-window pressure | No | The current project activity, norms, past updates, and draft fit within a manageable context window. |

**Decision:** Keep Cortex as one lead agent with one independent Critic / Validator subagent. No broader multi-agent team is justified.

## 2. Topology

**Pattern:** single + subagent (sequential)

```
           Inbound PM task
                  │
                  ▼
              [ Cortex ]
                  │
        Retrieves project context
        Drafts status update
        Proposes backlog stories
                  │
                  ▼
      [ Critic / Validator ]
         │             │
      Pass          Fail
         │             │
         ▼             ▼
 Human approval   Return to Cortex
   checkpoint      (max 2 revisions)
                        │
                        ▼
                 Escalate to human
```

## 3. Roster

| Agent / subagent | Responsibility | Runs which Loop Spec |
|---|---|---|
| Cortex | Retrieves project context, drafts status updates, proposes backlog stories | M2 Hook Loop |
| Critic / Validator | Independently validates the draft before it reaches the PM | Validation Loop |

## 4. Communication & hand-offs

_What passes between the parts? Any protocol (MCP / A2A, optional, note if used)._
- Cortex → Critic
  - Draft status update
  - Story proposals
  - Retrieved project context

- Critic → Cortex
  - Pass / Fail result
  - Validation findings
  - Required revisions

- Critic → Human
  - Escalation after two failed revisions

Protocol:
- Internal in-process hand-off.
- MCP and A2A are optional and not required.

## 5. The validator

- **What the critic checks:** _grounded claims · norms compliance · no confidential leak · nothing posted/committed_
- **Fail action:** _what happens when it fails (retry · revise · escalate to human)_

**What the critic checks:**

- Every claim is grounded in retrieved project data.

- No invented dates, metrics, or issue status.

- Project names, PRs, and issue IDs match the retrieved data.

- Story proposals stay within the configured queue limit.

- The draft follows the team's communication norms.

- No confidential information is exposed.

- Nothing is posted, committed, or approved automatically.

**Pass action:**

- The draft advances to the Human-in-the-Loop approval checkpoint.

**Fail action:**

- Return the draft to Cortex for revision.

- Maximum 2 revision attempts.

- If validation still fails after 2 revisions, escalate to a human reviewer.

- Record the validation failure in the execution log.

## 6. State: shared vs isolated

_What's shared across the fleet vs kept isolated per subagent (carry from M2)._

### Shared
- Project context
- Project activity
- Team norms
- Previous updates
- Current draft

### Isolated
- Critic reasoning
- Validation findings
- Revision history

## 7. Cost & latency budget
s
_Coordination has a price. Rough token/latency cost of the fleet vs a single agent. (Forward-link to M5 bounds.)_
The validator adds one additional model call per draft.

Worst case: up to 3 validation calls (initial check + 2 revision checks) before escalation to a human.

This adds a small latency overhead but significantly improves output quality and safety.

These limits are enforced by the Bounds & Evals configuration (Module 5).
