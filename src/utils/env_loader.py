"""
Shared utility for loading environment variables across the application.
"""

import os

from dotenv import load_dotenv


def load_environment_variables():
    """
    Load environment variables with proper precedence:
    1. Load base environment from .env
    2. Override with .env.local if it exists (for local development)

    Returns:
        str: A message indicating which configuration was loaded
    """
    # Load base environment from .env
    load_dotenv()

    # Check for local development overrides
    if os.path.exists(".env.local"):
        load_dotenv(".env.local", override=True)
        message = (
            "🔧 Loaded .env + .env.local (development mode with overrides)"
        )
    else:
        message = "🚀 Loaded .env only (production mode)"

    print(message)
    return message
