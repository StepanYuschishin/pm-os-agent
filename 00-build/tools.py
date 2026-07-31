"""Cortex mock tools, the tools your PM chief-of-staff agent is allowed to call.

These are plain Python functions over the files in `fixtures/`. They are imported
directly by `agent.py`, so this file is the single place that defines what Cortex
can and cannot do. Ask your coding agent to add, remove, or tighten a tool here.

Design note that matters for the course: there is deliberately NO publish tool.
Cortex can read and DRAFT a status update, and it can PROPOSE backlog stories (which
are capped and queued for a human), but it can never post to a channel, create or
merge a ticket/PR, commit a ship date, or mark a launch gate. The agent line is
enforced here, in infrastructure, not by a prompt.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

FIXTURES = Path(__file__).parent / "fixtures"

# Commitment bound (M5). A run that tries to queue more than this many backlog
# stories is rejected by infrastructure and must be escalated, even if the PRD
# would justify more. Auto-committing a flood of "real" work is the money analog.
MAX_QUEUE_ITEMS = int(os.environ.get("CORTEX_MAX_QUEUE_ITEMS", "10"))

GMAIL_SCOPE = ["https://www.googleapis.com/auth/gmail.readonly"]
CREDENTIALS_FILE = Path(__file__).parent / "credentials.json"
TOKEN_FILE = Path(__file__).parent / "token.json"


def _get_gmail_service():
    """Authenticate and return a read-only Gmail API service."""
    credentials = None

    if TOKEN_FILE.exists():
        credentials = Credentials.from_authorized_user_file(
            TOKEN_FILE,
            GMAIL_SCOPE,
        )

    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())

    if not credentials or not credentials.valid:
        if not CREDENTIALS_FILE.exists():
            raise FileNotFoundError(
                f"Missing Gmail credentials file: {CREDENTIALS_FILE}"
            )

        flow = InstalledAppFlow.from_client_secrets_file(
            CREDENTIALS_FILE,
            GMAIL_SCOPE,
        )
        credentials = flow.run_local_server(port=0)

    TOKEN_FILE.write_text(credentials.to_json())

    return build("gmail", "v1", credentials=credentials)


def count_gmail_messages(query: str, newer_than_days: int = 60) -> dict:
    """Count Gmail messages matching a query within the selected period.

    This tool is strictly read-only. It cannot send, delete, move, label,
    or modify email.
    """
    query = str(query or "").strip()

    if not query:
        return {"error": "query_required"}

    try:
        days = int(newer_than_days)
    except (TypeError, ValueError):
        return {"error": "invalid_newer_than_days"}

    if days < 1 or days > 3650:
        return {
            "error": "newer_than_days_out_of_range",
            "allowed": "1-3650",
        }

    gmail_query = f'newer_than:{days}d "{query}"'
    service = _get_gmail_service()

    count = 0
    page_token = None

    while True:
        response = (
            service.users()
            .messages()
            .list(
                userId="me",
                q=gmail_query,
                pageToken=page_token,
                maxResults=500,
            )
            .execute()
        )

        count += len(response.get("messages", []))
        page_token = response.get("nextPageToken")

        if not page_token:
            break

    return {
        "query": query,
        "newer_than_days": days,
        "gmail_query": gmail_query,
        "count": count,
        "access": "read_only",
    }

def _load_json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def get_task(which: str = "happy") -> dict:
    """Read the inbound PM task brief to work on.

    Args:
        which: one of "happy", "missing-data", "jailbreak".
    Returns the raw task text plus its source label.
    """
    path = FIXTURES / f"task-{which}.md"
    if not path.exists():
        return {"error": f"no task fixture named '{which}'",
                "available": ["happy", "missing-data", "jailbreak"]}
    return {"which": which, "body": path.read_text()}


def get_project(project_id: str) -> dict:
    """Look up a single project by its ID. Returns {"error": ...} if not found."""
    project_id = str(project_id).strip()
    projects = _load_json("projects.json")
    record = projects.get(project_id)
    if record is None:
        return {"error": "project_not_found", "project_id": project_id,
                "hint": "no such project in the system",
                "known_projects": list(projects.keys())}
    # Return the project WITHOUT its activity blob; activity is a separate tool call
    # so the agent has to deliberately pull it (a teachable retrieval step).
    return {k: v for k, v in record.items() if k != "activity"}


def get_activity(project_id: str) -> dict:
    """Pull recent engineering activity (merged PRs, open issues, Sev-1s) for a project."""
    project_id = str(project_id).strip()
    projects = _load_json("projects.json")
    record = projects.get(project_id)
    if record is None:
        return {"error": "project_not_found", "project_id": project_id}
    return {"project_id": project_id, "activity": record.get("activity", [])}


def search_past_updates(query: str = "") -> dict:
    """Search previous status updates and decisions for tone and precedent (the
    memory/retrieval surface).

    Naive keyword overlap over a small fixture so M4's retrieve-vs-reason lesson is
    concrete: relevant precedent is returned, irrelevant precedent is not."""
    query = (query or "").lower()
    corpus = _load_json("past-updates.json") + _load_json("decision-log.json")
    terms = {t for t in query.replace("#", " ").split() if len(t) > 2}
    hits = []
    for u in corpus:
        haystack = f"{u.get('project','')} {u.get('summary','')} {u.get('theme','')}".lower()
        if terms and any(term in haystack for term in terms):
            hits.append(u)
    return {"query": query, "matches": hits or corpus[:2],
            "note": "prior updates + decisions for precedent, team norms still govern."}


def get_roadmap(query: str = "") -> dict:
    """Return the roadmap. Some items are flagged confidential/embargoed, those must
    never appear in an external or company-wide update. `query` is a hint; the file
    is small enough to return whole so the agent can cite what it relied on."""
    text = (FIXTURES / "roadmap.md").read_text()
    return {"query": query, "roadmap": text,
            "warning": "items marked CONFIDENTIAL must not be shared outside the core team."}


def get_norms(query: str = "") -> dict:
    """Return the team norms / PM playbook. `query` is a hint; the full playbook is
    small enough to return whole so the agent can cite the exact rule it relied on."""
    text = (FIXTURES / "team-norms.md").read_text()
    return {"query": query, "norms": text}


def propose_stories(project_id: str, stories=None, reason: str = "") -> dict:
    """PROPOSE a set of backlog stories for a human to approve. This creates NOTHING
    in the tracker, it queues a request. A batch larger than CORTEX_MAX_QUEUE_ITEMS
    is rejected by infrastructure and must be escalated. This is the commitment bound,
    enforced outside the model (M5)."""
    if isinstance(stories, str):
        stories = [stories]
    if not isinstance(stories, list):
        return {"error": "invalid_stories", "stories": stories}
    if len(stories) > MAX_QUEUE_ITEMS:
        return {"status": "rejected",
                "error": "batch_exceeds_queue_cap",
                "count": len(stories),
                "cap_items": MAX_QUEUE_ITEMS,
                "action": "escalate to a human, do not split the batch to dodge the cap"}
    return {"status": "queued_for_approval",
            "project_id": str(project_id).strip(),
            "count": len(stories),
            "stories": stories,
            "reason": reason,
            "note": "queued for a human to approve, nothing was created in the tracker."}

REJECTION_PHRASES = [
    "unfortunately",
    "we decided to move forward with other candidates",
    "we have decided to move forward with other candidates",
    "we've decided to move forward with other candidates",
    "we decided to move forward with another candidate",
    "we have chosen to move forward with another candidate",
    "we decided to pursue other candidates",
    "we will not be moving forward with your application",
    "we won't be moving forward with your application",
    "not moving forward with your application",
    "unable to move forward with your application",
    "your application was not selected",
    "we regret to inform you",
    "other applicants whose experience more closely matches",
    "other candidates whose experience more closely matches",
    "not selected for this position",
    "not selected to move forward",
    "position has been filled",
]

APPLICATION_SUBMITTED_PHRASES = [
    "your application was submitted successfully",
    "your application has been submitted",
    "application submitted successfully",
    "we have received your application",
    "we've received your application",
    "your application has been received",
    "application received",
    "thank you for submitting your application",
    "thank you for your application",
    "thank you for applying",
]


def _gmail_message_ids_for_phrase(
    service,
    phrase: str,
    after_timestamp: int,
) -> set[str]:
    """Return unique Gmail message IDs matching one exact phrase."""
    gmail_query = f'after:{after_timestamp} "{phrase}"'

    message_ids: set[str] = set()
    page_token = None

    while True:
        response = (
            service.users()
            .messages()
            .list(
                userId="me",
                q=gmail_query,
                pageToken=page_token,
                maxResults=500,
            )
            .execute()
        )

        message_ids.update(
            message["id"]
            for message in response.get("messages", [])
        )

        page_token = response.get("nextPageToken")

        if not page_token:
            break

    return message_ids

def _gmail_message_ids_for_phrase_between(
    service,
    phrase: str,
    start_timestamp: int,
    end_timestamp: int,
) -> set[str]:
    """Return unique Gmail message IDs matching a phrase inside a date range."""
    gmail_query = (
        f'after:{start_timestamp} '
        f'before:{end_timestamp} '
        f'"{phrase}"'
    )

    message_ids: set[str] = set()
    page_token = None

    while True:
        response = (
            service.users()
            .messages()
            .list(
                userId="me",
                q=gmail_query,
                pageToken=page_token,
                maxResults=500,
            )
            .execute()
        )

        message_ids.update(
            message["id"]
            for message in response.get("messages", [])
        )

        page_token = response.get("nextPageToken")

        if not page_token:
            break

    return message_ids

def count_job_search_emails(
    start_date: str = "2026-06-22",
) -> dict:
    """Count job rejections and application confirmations from a date.

    Gmail access remains strictly read-only. Messages matching multiple
    phrases are counted only once.
    """
    try:
        parsed_date = datetime.strptime(start_date, "%Y-%m-%d")
    except ValueError:
        return {
            "error": "invalid_start_date",
            "expected_format": "YYYY-MM-DD",
        }

    # Midnight in Abu Dhabi, UTC+4.
    abu_dhabi_timezone = timezone(timedelta(hours=4))
    start_datetime = parsed_date.replace(tzinfo=abu_dhabi_timezone)
    after_timestamp = int(start_datetime.timestamp())

    service = _get_gmail_service()

    rejection_ids: set[str] = set()
    rejection_breakdown = {}

    for phrase in REJECTION_PHRASES:
        matching_ids = _gmail_message_ids_for_phrase(
            service,
            phrase,
            after_timestamp,
        )
        rejection_ids.update(matching_ids)
        rejection_breakdown[phrase] = len(matching_ids)

    submitted_ids: set[str] = set()
    submitted_breakdown = {}

    for phrase in APPLICATION_SUBMITTED_PHRASES:
        matching_ids = _gmail_message_ids_for_phrase(
            service,
            phrase,
            after_timestamp,
        )
        submitted_ids.update(matching_ids)
        submitted_breakdown[phrase] = len(matching_ids)

    # Prevent rejection messages containing phrases such as
    # "thank you for applying" from being counted as submissions.
    confirmed_application_ids = submitted_ids - rejection_ids

    return {
        "start_date": start_date,
        "timezone": "Asia/Dubai",
        "rejections": len(rejection_ids),
        "applications_submitted": len(confirmed_application_ids),
        "raw_submission_matches": len(submitted_ids),
        "submission_matches_excluded_as_rejections": len(
            submitted_ids & rejection_ids
        ),
        "rejection_phrase_breakdown": rejection_breakdown,
        "application_phrase_breakdown": submitted_breakdown,
        "counting_method": "unique Gmail message IDs",
        "access": "read_only",
    }
    
def _count_job_search_emails_between(
    service,
    start_datetime: datetime,
    end_datetime: datetime,
) -> dict:
    """Count unique job-search emails inside one specific time period."""
    start_timestamp = int(start_datetime.timestamp())
    end_timestamp = int(end_datetime.timestamp())

    rejection_ids: set[str] = set()

    for phrase in REJECTION_PHRASES:
        rejection_ids.update(
            _gmail_message_ids_for_phrase_between(
                service,
                phrase,
                start_timestamp,
                end_timestamp,
            )
        )

    submitted_ids: set[str] = set()

    for phrase in APPLICATION_SUBMITTED_PHRASES:
        submitted_ids.update(
            _gmail_message_ids_for_phrase_between(
                service,
                phrase,
                start_timestamp,
                end_timestamp,
            )
        )

    confirmed_application_ids = submitted_ids - rejection_ids

    return {
        "applications_submitted": len(confirmed_application_ids),
        "rejections": len(rejection_ids),
    }

def get_job_search_dashboard(
    start_date: str = "2026-06-22",
) -> dict:
    """Build an on-demand job-search dashboard from Gmail.

    Gmail access remains strictly read-only.
    """
    abu_dhabi_timezone = timezone(timedelta(hours=4))

    try:
        baseline_date = datetime.strptime(
            start_date,
            "%Y-%m-%d",
        ).replace(tzinfo=abu_dhabi_timezone)
    except ValueError:
        return {
            "error": "invalid_start_date",
            "expected_format": "YYYY-MM-DD",
        }

    now = datetime.now(abu_dhabi_timezone)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    seven_days_ago = today - timedelta(days=7)

    service = _get_gmail_service()

    totals = count_job_search_emails(start_date)

    yesterday_metrics = _count_job_search_emails_between(
        service,
        yesterday,
        today,
    )

    last_7_days_metrics = _count_job_search_emails_between(
        service,
        seven_days_ago,
        now,
    )

    return {
        "dashboard": "Cortex Job Search Dashboard",
        "generated_at": now.isoformat(),
        "timezone": "Asia/Dubai",
        "since": start_date,
        "totals": {
            "applications_submitted": totals["applications_submitted"],
            "rejections": totals["rejections"],
        },
        "yesterday": {
            "date": yesterday.strftime("%Y-%m-%d"),
            **yesterday_metrics,
        },
        "last_7_days": {
            "from": seven_days_ago.strftime("%Y-%m-%d"),
            "to": now.strftime("%Y-%m-%d"),
            **last_7_days_metrics,
        },
        "access": "read_only",
        "note": (
            "Counts use unique Gmail message IDs and phrase-based "
            "classification."
        ),
    }


def format_job_search_dashboard(
    start_date: str = "2026-06-22",
) -> str:
    """Return the job-search dashboard as readable text."""
    dashboard = get_job_search_dashboard(start_date)

    if "error" in dashboard:
        return json.dumps(dashboard, indent=2)

    totals = dashboard["totals"]
    yesterday = dashboard["yesterday"]
    last_7_days = dashboard["last_7_days"]

    return (
        "CORTEX JOB SEARCH DASHBOARD\n"
        "===========================\n\n"
        f"Since: {dashboard['since']}\n"
        f"Applications submitted: {totals['applications_submitted']}\n"
        f"Rejections: {totals['rejections']}\n\n"
        f"Yesterday ({yesterday['date']}):\n"
        f"+{yesterday['applications_submitted']} applications\n"
        f"+{yesterday['rejections']} rejections\n\n"
        f"Last 7 days ({last_7_days['from']} to "
        f"{last_7_days['to']}):\n"
        f"{last_7_days['applications_submitted']} applications\n"
        f"{last_7_days['rejections']} rejections\n\n"
        "Access: Gmail read-only\n"
        "Classification: phrase-based, unique messages"
    )   

# Registry the agent loop reads. Add a tool here and the agent can call it.
# Note what is ABSENT: there is no post_update, no create_issue, no merge_pr,
# no commit_ship_date, no close_bug, no tool that acts on the world.
TOOLS = {
    "get_task": get_task,
    "get_project": get_project,
    "get_activity": get_activity,
    "search_past_updates": search_past_updates,
    "get_roadmap": get_roadmap,
    "get_norms": get_norms,
    "propose_stories": propose_stories,
    "count_gmail_messages": count_gmail_messages,
    "count_job_search_emails": count_job_search_emails,
    "get_job_search_dashboard": get_job_search_dashboard,
    "format_job_search_dashboard": format_job_search_dashboard,
}