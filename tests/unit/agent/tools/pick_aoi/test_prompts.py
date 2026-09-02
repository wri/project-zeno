from src.agent.subagents.pick_aoi.prompts import GEOCODER_PROMPT
from src.agent.subagents.pick_aoi.types import AreaOfInterestType


def test_every_area_type_is_offered_to_the_model_verbatim():
    """The prompt lists the enum, so the two cannot drift apart.

    `area_type` is parsed back into AreaOfInterestType, so a value the prompt
    spells differently from the enum (the "adminstrative" typo included) is a
    value the model can never return.
    """
    for area_type in AreaOfInterestType:
        assert f'"{area_type.value}"' in GEOCODER_PROMPT
