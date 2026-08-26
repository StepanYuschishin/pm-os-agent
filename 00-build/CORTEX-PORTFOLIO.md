# Cortex — Agentic Job Search Operations System

## Product Summary

Cortex is a personal agentic AI system that monitors my job-search activity,
classifies recruiting emails, maintains job-search metrics, identifies safe
rejection emails that can be answered, autonomously sends approved replies,
and delivers scheduled job-search dashboards.

## Problem

A high-volume job search creates repetitive operational work:

- tracking submitted applications;
- tracking rejections;
- distinguishing recruiting emails from unrelated messages;
- monitoring recent job-search performance;
- responding to rejection emails;
- repeatedly reviewing Gmail for changes.

Doing this manually creates overhead without materially improving the job search.

## User

Primary user: a professional running a high-volume job search.

Current deployment: my own job-search workflow.

## Product Goal

Reduce repetitive job-search operations while preserving human control over
high-risk communication and preventing unsafe autonomous actions.

## Core Workflow

Gmail
↓
Candidate email retrieval
↓
AI semantic classification
↓
Local classification cache
↓
Job-search state / metrics
↓
Two action paths:

1. Analytics
   → calculate metrics
   → generate dashboard
   → scheduled email delivery

2. Rejection automation
   → detect rejection
   → evaluate replyability
   → apply confidence + sender + subject guardrails
   → duplicate/thread protection
   → send approved template reply

## Agentic Capabilities

Cortex can:

- retrieve Gmail messages;
- classify job-search emails using an LLM;
- maintain persistent classification state;
- calculate job-search metrics;
- identify actionable rejection emails;
- make bounded decisions about whether an email is safe to answer;
- send predefined replies when all guardrails pass;
- generate and send scheduled dashboards.

## Guardrails

Autonomous rejection replies require:

- REJECTION classification;
- confidence >= 0.95;
- rejection-specific semantic evidence;
- replyable sender;
- non-blocked subject;
- no self-sender;
- no previously answered message;
- no previously answered thread;
- maximum batch size of 20.

The agent therefore has bounded autonomy rather than unrestricted Gmail access.

## Architecture

External system:
Gmail API

Intelligence:
OpenAI semantic classifier

State:
Local classification cache
Local rejection-reply ledger

Execution:
Python orchestration

Scheduling:
macOS launchd

Outputs:
Scheduled Cortex Job Search Dashboard
Autonomous safe rejection replies

## Current Product Metrics

Production data as of August 2026:

- 387 applications detected
- 147 rejections detected
- scheduled dashboard delivery
- autonomous rejection-reply workflow
- message-level duplicate protection
- thread-level duplicate protection

## Reliability Improvement

Initial implementation repeatedly rescanned and reclassified historical Gmail
messages.

Observed runtime:
~10–30 minutes, with some scheduled executions hanging significantly longer.

Root cause:
expensive repeated external Gmail/LLM work rather than the dashboard computation itself.

Solution:
introduced persistent semantic-classification caching and reused one classified
snapshot for dashboard calculations.

Observed cached runtime:
~9 seconds.

This changed the architecture from repeated historical computation toward
incremental stateful processing.

## Product Status

Working personal production system.

Current focus:
portfolio packaging and productization rather than additional feature expansion.