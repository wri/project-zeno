"""UserModel lifts the RW account's apps from the /auth/user/me payload.

RW nests them under ``extraUserData.apps``. The live shape is unconfirmed,
so anything unexpected must become None rather than an error.
"""

import pytest

from src.api.schemas import UserModel


def _rw_user(**extra):
    return {
        "id": "rw-1",
        "name": "RW One",
        "email": "rw-1@example.org",
        "createdAt": "2019-05-01T10:00:00Z",
        "updatedAt": "2024-01-01T00:00:00Z",
        **extra,
    }


@pytest.mark.parametrize(
    "apps, expected",
    [
        (["gfw"], ["gfw"]),
        (["gnw"], ["gnw"]),
        (["gfw", "rw", "gfw", "gnw"], ["gfw", "rw", "gnw"]),
        ([" gfw ", 3, None, "", "rw"], ["gfw", "rw"]),
    ],
)
def test_apps_are_lifted_as_unique_strings_in_order(apps, expected):
    user = UserModel.model_validate(_rw_user(extraUserData={"apps": apps}))

    assert user.rw_apps == expected


@pytest.mark.parametrize(
    "extra_user_data",
    [None, "gfw", ["gfw"], {}, {"apps": None}, {"apps": "gfw"}, {"apps": []}],
)
def test_unusable_apps_become_none(extra_user_data):
    user = UserModel.model_validate(_rw_user(extraUserData=extra_user_data))

    assert user.rw_apps is None


def test_payload_without_extra_user_data_has_no_apps():
    assert UserModel.model_validate(_rw_user()).rw_apps is None


def test_round_trip_through_model_dump_keeps_apps():
    # /api/auth/me re-validates the dumped model; there is no extraUserData
    # key then, so the lifted value must survive as is.
    user = UserModel.model_validate(_rw_user(extraUserData={"apps": ["gfw"]}))

    again = UserModel.model_validate(user.model_dump())

    assert again.rw_apps == ["gfw"]
