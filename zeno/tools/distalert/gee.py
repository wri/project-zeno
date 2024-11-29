import os

import ee
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

_ = load_dotenv()


def init_gee() -> None:
    """Initialize and authenticate gee"""

    scopes = [
        "https://www.googleapis.com/auth/earthengine",
        "https://www.googleapis.com/auth/cloud-platform",
    ]

    credentials = Credentials.from_service_account_file(
        "ee-zeno-service-account.json", scopes=scopes
    )

    ee.Initialize(credentials)
