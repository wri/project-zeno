DATASETS_PLACEHOLDER = "{{AVAILABLE_DATASETS}}"


def load_datasets_info() -> str:
    """Build a bullet list of datasets from configuration, skipping any the
    current agent profile (feature flag) excludes."""
    from src.agent.datasets.config import DATASETS
    from src.agent.tool_spec import bound_availability

    excluded = bound_availability().excluded_datasets
    datasets_info = []
    for dataset in DATASETS:
        name = dataset.get("dataset_name", "Unknown")
        if name in excluded:
            continue
        content_date = dataset.get("content_date", "Unknown")
        resolution = dataset.get("resolution", "Unknown")
        update_frequency = dataset.get("update_frequency", "Unknown")
        description = dataset.get("description", "Unknown")

        description_parts = []
        if content_date != "Unknown":
            description_parts.append(f"from {content_date}")
        if resolution != "Unknown":
            description_parts.append(f"{resolution} resolution")
        if update_frequency != "Unknown":
            description_parts.append(f"{update_frequency} updates")
        if description != "Unknown":
            description_parts.append(f"{description}")

        context_layers = dataset.get("context_layers")
        if context_layers:
            context_desc = ", ".join(
                layer.get("description", "") for layer in context_layers
            )
            if context_desc:
                description_parts.append(f"with {context_desc.lower()}")

        line = (
            ", ".join(description_parts)
            if description_parts
            else "detailed environmental data"
        )
        datasets_info.append(f"- {name}: {line.capitalize()}")

    return "\n".join(datasets_info)


def render_capabilities_body(template: str) -> str:
    """Inject live dataset list into the capabilities skill template."""
    return template.replace(DATASETS_PLACEHOLDER, load_datasets_info())
