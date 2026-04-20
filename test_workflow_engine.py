from __future__ import annotations

from app.core.workflow_engine import WorkflowEngine


def test_workflow_engine_create_and_list(tmp_path) -> None:
    engine = WorkflowEngine(str(tmp_path))
    wf = engine.create_workflow(
        name="Daily summary",
        description="Send a daily summary",
        steps=[{"step_id": "s1", "title": "Collect", "action": "collect"}],
        standing_order="Always summarize inbox first.",
    )
    assert wf.workflow_id
    workflows = engine.list_workflows()
    assert len(workflows) == 1


def test_workflow_engine_start_run(tmp_path) -> None:
    engine = WorkflowEngine(str(tmp_path))
    wf = engine.create_workflow(
        name="Daily summary",
        description="Send a daily summary",
        steps=[{"step_id": "s1", "title": "Collect", "action": "collect"}],
    )
    run = engine.start_run(wf.workflow_id, context={"user_id": "u1"})
    assert run.workflow_id == wf.workflow_id
    runs = engine.list_runs(wf.workflow_id)
    assert len(runs) == 1
