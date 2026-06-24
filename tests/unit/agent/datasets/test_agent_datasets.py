from src.agent.datasets.config import DATASETS, agent_datasets


def test_agent_datasets_hides_dist_but_keeps_it_loaded():
    names = {d["dataset_name"] for d in agent_datasets()}
    all_names = {d["dataset_name"] for d in DATASETS}

    dist = "Global all ecosystem disturbance alerts (DIST-ALERT)"
    # DIST is still loaded (handlers/metadata need it) ...
    assert dist in all_names
    # ... but hidden from the agent via agent_enabled: false.
    assert dist not in names
    # Integrated Alerts replaces it in the agent-facing set.
    assert "Integrated Alerts" in names
