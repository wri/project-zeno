from src.agent.middleware import format_session_block


def test_session_block_names_the_dataset_as_its_tools_do():
    block = format_session_block(
        {
            "dataset": {
                "dataset_name": "Tree cover loss",
                "analytics_dataset": "tree_cover_loss",
            }
        }
    )

    assert "Dataset: tree_cover_loss" in block


def test_session_block_names_the_dataset_by_its_title_otherwise():
    block = format_session_block(
        {"dataset": {"dataset_name": "Tree cover loss"}}
    )

    assert "Dataset: Tree cover loss" in block
