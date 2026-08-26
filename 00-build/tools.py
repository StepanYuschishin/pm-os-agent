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
import base64
import time
from openai import OpenAI, APIConnectionError, APITimeoutError, RateLimitError
from email.message import EmailMessage
from pathlib import Path
from datetime import datetime, timedelta, timezone
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from dotenv import load_dotenv
from email.utils import parsedate_to_datetime
load_dotenv(Path(__file__).parent / ".env")

FIXTURES = Path(__file__).parent / "fixtures"

# Commitment bound (M5). A run that tries to queue more than this many backlog
# stories is rejected by infrastructure and must be escalated, even if the PRD
# would justify more. Auto-committing a flood of "real" work is the money analog.
MAX_QUEUE_ITEMS = int(os.environ.get("CORTEX_MAX_QUEUE_ITEMS", "10"))

GMAIL_SCOPE = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]
CREDENTIALS_FILE = Path(__file__).parent / "credentials.json"
OPENAI_MODEL = os.environ.get("CORTEX_CLASSIFIER_MODEL", "gpt-4.1-mini")
TOKEN_FILE = Path(__file__).parent / "token.json"
REJECTION_REPLIES_FILE = Path(__file__).parent / "rejection-replies.json"
JOB_SEARCH_CACHE_FILE = Path(__file__).parent / "job-search-classifications.json"

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

def _execute_gmail_request(
    request,
    attempts: int = 3,
    delay_seconds: int = 5,
):
    """Execute a Gmail API request with retries for temporary network timeouts."""
    last_error = None

    for attempt in range(1, attempts + 1):
        try:
            return request.execute()
        except TimeoutError as error:
            last_error = error

            if attempt == attempts:
                raise

            time.sleep(delay_seconds)

    raise last_error

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
        response = _execute_gmail_request(
            service.users()
            .messages()
            .list(
                userId="me",
                q=gmail_query,
                pageToken=page_token,
                maxResults=500,
            )
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
     # Direct rejection
    "unfortunately",
    "we regret to inform you",
    "we regret",
    "regrettably",
    "regretfully",
    "we are sorry to inform you",
    "we're sorry to inform you",
    "we are sorry to let you know",
    "we're sorry to let you know",

    # Not moving forward
    "we will not be moving forward",
    "we won't be moving forward",
    "we are not moving forward",
    "we're not moving forward",
    "not moving forward with your application",
    "not moving forward with your candidacy",
    "unable to move forward with your application",
    "unable to proceed with your application",
    "not to proceed with your application",
    "not to proceed with your candidacy",
    "will not proceed with your application",
    "will not proceed further",
    "will not progress your application",
    "will not progress further",

    # Candidate not selected
    "your application was not selected",
    "your application has not been selected",
    "you were not selected",
    "you have not been selected",
    "not selected for this position",
    "not selected for this role",
    "not selected to move forward",
    "not selected for the next stage",
    "not selected for further consideration",
    "not shortlisted",
    "you have not been shortlisted",
    "we have not shortlisted your application",

    # Other candidate chosen
    "we decided to move forward with other candidates",
    "we have decided to move forward with other candidates",
    "we've decided to move forward with other candidates",
    "we decided to pursue other candidates",
    "we have chosen to pursue other candidates",
    "we have chosen to move forward with another candidate",
    "we decided to move forward with another candidate",
    "another candidate has been selected",
    "another candidate was selected",
    "we selected another candidate",
    "we have selected another candidate",
    "the role has been offered to another candidate",
    "we have filled the role with another candidate",

    # Stronger match / fit language
    "other applicants whose experience more closely matches",
    "other candidates whose experience more closely matches",
    "other candidates whose qualifications more closely match",
    "candidates whose experience more closely aligns",
    "candidates whose background more closely aligns",
    "we have identified candidates with a closer match",
    "we are proceeding with candidates who more closely match",
    "we are moving ahead with candidates who more closely match",
    "your experience does not match our current requirements",
    "your background does not match our current requirements",
    "not the right fit",
    "not a suitable fit",
    "not the best fit",
    "not a match for this role",
    "not the right match for this position",

    # Position closed / filled / cancelled
    "position has been filled",
    "the position has been filled",
    "role has been filled",
    "the role has been filled",
    "vacancy has been filled",
    "this vacancy has been filled",
    "position is no longer available",
    "role is no longer available",
    "vacancy is no longer available",
    "position has been closed",
    "role has been closed",
    "vacancy has been closed",
    "position has been cancelled",
    "role has been cancelled",
    "vacancy has been cancelled",
    "we are no longer hiring for this position",
    "we are no longer hiring for this role",

    # Process ended
    "your application is no longer under consideration",
    "your candidacy is no longer under consideration",
    "we will not be progressing your application",
    "we will not be progressing your candidacy",
    "we are unable to progress your application",
    "we are unable to progress your candidacy",
    "we are unable to offer you the position",
    "we are unable to offer you the role",
    "we will not be offering you the position",
    "we will not be offering you the role",

    # ATS-style wording
    "application unsuccessful",
    "your application was unsuccessful",
    "your application has been unsuccessful",
    "candidacy unsuccessful",
    "unsuccessful on this occasion",
    "we will not be taking your application further",
    "we will not be taking your candidacy further",
    "we will not be progressing to the next stage",
    "we will not invite you to the next stage",
    "we are unable to invite you to the next stage",

    # Soft rejection wording
    "we appreciate your interest, however",
    "thank you for your interest, however",
    "thank you for applying, however",
    "after careful consideration",
    "after reviewing your application",
    "following careful consideration",
    "following review of your application",
]

APPLICATION_SUBMITTED_PHRASES = [
    # Direct confirmation
    "your application was submitted successfully",
    "your application has been submitted",
    "your application was submitted",
    "application submitted successfully",
    "application has been submitted",
    "application submitted",

    # Received
    "we have received your application",
    "we've received your application",
    "we received your application",
    "your application has been received",
    "your application was received",
    "application received",
    "application successfully received",

    # Thank-you confirmations
    "thank you for submitting your application",
    "thank you for your application",
    "thank you for applying",
    "thanks for applying",
    "thanks for your application",
    "thank you for applying to",
    "thanks for applying to",

    # Under review
    "your application is under review",
    "your application is now under review",
    "we are reviewing your application",
    "we're reviewing your application",
    "your application will be reviewed",
    "your application is being reviewed",
    "your application has been forwarded for review",
    "your application has been sent for review",
    "your application has been passed to the hiring team",
    "your application has been forwarded to the hiring team",

    # Recruiting system acknowledgement
    "your application has been successfully received",
    "your application has been successfully submitted",
    "we have successfully received your application",
    "we have successfully received your submission",
    "your submission has been received",
    "your submission was successful",
    "submission successful",
    "application confirmation",
    "application acknowledgement",
    "application acknowledgment",

    # Candidate profile / ATS
    "your candidate profile has been created",
    "your candidate profile has been received",
    "your profile has been submitted",
    "your profile has been received",
    "your application is now in our system",
    "your application has been added to our system",
    "your application is now in our recruitment system",
    "your application has been added to our recruitment system",

    # Role-specific confirmations
    "we received your application for",
    "we have received your application for",
    "thank you for applying for",
    "thank you for applying to the",
    "thanks for applying for",
    "your application for the position of",
    "your application for the role of",
    "your application for this position",
    "your application for this role",

    # Next-step-neutral confirmation
    "we will review your application",
    "our recruitment team will review your application",
    "our hiring team will review your application",
    "we will be in touch regarding your application",
    "we will contact you if your profile matches",
    "we will contact you regarding next steps",
]

def _get_gmail_message_summary(
    service,
    message_id: str,
) -> dict:
    """Read Gmail metadata and full text body for classification."""
    message = _execute_gmail_request(
        service.users()
        .messages()
        .get(
            userId="me",
            id=message_id,
            format="full",
        )
    )

    headers = {
        header["name"].lower(): header["value"]
        for header in message.get("payload", {}).get("headers", [])
    }

    def extract_text(payload: dict) -> str:
        """Extract readable text from plain-text or HTML Gmail MIME payloads."""
        mime_type = payload.get("mimeType", "")
        body_data = payload.get("body", {}).get("data")

        if body_data:
            try:
                decoded = base64.urlsafe_b64decode(
                    body_data.encode("utf-8")
                ).decode("utf-8", errors="replace")
            except Exception:
                decoded = ""

            if mime_type == "text/plain":
                return decoded

            if mime_type == "text/html":
                import re
                import html

                text = re.sub(
                    r"<script.*?</script>",
                    " ",
                    decoded,
                    flags=re.S | re.I,
                )
                text = re.sub(
                    r"<style.*?</style>",
                    " ",
                    text,
                    flags=re.S | re.I,
                )
                text = re.sub(r"<[^>]+>", " ", text)
                text = html.unescape(text)
                text = re.sub(r"\s+", " ", text)

                return text.strip()

        text_parts = []

        for part in payload.get("parts", []):
            part_text = extract_text(part)

            if part_text:
                text_parts.append(part_text)

        return "\n".join(text_parts)

    body = extract_text(
        message.get("payload", {})
    ).strip()

    return {
        "id": message_id,
        "thread_id": message.get("threadId", ""),
        "message_header_id": headers.get("message-id", ""),
        "subject": headers.get("subject", ""),
        "from": headers.get("from", ""),
        "reply_to": headers.get("reply-to", ""),
        "date": headers.get("date", ""),
        "snippet": message.get("snippet", ""),
        "body": body,
    }

def _load_rejection_replies() -> dict:
    """Load record of rejection emails Cortex has already replied to."""
    if not REJECTION_REPLIES_FILE.exists():
        return {}

    try:
        return json.loads(REJECTION_REPLIES_FILE.read_text())
    except json.JSONDecodeError:
        return {}


def _save_rejection_replies(replies: dict) -> None:
    """Persist sent rejection-reply records."""
    REJECTION_REPLIES_FILE.write_text(
        json.dumps(replies, indent=2)
    )

def get_replyable_rejections(
    start_date: str = "2026-06-22",
) -> dict:
    """Find AI-classified rejection emails that are safe to reply to."""
    abu_dhabi_timezone = timezone(timedelta(hours=4))

    try:
        start_datetime = datetime.strptime(
            start_date,
            "%Y-%m-%d",
        ).replace(tzinfo=abu_dhabi_timezone)
    except ValueError:
        return {
            "error": "invalid_start_date",
            "expected_format": "YYYY-MM-DD",
        }

    now = datetime.now(abu_dhabi_timezone)
    service = _get_gmail_service()

    ai_result = _count_job_search_emails_ai_between(
        service,
        start_datetime,
        now,
    )

    already_replied = _load_rejection_replies()

    already_replied_thread_ids = {
        record.get("thread_id")
        for record in already_replied.values()
        if record.get("thread_id")
    }

    replyable = []
    skipped_no_reply = []
    skipped_already_replied = []

    blocked_sender_terms = [
        "no-reply",
        "noreply",
        "do-not-reply",
        "donotreply",
        "do_not_reply",
        "automated",
        "notification",
        "notifications",
        "system@",
        "support@",
        "mailer-daemon",
        "bounce",
        "successfactors",
        "myworkday",
        "do not reply",
        "workday@",
        "workday.hr@",
        "workflow.email.",
        "info@ing.com",
        "workday.hr",
    ]

    blocked_subject_terms = [
        "termination of employment",
        "collective request",
        "separation measures",
        "message replied:",
        "relocation",
        "visa",
        "offboarding",
        "employment termination",
    ]

    for message in ai_result["classified_messages"]:
        if message.get("label") != "REJECTION":
            continue

        message_id = message["id"]

        if message_id in already_replied:
            skipped_already_replied.append(message)
            continue

        message_thread_id = message.get("thread_id")

        if (
            message_thread_id
            and message_thread_id in already_replied_thread_ids
        ):
            skipped_already_replied.append(message)
            continue
        
        confidence = float(message.get("confidence") or 0)

        if confidence < 0.95:
            skipped_no_reply.append(message)
            continue

        reason = str(message.get("reason") or "").lower()

        rejection_reason_terms = [
            "will not proceed",
            "will not move forward",
            "not selected",
            "another candidate",
            "application was declined",
            "application declined",
            "application was unsuccessful",
            "application unsuccessful",
            "role was filled",
            "position was filled",
            "will not progress",
            "not progressing",
            "rejected",
            "rejection",
        ]

        if not any(term in reason for term in rejection_reason_terms):
            skipped_no_reply.append(message)
            continue

        message_id = message["id"]

        sender = message.get("from", "").lower()
        reply_to = message.get("reply_to", "").lower()
        subject = message.get("subject", "").lower()

        effective_reply_address = reply_to or sender

        if "stepan.yuschishin@gmail.com" in effective_reply_address:
            skipped_no_reply.append(message)
            continue

        if "stepan.yuschishin" in sender:
            skipped_no_reply.append(message)
            continue

        if any(term in subject for term in blocked_subject_terms):
            skipped_no_reply.append(message)
            continue
        
        if message_id in already_replied:
            skipped_already_replied.append(message)
            continue

        if any(term in effective_reply_address for term in blocked_sender_terms):
            skipped_no_reply.append(message)
            continue

        message["effective_reply_address"] = effective_reply_address
        replyable.append(message)

    return {
        "total_rejections": ai_result["rejections"],
        "replyable": replyable,
        "replyable_count": len(replyable),
        "skipped_no_reply_count": len(skipped_no_reply),
        "skipped_already_replied_count": len(skipped_already_replied),
        "skipped_no_reply": skipped_no_reply,
    }

def send_rejection_reply(
    message_id: str,
    body_text: str = (
        "Thanks for letting me know. I appreciate the update and your time. "
        "Please feel free to keep me in mind for any relevant opportunities "
        "in the future."
    ),
) -> dict:
    """Reply once to one rejection email inside the existing Gmail thread."""
    message_id = str(message_id or "").strip()

    if not message_id:
        return {"error": "message_id_required"}

    already_replied = _load_rejection_replies()

    if message_id in already_replied:
        return {
            "status": "skipped",
            "reason": "already_replied",
            "message_id": message_id,
        }

    service = _get_gmail_service()
    original = _get_gmail_message_summary(service, message_id)

    original_thread_id = original.get("thread_id", "")

    already_replied_thread_ids = {
        record.get("thread_id")
        for record in already_replied.values()
        if record.get("thread_id")
    }

    if (
        original_thread_id
        and original_thread_id in already_replied_thread_ids
    ):
        return {
            "status": "skipped",
            "reason": "thread_already_replied",
            "thread_id": original_thread_id,
            "message_id": message_id,
        }

    cache = _load_job_search_cache()
    classification = cache.get(message_id)

    if not classification:
        classification = _classify_job_email(original)
        cache[message_id] = classification
        _save_job_search_cache(cache)

    if classification.get("label") != "REJECTION":
        return {
            "status": "skipped",
            "reason": "not_classified_as_rejection",
            "message_id": message_id,
        }

    confidence = float(classification.get("confidence") or 0)

    if confidence < 0.95:
        return {
            "status": "skipped",
            "reason": "low_rejection_confidence",
            "confidence": confidence,
            "message_id": message_id,
        }

    sender = original.get("from", "")
    reply_to = original.get("reply_to", "")
    recipient = reply_to or sender


    subject_lower = original.get("subject", "").lower()
    sender_lower = sender.lower()

    blocked_subject_terms = [
        "termination of employment",
        "collective request",
        "separation measures",
        "message replied:",
        "relocation",
        "visa",
        "offboarding",
        "employment termination",
    ]

    if "stepan.yuschishin" in sender_lower:
        return {
            "status": "skipped",
            "reason": "self_sender",
            "message_id": message_id,
        }

    if any(term in subject_lower for term in blocked_subject_terms):
        return {
            "status": "skipped",
            "reason": "blocked_subject",
            "subject": original.get("subject", ""),
        }

    blocked_terms = [
        "no-reply",
        "noreply",
        "do-not-reply",
        "donotreply",
        "do_not_reply",
        "automated",
        "notification",
        "notifications",
        "system@",
        "support@",
        "mailer-daemon",
        "bounce",
    ]

    recipient_lower = recipient.lower()

    if any(term in recipient_lower for term in blocked_terms):
        return {
            "status": "skipped",
            "reason": "blocked_recipient",
            "recipient": recipient,
        }

    original_subject = original.get("subject", "").strip()

    if original_subject.lower().startswith("re:"):
        reply_subject = original_subject
    else:
        reply_subject = f"Re: {original_subject}"

    reply = EmailMessage()
    reply["To"] = recipient
    reply["From"] = "me"
    reply["Subject"] = reply_subject

    original_message_header_id = original.get("message_header_id", "")

    if original_message_header_id:
        reply["In-Reply-To"] = original_message_header_id
        reply["References"] = original_message_header_id

    reply.set_content(body_text)

    encoded_message = base64.urlsafe_b64encode(
        reply.as_bytes()
    ).decode("utf-8")

    sent = _execute_gmail_request(
        service.users()
        .messages()
        .send(
            userId="me",
            body={
                "raw": encoded_message,
                "threadId": original.get("thread_id"),
            },
        )
    )

    already_replied[message_id] = {
        "sent_message_id": sent.get("id"),
        "thread_id": sent.get("threadId"),
        "recipient": recipient,
        "subject": reply_subject,
        "sent_at": datetime.now(
            timezone(timedelta(hours=4))
        ).isoformat(),
    }

    _save_rejection_replies(already_replied)

    return {
        "status": "sent",
        "original_message_id": message_id,
        "sent_message_id": sent.get("id"),
        "thread_id": sent.get("threadId"),
        "recipient": recipient,
        "subject": reply_subject,
    }

def send_all_replyable_rejections(
    start_date: str = "2026-06-22",
    max_batch: int = 20,
) -> dict:
    """Send one polite reply to each currently replyable rejection."""
    discovery = get_replyable_rejections(start_date)

    if "error" in discovery:
        return discovery

    replyable = discovery["replyable"][:max_batch]
    results = []

    for message in replyable:
        result = send_rejection_reply(message["id"])

        results.append({
            "original_message_id": message["id"],
            "recipient": message.get("effective_reply_address"),
            "subject": message.get("subject"),
            "result": result,
        })

    sent_count = sum(
        1
        for item in results
        if item["result"].get("status") == "sent"
    )

    skipped_count = sum(
        1
        for item in results
        if item["result"].get("status") == "skipped"
    )

    return {
        "status": "completed",
        "discovered_replyable": discovery["replyable_count"],
        "attempted": len(replyable),
        "sent": sent_count,
        "skipped": skipped_count,
        "max_batch": max_batch,
        "results": results,
    }

def _load_job_search_cache() -> dict:
    """Load cached job-email classifications."""
    if not JOB_SEARCH_CACHE_FILE.exists():
        return {}

    try:
        return json.loads(JOB_SEARCH_CACHE_FILE.read_text())
    except json.JSONDecodeError:
        return {}


def _save_job_search_cache(cache: dict) -> None:
    """Persist job-email classifications."""
    JOB_SEARCH_CACHE_FILE.write_text(
        json.dumps(cache, indent=2)
    )


def _classify_job_email(email_data: dict) -> dict:
    """Classify one job-search email using an LLM."""
    client = OpenAI(
        timeout=30.0,
        max_retries=0,
    )

    prompt = f"""
Classify this email into exactly one category.

Categories:
APPLICATION_CONFIRMATION
REJECTION
INTERVIEW
RECRUITER_REPLY
OTHER

Definitions:

APPLICATION_CONFIRMATION:
The email confirms or clearly acknowledges that a job application
was submitted, received, accepted into the recruiting system, or is now under review.

This includes semantic variants such as:
- "Thank you for applying"
- "Thanks for applying"
- "Thank you for your application"
- "We received your application"
- "Your application has been received"
- "Your application is under review"
- "We are reviewing your application"
- "Your application was submitted successfully"

REJECTION:
The email states that the candidate will not proceed, was not selected,
another candidate was chosen, the role was filled, the application
was unsuccessful, or the employer decided not to move forward.

INTERVIEW:
The email invites the candidate to an interview, assessment,
screening call, recruiter call, hiring manager call,
technical interview, or next hiring stage.

RECRUITER_REPLY:
The email is clearly about a specific job opportunity or application,
but does not itself confirm submission, rejection, or an interview/next stage.

OTHER:
Anything unrelated to the user's job search, including:
- generic job alerts
- newsletters
- account verification emails
- passwords or OTPs
- visa/admin messages
- surveys
- marketing emails

Important classification rules:
- Base the decision on meaning, not exact phrases.
- Prefer the most specific hiring-state category.
- If an email says "thank you for applying" and confirms receipt/review,
  classify as APPLICATION_CONFIRMATION.
- If an email says "thank you for applying" but then says the candidate
  will not move forward, classify as REJECTION.
- Do not classify newsletters or generic job alerts as applications.
- Do not classify account creation, password verification, OTP,
  survey, or visa/admin emails as job applications.
- Do not infer an application confirmation merely because the email is from a recruiter.

Email:

From: {email_data.get("from", "")}
Subject: {email_data.get("subject", "")}
Snippet: {email_data.get("snippet", "")}

Full email body:
{email_data.get("body", "")}

Return JSON only:

{{
  "label": "APPLICATION_CONFIRMATION|REJECTION|INTERVIEW|RECRUITER_REPLY|OTHER",
  "confidence": 0.0,
  "reason": "short explanation"
}}
"""

    last_error = None

    for attempt in range(1, 4):
        try:
            response = client.responses.create(
                model=OPENAI_MODEL,
                input=prompt,
            )
            break

        except (APIConnectionError, APITimeoutError, RateLimitError) as error:
            last_error = error

            if attempt == 3:
                raise

            time.sleep(5 * attempt)

    else:
        raise last_error

    text = response.output_text.strip()

    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        return {
            "label": "OTHER",
            "confidence": 0.0,
            "reason": "classifier_invalid_json",
        }

    return result



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
        response = _execute_gmail_request(
            service.users()
            .messages()
            .list(
                userId="me",
                q=gmail_query,
                pageToken=page_token,
                maxResults=500,
            )
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
        response = _execute_gmail_request(
            service.users()
            .messages()
            .list(
                userId="me",
                q=gmail_query,
                pageToken=page_token,
                maxResults=500,
            )
        )

        message_ids.update(
            message["id"]
            for message in response.get("messages", [])
        )

        page_token = response.get("nextPageToken")

        if not page_token:
            break

    return message_ids

def _count_job_search_emails_ai_between(
    service,
    start_datetime: datetime,
    end_datetime: datetime,
) -> dict:
    """Count job-search email categories using semantic classification."""
    candidate_ids = _get_job_email_candidates_between(
        service,
        start_datetime,
        end_datetime,
    )

    counts = {
        "applications_submitted": 0,
        "rejections": 0,
        "interviews": 0,
        "recruiter_replies": 0,
        "other": 0,
    }

    classified_messages = []

    cache = _load_job_search_cache()
    cache_changed = False

    

    for message_id in candidate_ids:
        cached_record = cache.get(message_id)

        if cached_record and cached_record.get("subject") is not None:
            email_data = {
                "id": message_id,
                "thread_id": cached_record.get("thread_id", ""),
                "date": cached_record.get("date", ""),
                "subject": cached_record.get("subject", ""),
                "from": cached_record.get("from", ""),
                "reply_to": cached_record.get("reply_to", ""),
                "snippet": cached_record.get("snippet", ""),
                "body": "",
            }

            classification = {
                "label": cached_record.get("label", "OTHER"),
                "confidence": cached_record.get("confidence"),
                "reason": cached_record.get("reason"),
            }

        else:
            email_data = _get_gmail_message_summary(
                service,
                message_id,
            )

            classification = _classify_job_email(email_data)

            cache[message_id] = {
                "label": classification.get("label", "OTHER"),
                "confidence": classification.get("confidence"),
                "reason": classification.get("reason"),
                "thread_id": email_data.get("thread_id", ""),
                "date": email_data.get("date", ""),
                "subject": email_data.get("subject", ""),
                "from": email_data.get("from", ""),
                "reply_to": email_data.get("reply_to", ""),
                "snippet": email_data.get("snippet", ""),
            }

            _save_job_search_cache(cache)
            cache_changed = True



        label = classification.get("label", "OTHER")

        if label == "APPLICATION_CONFIRMATION":
            counts["applications_submitted"] += 1

        elif label == "REJECTION":
            counts["rejections"] += 1

        elif label == "INTERVIEW":
            counts["interviews"] += 1

        elif label == "RECRUITER_REPLY":
            counts["recruiter_replies"] += 1

        else:
            counts["other"] += 1

        classified_messages.append(
            {
                "id": message_id,
                "thread_id": email_data.get("thread_id", ""),
                "date": email_data.get("date", ""),
                "subject": email_data["subject"],
                "from": email_data["from"],
                "reply_to": email_data.get("reply_to", ""),
                "label": label,
                "confidence": classification.get("confidence"),
                "reason": classification.get("reason"),
            }
        )

    if cache_changed:
        _save_job_search_cache(cache)

    return {
            **counts,
            "candidate_messages": len(candidate_ids),
            "classified_messages": classified_messages,
            "classification_method": "llm_semantic",
    }

def _get_job_email_candidates_between(
    service,
    start_datetime: datetime,
    end_datetime: datetime,
) -> set[str]:
    """Retrieve a broad candidate set of job-search emails."""
    start_timestamp = int(start_datetime.timestamp())
    end_timestamp = int(end_datetime.timestamp())

    candidate_queries = [
        f"after:{start_timestamp} before:{end_timestamp} application",
        f"after:{start_timestamp} before:{end_timestamp} candidate",
        f"after:{start_timestamp} before:{end_timestamp} recruiter",
        f"after:{start_timestamp} before:{end_timestamp} interview",
        f"after:{start_timestamp} before:{end_timestamp} hiring",
        f"after:{start_timestamp} before:{end_timestamp} position",
        f"after:{start_timestamp} before:{end_timestamp} role",
        f"after:{start_timestamp} before:{end_timestamp} unfortunately",
    ]

    message_ids: set[str] = set()

    for gmail_query in candidate_queries:
        page_token = None

        while True:
            response = _execute_gmail_request(
                service.users()
                .messages()
                .list(
                    userId="me",
                    q=gmail_query,
                    pageToken=page_token,
                    maxResults=500,
                )
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

def get_job_search_quality_report(
    start_date: str = "2026-06-22",
) -> dict:
    """Compare legacy phrase counting with semantic LLM classification."""
    abu_dhabi_timezone = timezone(timedelta(hours=4))

    try:
        start_datetime = datetime.strptime(
            start_date,
            "%Y-%m-%d",
        ).replace(tzinfo=abu_dhabi_timezone)
    except ValueError:
        return {
            "error": "invalid_start_date",
            "expected_format": "YYYY-MM-DD",
        }

    now = datetime.now(abu_dhabi_timezone)

    service = _get_gmail_service()

    legacy = count_job_search_emails(start_date)

    ai = _count_job_search_emails_ai_between(
        service,
        start_datetime,
        now,
    )

    return {
        "start_date": start_date,
        "legacy_phrase_based": {
            "applications_submitted": legacy["applications_submitted"],
            "rejections": legacy["rejections"],
        },
        "ai_semantic": {
            "applications_submitted": ai["applications_submitted"],
            "rejections": ai["rejections"],
            "interviews": ai["interviews"],
            "recruiter_replies": ai["recruiter_replies"],
        },
        "candidate_messages": ai["candidate_messages"],
        "classified_messages": ai["classified_messages"],
    }

def get_job_search_dashboard(
    start_date: str = "2026-06-22",
) -> dict:
    """Build dashboard from one Gmail/AI snapshot instead of rescanning Gmail."""

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
    today = now.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    yesterday = today - timedelta(days=1)
    seven_days_ago = today - timedelta(days=7)

    service = _get_gmail_service()

    # ONE full Gmail/AI pass only.
    snapshot = _count_job_search_emails_ai_between(
        service,
        baseline_date,
        now,
    )

    yesterday_counts = {
        "applications_submitted": 0,
        "rejections": 0,
        "interviews": 0,
        "recruiter_replies": 0,
        "other": 0,
    }

    last_7_days_counts = {
        "applications_submitted": 0,
        "rejections": 0,
        "interviews": 0,
        "recruiter_replies": 0,
        "other": 0,
    }

    label_to_key = {
        "APPLICATION_CONFIRMATION": "applications_submitted",
        "REJECTION": "rejections",
        "INTERVIEW": "interviews",
        "RECRUITER_REPLY": "recruiter_replies",
        "OTHER": "other",
    }

    for message in snapshot["classified_messages"]:
        raw_date = message.get("date", "")

        if not raw_date:
            continue

        try:
            message_datetime = parsedate_to_datetime(raw_date)

            if message_datetime.tzinfo is None:
                message_datetime = message_datetime.replace(
                    tzinfo=timezone.utc
                )

            message_datetime = message_datetime.astimezone(
                abu_dhabi_timezone
            )
        except (TypeError, ValueError, OverflowError):
            continue

        key = label_to_key.get(
            message.get("label", "OTHER"),
            "other",
        )

        if yesterday <= message_datetime < today:
            yesterday_counts[key] += 1

        if seven_days_ago <= message_datetime <= now:
            last_7_days_counts[key] += 1

    return {
        "dashboard": "Cortex Job Search Dashboard",
        "generated_at": now.isoformat(),
        "timezone": "Asia/Dubai",
        "since": start_date,

        "totals": {
            "applications_submitted":
                snapshot["applications_submitted"],
            "rejections":
                snapshot["rejections"],
        },

        "yesterday": {
            "date": yesterday.strftime("%Y-%m-%d"),
            **yesterday_counts,
        },

        "last_7_days": {
            "from": seven_days_ago.strftime("%Y-%m-%d"),
            "to": now.strftime("%Y-%m-%d"),
            **last_7_days_counts,
        },

        "access": "gmail_readonly_and_send",

        "note": (
            "Dashboard uses one Gmail snapshot and cached AI semantic "
            "classification; time-window metrics are calculated locally."
        ),
    }

def format_job_search_dashboard(
    start_date: str = "2026-06-22",
    automation_stats: dict | None = None,
) -> str:
    """Return the job-search dashboard as readable text."""
    dashboard = get_job_search_dashboard(start_date)

    if "error" in dashboard:
        return json.dumps(dashboard, indent=2)

    totals = dashboard["totals"]
    yesterday = dashboard["yesterday"]
    last_7_days = dashboard["last_7_days"]

    automation_stats = automation_stats or {}

    replyable_found = automation_stats.get(
        "discovered_replyable",
        0,
    )

    replies_sent = automation_stats.get(
        "sent",
        0,
    )

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

        "AUTOMATION\n"
        f"Replyable rejections found: {replyable_found}\n"
        f"Rejection replies sent this run: {replies_sent}\n\n"

        "System:\n"
        "Gmail access: Read + Send\n"
        "Classification: AI semantic + local cache\n"
        "Duplicate protection: message + thread level"
    )   

def email_job_search_dashboard(
    recipient: str,
    start_date: str = "2026-06-22",
    automation_stats: dict | None = None,
) -> dict:
    """Generate the dashboard and email it to the selected recipient."""
    recipient = str(recipient or "").strip()

    if not recipient or "@" not in recipient:
        return {"error": "valid_recipient_required"}

    dashboard_text = format_job_search_dashboard(
        start_date,
        automation_stats=automation_stats,
    )
    subject = "Cortex Job Search Dashboard"

    message = EmailMessage()
    message["To"] = recipient
    message["From"] = "me"
    message["Subject"] = subject
    message.set_content(dashboard_text)

    encoded_message = base64.urlsafe_b64encode(
        message.as_bytes()
    ).decode("utf-8")

    service = _get_gmail_service()

    sent_message = _execute_gmail_request(
        service.users()
        .messages()
        .send(
            userId="me",
            body={"raw": encoded_message},
        )
    )

    return {
        "status": "sent",
        "recipient": recipient,
        "subject": subject,
        "message_id": sent_message.get("id"),
        "access": "gmail_readonly_and_send",
    }

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
    "email_job_search_dashboard": email_job_search_dashboard,
    "get_job_search_quality_report": get_job_search_quality_report,
    "get_replyable_rejections": get_replyable_rejections,
    "send_rejection_reply": send_rejection_reply,
    "send_all_replyable_rejections": send_all_replyable_rejections,
}