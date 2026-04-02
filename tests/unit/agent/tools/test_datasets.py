from pathlib import Path

import yaml


DATASETS_DIR = Path("src/agent/tools/datasets")


def test_tree_cover_loss_dataset_schema_includes_expected_context_layers_and_prompt_instructions():
    dataset_path = DATASETS_DIR / "tree_cover_loss.yml"

    with dataset_path.open(encoding="utf-8") as f:
        dataset = yaml.safe_load(f)

    assert dataset["dataset_name"] == "Tree cover loss"
    assert dataset["context_layers"] == [
        {
            "value": "primary_forest",
            "description": (
                "Shows loss within primary, intact, natural, or undisturbed forests."
            ),
        }
    ]

    prompt_instructions = dataset["prompt_instructions"]

    assert "Reports gross annual loss of tree cover" in prompt_instructions
    assert "always include the GHG emissions associated with that loss" in prompt_instructions
    assert "If users ask for intra-year or seasonal tree cover loss OR emissions, refuse" in prompt_instructions
    assert 'DO NOT use the term "deforestation", use "tree cover loss" instead' in prompt_instructions
    assert "Use 30% threshold." in prompt_instructions
    assert "If a user asks for net gain/loss, refuse" in prompt_instructions
    assert "DO NOT show emissions and loss in the same chart, use separate charts." in prompt_instructions
