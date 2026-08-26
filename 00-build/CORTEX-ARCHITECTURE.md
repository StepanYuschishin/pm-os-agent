# Cortex — Architecture & Agent Flow

## 1. High-Level Architecture

User / Schedule
↓
macOS launchd
↓
Cortex Orchestrator
↓
Gmail Retrieval Layer
↓
Semantic Classification Layer
↓
Persistent Local State
↓
Decision / Guardrail Layer
↓
Two Execution Paths

A. Analytics Path
→ aggregate job-search metrics
→ generate dashboard
→ send dashboard email

B. Rejection Automation Path
→ detect rejection
→ evaluate replyability
→ enforce guardrails
→ prevent duplicate replies
→ send bounded reply

## 2. Core Components

### Scheduler
macOS launchd triggers Cortex automatically on schedule.

### Orchestrator
`send_dashboard.py`

Coordinates the full run:
1. discover replyable rejection emails;
2. send safe replies;
3. generate dashboard;
4. email dashboard;
5. terminate if the run exceeds the configured maximum runtime.

### Gmail Integration Layer
`tools.py`

Responsible for:
- Gmail authentication;
- retrieving candidate emails;
- reading email metadata and body;
- sending approved rejection replies;
- sending dashboard emails.

### AI Classification Layer
OpenAI semantic classifier.

Each relevant email is classified into one of:

- APPLICATION_CONFIRMATION
- REJECTION
- INTERVIEW
- RECRUITER_REPLY
- OTHER

Classification includes:
- label;
- confidence;
- semantic reason.

### Persistent State

`job-search-classifications.json`

Stores:
- classification;
- confidence;
- semantic reason;
- thread ID;
- date;
- subject;
- sender;
- reply-to;
- snippet.

Purpose:
avoid repeatedly fetching and reclassifying historical email.

`rejection-replies.json`

Stores successfully handled rejection messages and thread IDs.

Purpose:
prevent duplicate autonomous replies.

### Guardrail / Decision Layer

Before Cortex can reply, all conditions must pass:

REJECTION
↓
confidence >= 0.95
↓
reason contains rejection evidence
↓
sender is replyable
↓
subject is safe
↓
not self-sent
↓
message not previously answered
↓
thread not previously answered
↓
batch cap not exceeded
↓
SEND

## 3. Agent Flow

### Step 1 — Trigger

Cortex is triggered automatically by macOS `launchd`.

The user does not need to open Cursor or Terminal.

### Step 2 — Discover Job-Search Emails

Cortex queries Gmail for a broad candidate set using job-search-related terms such as:

- application
- candidate
- recruiter
- interview
- hiring
- position
- role
- unfortunately

The candidate set is deduplicated by Gmail message ID.

### Step 3 — Retrieve or Reuse State

For each candidate message:

IF metadata + classification exist in local cache:
→ reuse cached state

ELSE:
→ fetch Gmail message
→ extract metadata/body
→ send content to semantic classifier
→ persist classification + metadata

This prevents repeated expensive Gmail reads and LLM calls.

### Step 4 — Semantic Classification

The LLM classifies each relevant email into a job-search state.

The classifier is instructed to prefer the most specific hiring-state category.

Example:

"Thank you for applying, but we decided to move forward with another candidate"

→ REJECTION

not:

→ APPLICATION_CONFIRMATION

### Step 5 — Rejection Decision

For every email classified as REJECTION, Cortex evaluates whether autonomous reply is permitted.

The decision is bounded by explicit infrastructure-level rules.

If any guardrail fails:
→ DO NOT SEND

If all guardrails pass:
→ send predefined polite response

### Step 6 — Duplicate Protection

Cortex checks both:

- message ID
- thread ID

This prevents multiple responses to different rejection emails in the same conversation.

### Step 7 — Dashboard Calculation

Cortex uses the classified snapshot to calculate:

- total applications;
- total rejections;
- yesterday's applications;
- yesterday's rejections;
- last 7 days applications;
- last 7 days rejections.

No repeated full Gmail scan is required for each metric window.

### Step 8 — Dashboard Delivery

Cortex emails the final dashboard containing:

- cumulative metrics;
- yesterday;
- last 7 days;
- autonomous actions taken during the current run;
- system capabilities.

### Step 9 — Exit

Normal run:
→ exit code 0

If the overall run exceeds its configured safety ceiling:
→ terminate instead of hanging indefinitely.

## 4. Autonomy Boundary

Cortex is not fully autonomous.

It has bounded authority.

### Cortex may autonomously:

- retrieve job-search emails;
- classify emails;
- update local state;
- calculate metrics;
- identify safe rejection responses;
- send predefined rejection replies;
- send dashboards.

### Cortex may not:

- compose arbitrary recruiter messages;
- negotiate salary;
- accept or reject offers;
- schedule interviews;
- modify applications;
- apply for jobs;
- respond to ambiguous hiring messages;
- bypass sender or thread guardrails.

The key design principle is:

Autonomy is granted only where the cost of a wrong action is low and the decision can be constrained by explicit rules.

## 5. Architecture Evolution

### V1 — Naive historical processing

Each run repeatedly:
- searched historical Gmail;
- fetched full messages;
- reused only partial classification cache;
- recalculated multiple dashboard windows independently.

Observed runtime:
~10–30 minutes.

Some runs became stuck significantly longer.

### V2 — Stateful cached architecture

Cortex now:
- persists email metadata with classification;
- avoids repeated historical full-message retrieval;
- avoids repeated LLM classification;
- calculates dashboard windows from one classified snapshot.

Observed cached runtime:
~9 seconds.

Approximate improvement:
~60x faster on a normal cached run.