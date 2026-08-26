# Cortex — Agentic Job Search Operations System

> A working agentic AI system that monitors job-search activity, semantically classifies recruiting emails, maintains persistent state, performs bounded autonomous actions, and delivers scheduled analytics dashboards.

![Cortex Architecture](assets/cortex-architecture.png)

---

## What is Cortex?

Cortex is a personal agentic system built to automate repetitive operations in a high-volume job search.

Instead of manually reviewing Gmail, tracking applications and rejections, calculating job-search metrics, and responding to routine rejection emails, Cortex continuously turns incoming recruiting activity into structured state, analytics, and safe autonomous actions.

The system currently operates against a real Gmail account and runs automatically on schedule.

---

## The Problem

A high-volume job search generates significant operational overhead:

- tracking submitted applications;
- tracking rejections;
- distinguishing recruiting emails from unrelated messages;
- monitoring recent job-search performance;
- responding to routine rejection emails;
- repeatedly reviewing Gmail for changes.

Most of this work is repetitive, while mistakes in external communication can still carry reputational cost.

The product challenge was therefore not simply:

**"Can AI automate the workflow?"**

It was:

**"Which decisions should be automated, and where should autonomy stop?"**

---

## How It Works

Cortex follows a stateful agent workflow:

1. **Trigger** — macOS `launchd` starts Cortex automatically.
2. **Discover** — Gmail is searched for candidate job-search emails.
3. **Retrieve** — previously processed messages reuse persistent local state.
4. **Classify** — new messages are semantically classified with an LLM.
5. **Decide** — rejection emails pass through explicit reply guardrails.
6. **Act** — safe rejection replies can be sent autonomously.
7. **Prevent duplicates** — message and thread-level state prevents repeated actions.
8. **Analyze** — job-search metrics are calculated from one classified snapshot.
9. **Report** — Cortex generates and emails a scheduled dashboard.

---

## AI Classification

Relevant emails are classified into one of five hiring states:

- `APPLICATION_CONFIRMATION`
- `REJECTION`
- `INTERVIEW`
- `RECRUITER_REPLY`
- `OTHER`

Each classification includes:

- label;
- confidence;
- semantic reason.

The classifier evaluates meaning rather than relying only on keyword matching.

---

## Bounded Autonomy

Cortex intentionally does **not** have unrestricted authority.

An autonomous rejection reply is allowed only when all required guardrails pass:

- classified as `REJECTION`;
- confidence ≥ 0.95;
- semantic reason contains rejection evidence;
- sender is replyable;
- subject is not blocked;
- message is not self-sent;
- message has not already been answered;
- thread has not already been answered;
- batch safety limit is not exceeded.

If any check fails:

**DO NOT SEND.**

### Cortex may autonomously

- retrieve job-search emails;
- classify emails;
- maintain local state;
- calculate metrics;
- identify safe rejection replies;
- send predefined rejection responses;
- send scheduled dashboards.

### Cortex may not autonomously

- compose arbitrary recruiter messages;
- negotiate salary;
- accept or reject offers;
- schedule interviews;
- modify applications;
- apply for jobs;
- respond to ambiguous hiring messages;
- bypass guardrails.

The design principle is simple:

> Grant autonomy where the cost of a wrong action is low and the decision can be constrained by explicit rules.

---

## Persistent State

Cortex maintains two local state stores.

### Classification Cache

Stores previously processed email metadata and AI classifications.

This prevents historical emails from being repeatedly fetched and reclassified.

### Rejection Reply Ledger

Stores handled messages and Gmail thread IDs.

This provides idempotency and prevents duplicate autonomous replies.

Runtime state is intentionally excluded from Git.

---

## Reliability Engineering

The first implementation worked functionally but had a serious performance problem.

### V1 — Repeated historical processing

Each execution repeatedly performed expensive Gmail retrieval and LLM classification work.

Observed runtime:

**~10–30 minutes**

Some scheduled runs became stuck significantly longer.

### V2 — Stateful cached processing

The architecture was changed to:

- persist classification metadata;
- reuse previous AI classifications;
- avoid repeated historical full-message retrieval;
- calculate multiple dashboard windows from one classified snapshot.

Observed cached runtime:

**~9 seconds**

This represented approximately a **60× improvement** compared with a typical 10-minute run.

The important architectural change was moving from repeated historical computation toward **stateful incremental processing**.

---

## Current Product Metrics

Production snapshot — August 2026:

- **387** applications detected
- **147** rejections detected
- scheduled job-search dashboard delivery
- autonomous rejection-reply workflow
- AI semantic classification
- persistent classification cache
- message-level duplicate protection
- thread-level duplicate protection
- ~9 second cached execution

---

## Technology

- **Python** — orchestration and business logic
- **OpenAI API** — semantic email classification
- **Gmail API** — environment / read + bounded write actions
- **OAuth 2.0** — Gmail authorization
- **JSON local state** — classification cache and action ledger
- **macOS launchd** — scheduled autonomous execution
- **Git / GitHub** — source control and product documentation

---

## Repository Structure

```text
pm-os-agent/
├── README.md
├── assets/
│   └── cortex-architecture.png
├── 00-build/
│   ├── agent.py
│   ├── tools.py
│   ├── send_dashboard.py
│   └── ...
├── 01-agent-line/
├── 02-loop-design/
├── 03-orchestration/
├── 04-memory-context/
├── 05-bounds-evals/
├── 06-autonomy/
└── deployment/