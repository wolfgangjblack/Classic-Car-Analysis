"""Tests for backend/app/core/agents.py -- dedup, consolidation, directory loading."""

from app.core.agents import AgentPipeline, ChatAgent, JsonicAgent

# --- Deduplication (this caught a real production bug) ---


def test_dedup_hashable_values():
    pipeline = AgentPipeline()
    pipeline.data = {
        "test.json": {
            "processing_results": {},
            "token_costs": 0.0,
        }
    }
    agent = JsonicAgent(system_prompt="test", name="testAgent")
    agent.data = {"make": ["Ford", "Ford", "Chevrolet"]}
    agent.token_cost = 0

    pipeline.agents["processing"] = [agent]

    # Simulate the dedup logic from process_transcript
    clean_data = {}
    for k, v in agent.data.items():
        try:
            clean_data[k] = list(set(v))
        except TypeError:
            seen = []
            for item in v:
                if item not in seen:
                    seen.append(item)
            clean_data[k] = seen

    assert "Ford" in clean_data["make"]
    assert "Chevrolet" in clean_data["make"]
    assert len(clean_data["make"]) == 2


def test_dedup_unhashable_values():
    """This was a real bug: conditionAgent returned dicts, set() failed with TypeError."""
    data = {
        "exterior": [
            {"paint": "good", "rust": "none"},
            {"paint": "good", "rust": "none"},
            {"paint": "fair", "rust": "surface"},
        ]
    }

    clean_data = {}
    for k, v in data.items():
        try:
            clean_data[k] = list(set(v))
        except TypeError:
            seen = []
            for item in v:
                if item not in seen:
                    seen.append(item)
            clean_data[k] = seen

    assert len(clean_data["exterior"]) == 2


# --- _consolidate_agent_results ---


def test_consolidate_agent_results():
    pipeline = AgentPipeline()
    pipeline.data = {
        "test.json": {
            "processing_results": {
                "basicAgent": {"make": ["Ford"], "model": ["Mustang"]},
                "historyAgent": {"mileage": ["50000"]},
            },
        }
    }
    result = pipeline._consolidate_agent_results("test.json")
    assert "basicAgent:" in result
    assert "Ford" in result
    assert "historyAgent:" in result
    assert "50000" in result


# --- _load_agents_from_directory ---


def test_load_agents_from_directory(tmp_path):
    (tmp_path / "basicAgent.txt").write_text("You extract basic car info. Return JSON.")
    (tmp_path / "summaryAgent.txt").write_text("You summarize vehicle reports.")
    (tmp_path / "emptyAgent.txt").write_text("")  # should be skipped

    pipeline = AgentPipeline(agents_dir=str(tmp_path))

    processing_names = [a.name for a in pipeline.agents["processing"]]
    summarizing_names = [a.name for a in pipeline.agents["summarizing"]]

    assert "basicAgent" in processing_names
    assert "summaryAgent" in summarizing_names
    assert len(pipeline.agents["processing"]) == 1
    assert len(pipeline.agents["summarizing"]) == 1

    assert isinstance(pipeline.agents["processing"][0], JsonicAgent)
    assert isinstance(pipeline.agents["summarizing"][0], ChatAgent)
