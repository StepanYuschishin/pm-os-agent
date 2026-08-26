import signal
import sys

from tools import (
    email_job_search_dashboard,
    send_all_replyable_rejections,
)

DASHBOARD_RECIPIENT = "stepan.yuschishin@gmail.com"
JOB_SEARCH_START_DATE = "2026-06-22"
MAX_RUN_SECONDS = 600  # 10 minutes


class CortexRunTimeout(Exception):
    pass


def _handle_timeout(signum, frame):
    raise CortexRunTimeout(
        f"Cortex job-search run exceeded {MAX_RUN_SECONDS} seconds"
    )


signal.signal(signal.SIGALRM, _handle_timeout)
signal.alarm(MAX_RUN_SECONDS)

try:
    print("=== CORTEX JOB SEARCH RUN ===")

    reply_result = send_all_replyable_rejections(
        start_date=JOB_SEARCH_START_DATE,
        max_batch=20,
    )

    print("REJECTION REPLIES:")
    print({
        "status": reply_result.get("status"),
        "discovered_replyable": reply_result.get("discovered_replyable"),
        "attempted": reply_result.get("attempted"),
        "sent": reply_result.get("sent"),
        "skipped": reply_result.get("skipped"),
    })

    dashboard_result = email_job_search_dashboard(
        recipient=DASHBOARD_RECIPIENT,
        start_date=JOB_SEARCH_START_DATE,
        automation_stats=reply_result,
    )

    print("DASHBOARD:")
    print(dashboard_result)

except CortexRunTimeout as error:
    print(f"ERROR: {error}", file=sys.stderr)
    sys.exit(124)

finally:
    signal.alarm(0)