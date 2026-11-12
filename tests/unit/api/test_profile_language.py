"""The profile accepts every UI locale the frontend ships (PZB-1015).

The frontend's locales are the same codes as ``preferred_language_code``:
en, es, fr, pt, id and zh (Simplified Chinese).
"""

import pytest
from pydantic import ValidationError

from src.api.schemas import UserProfileUpdateRequest

UI_LOCALES = ["en", "es", "fr", "pt", "id", "zh"]


@pytest.mark.parametrize("code", UI_LOCALES)
def test_profile_update_accepts_each_ui_locale(code):
    request = UserProfileUpdateRequest(preferred_language_code=code)

    assert request.preferred_language_code == code


@pytest.mark.parametrize("code", ["xx", "zh-TW", "zh-Hans"])
def test_profile_update_rejects_other_language_codes(code):
    with pytest.raises(ValidationError, match="Invalid language code"):
        UserProfileUpdateRequest(preferred_language_code=code)
