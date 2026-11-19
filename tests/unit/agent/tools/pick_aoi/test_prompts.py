from src.agent.subagents.pick_aoi.prompts import GEOCODER_PROMPT
from src.agent.subagents.pick_aoi.types import AreaOfInterestType


def test_every_area_type_is_offered_to_the_model_verbatim():
    """The prompt lists the enum, so the two cannot drift apart.

    `area_type` is parsed back into AreaOfInterestType, so a value the prompt
    spells differently from the enum is a
    value the model can never return.
    """
    for area_type in AreaOfInterestType:
        assert f'"{area_type.value}"' in GEOCODER_PROMPT


def test_the_tool_description_asks_for_the_full_request():
    """The geocoder decides between one area and its subregions from the
    words around the place. With "Pass the user's words about the place",
    the orchestrator sent "Democratic Republic of the Congo" for "Which
    province of the DRC…" and got the country (a GOLD regression after
    #911). The description must ask for the whole request."""
    from src.agent.prompts.tool_descriptions import TOOL_DESCRIPTIONS

    description = TOOL_DESCRIPTIONS["pick_aoi"]
    assert "full request" in description
    assert "not only the place name" in description
