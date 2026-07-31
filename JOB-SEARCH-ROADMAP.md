# Cortex Job Search Roadmap

## V1 — Gmail Analytics ✅

- Gmail OAuth authentication
- Read-only Gmail access
- Count job rejection emails
- Count application confirmation emails
- Unique-message deduplication
- Start-date filtering
- Credentials excluded from Git

## V2 — Daily Dashboard 🚧

Goal: produce one clear job-search status report on demand.

Dashboard metrics:

- Applications submitted since 2026-06-22
- Rejections since 2026-06-22
- Applications submitted yesterday
- Rejections received yesterday
- Applications submitted during the last 7 days
- Rejections received during the last 7 days
- Read-only access only

Out of scope:

- Scheduled daily delivery
- Interviews and offers
- Semantic LLM classification
- Sending or modifying email

## V3 — Semantic Email Classification

Replace phrase-only matching with an LLM-assisted classifier.

Categories:

- Application confirmation
- Rejection
- Recruiter outreach
- Interview invitation
- Assessment request
- Offer
- Irrelevant email

Requirements:

- Confidence score
- Evidence from the email
- Human-review queue for uncertain classifications
- No email modification

## V4 — Company and Role Analytics

Extract and analyse:

- Company
- Role title
- Location
- Application source
- Application date
- Rejection date
- Time to response
- Response rate by company, role and industry

## V5 — Job Search Funnel

Track:

- Applied
- Recruiter response
- Screening
- Interview
- Final interview
- Offer
- Rejected
- Withdrawn

Requirements:

- One application record per company and role
- Deduplication
- Manual correction support
- Funnel conversion metrics

## V6 — AI Job Search Chief of Staff

Generate actionable insights:

- Which roles produce the highest response rate
- Which sectors produce the most rejections
- Which application channels work best
- Where applications stall
- Recommended weekly priorities
- Follow-up reminders
- Daily and weekly executive summary

Safety boundaries:

- Read-only Gmail by default
- Never send email without human approval
- Never apply to jobs automatically without human approval
- Never modify or delete messages
- Clearly distinguish facts from AI-generated recommendations