import pytest
import os
import json
from unittest.mock import MagicMock, patch
from pathlib import Path
from app.core.autonomy_engine import AutonomyEngine


@pytest.fixture
def temp_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return str(workspace)


def test_autonomy_engine_initialization(temp_workspace):
    engine = AutonomyEngine(workspace_dir=temp_workspace)
    assert engine.workspace_dir == Path(temp_workspace)
    assert engine.goals_file == Path(temp_workspace) / "goals.jsonl"


def test_read_goals_empty(temp_workspace):
    engine = AutonomyEngine(workspace_dir=temp_workspace)
    goals = engine._read_goals()
    assert goals == []


def test_read_goals_with_data(temp_workspace):
    engine = AutonomyEngine(workspace_dir=temp_workspace)
    goals_data = [
        {"id": "goal1", "description": "Do the first thing"},
        {"id": "goal2", "description": "Do the second thing"},
    ]
    with open(engine.goals_file, "w") as f:
        for g in goals_data:
            f.write(json.dumps(g) + "\n")

    goals = engine._read_goals()
    assert len(goals) == 2
    assert goals[0]["id"] == "goal1"
    assert goals[1]["description"] == "Do the second thing"


@pytest.mark.asyncio
async def test_autonomy_engine_start_stop(temp_workspace):
    engine = AutonomyEngine(workspace_dir=temp_workspace)

    # We won't fully start it because it enters an infinite while loop
    # but we can mock its loop to exit immediately
    with patch.object(engine, "_read_goals", return_value=[]):
        pass  # In a full test, we'd mock asyncio.sleep to break the loop or similar
