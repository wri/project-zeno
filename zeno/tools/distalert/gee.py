import os
import ee
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

_ = load_dotenv()

def init_gee() -> None:
    """Initialize and authenticate gee"""

    service_account_info = {
        "type": "service_account",
        "project_id": os.environ.get("GEE_PROJECT_ID"),
        "private_key_id": os.environ.get("GEE_PRIVATE_KEY_ID"),
        "private_key": os.environ.get("GEE_PRIVATE_KEY"),
        "client_email": os.environ.get("GEE_CLIENT_EMAIL"),
        "client_id": os.environ.get("GEE_CLIENT_ID"),
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_x509_cert_url": os.environ.get("GEE_CLIENT_CERT_URL"),
        "universe_domain": "googleapis.com",
    }

    scopes = [
        "https://www.googleapis.com/auth/earthengine",
        "https://www.googleapis.com/auth/cloud-platform",
    ]

    credentials = Credentials.from_service_account_info(
        service_account_info, scopes=scopes)


    ee.Initialize(credentials)
