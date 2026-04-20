from app.core.task_ledger import TaskLedger
from app.core.audit import AuditEvent, get_action_logger, ActionContext

# Create audit trace
logger = get_action_logger()
logger.record(AuditEvent(
    kind="tool_call",
    action="twitter.post",
    context=ActionContext(user_id="u1", platform="web", request_text="Post a tweet", request_id="req_999"),
    detail="Posting daily tweet",
    success=True
))

# Create approval task
ledger = TaskLedger("workspace")
ledger.add_task(
    task_id="approval_mock_1",
    task_type="approval",
    title="Delete tmp directory",
    metadata={
        "target": "/tmp",
        "risk_level": "High",
        "reason": "User requested cleanup"
    }
)

print("Mock data generated in workspace.")
