# Memory & Context: Cortex PM Chief-of-Staff Agent

> Module 4 · Memory & Context

## 1. Context budget

_What does each loop iteration actually receive, and why? (You can't fit everything, what's the priority order?)_
Gets:
- Current user request
- Selected Gmail thread
- Retrieved recruiter emails
- Job-search preferences

Avoids:
- Entire mailbox
- Old unrelated threads
- Previous drafts

## 2. Retrieve vs. long-context: per source

For each data source, decide: **retrieve** (narrow a large/changing corpus to the relevant slice) or **long-context** (just include a bounded set you can reason over).

| Source | Size / volatility | Decision | Why |
|---|---|---|---|
| Gmail mailbox | Large, continuously changing | Retrieve | The mailbox is large and volatile; retrieve only messages relevant to the current job-search task using sender, subject, labels, keywords, and date filters. |
| Relevant Gmail thread | Small, bounded for the selected conversation | Long-context | Once the relevant thread is identified, include the complete thread so Cortex can understand the conversation history and draft a grounded response. |
| Current user request | Small, live, this run only | Long-context | The complete current request is required to understand the task and should remain isolated to this run. |
| Job-search preferences and rules | Small, slow-changing | Long-context | This is a bounded set of persistent rules such as target roles, locations, salary expectations, tone, and approval requirements. |

## 3. Retrieval quality plan

_Which of these apply, and how? (This is what separates modern agentic retrieval from naive "embed → top-k → stuff".)_

| Retrieved source | Routing | Document grading | Reranking | Self-verification | Caching |
|---|:---:|:---:|:---:|:---:|:---:|
| Gmail mailbox | ✓ | ✓ | ✓ | ✓ | – |

### Why these moves apply

- **Routing:** Cortex must query Gmail only when the task requires email evidence, such as finding recruiter messages, checking follow-ups, or preparing a reply.
- **Document grading:** Every retrieved email must be checked for relevance to the current vacancy, recruiter, company, or conversation.
- **Reranking:** Relevant recruiter emails may be buried among newsletters, automated alerts, and similarly worded messages, so the strongest and most recent matches should rank first.
- **Self-verification:** Every claim about a recruiter, interview stage, salary, deadline, or requested action must be supported by the retrieved email or thread.
- **Caching:** Do not rely on persistent caching because the mailbox changes continuously; retrieve current results for each run.


## 4. Memory map (your PM brain)

| Memory type | What Cortex stores | Lifetime |
|---|---|---|
| Working | The current user request, retrieved Gmail results, the selected email thread, and the reply draft being prepared | This run only |
| Episodic | Prior interactions with the same recruiter, company, vacancy, or Gmail thread | Per thread or job opportunity; ages out when no longer active |
| Semantic | Stable job-search preferences: target roles, preferred locations, salary expectations, communication style, approval rules, and known recruiter/company facts | Long-lived; updated deliberately |
| Shared | Findings passed between retrieval, drafting, critic, and human-review steps, such as selected emails, extracted facts, and validation results | Scoped to the current agent workflow |

## 5. Memory risks & mitigations

| Risk | Where it affects Cortex | Mitigation |
|---|---|---|
| Drift | Stored job-search preferences, recruiter status, or opportunity stage no longer reflect reality | Reconfirm important preferences periodically and retrieve current opportunity status from Gmail before acting |
| Poisoning | An incorrect claim from an email, forwarded message, or generated draft is saved and later treated as fact | Validate facts against the original Gmail message before writing them to persistent memory; store source references |
| Staleness | Cortex remembers an old interview stage, deadline, salary discussion, or recruiter request | Use TTL for volatile facts and re-fetch the latest Gmail thread before drafting or making a recommendation |
| PII / retention | Personal email content, phone numbers, compensation details, attachments, or confidential information are stored longer or shared more broadly than needed | Store the minimum necessary data, scope access per workflow, apply retention limits, and require human approval before sending or exposing sensitive content |

