"""Load testing configuration for Project Zeno chat endpoint."""

import os


class LoadTestConfig:
    """Configuration for load testing scenarios."""

    # API Configuration
    BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
    API_ENDPOINT = "/api/chat"

    # Authentication - Machine user API key
    # Format: zeno-key_<prefix>_<secret>
    MACHINE_USER_TOKEN = os.getenv(
        "ZENO_MACHINE_USER_TOKEN",
    )

    # Load Testing Parameters
    SPAWN_RATE = 1  # Users spawned per second
    RUN_TIME = "5m"  # Test duration

    # Request Timeouts
    REQUEST_TIMEOUT = 600  # seconds (increased for streaming responses)
    STREAMING_TIMEOUT = 600  # seconds for streaming responses
    CONNECT_TIMEOUT = 10  # seconds for initial connection
    READ_TIMEOUT = 600  # seconds for reading response data

    # Connection Pool Configuration
    MAX_POOL_SIZE = 50  # Maximum connections per pool
    MAX_POOL_CONNECTIONS = 200  # Total connections across all pools
    POOL_BLOCK = False  # Don't block when pool is full

    # User Behavior Weights
    QUICK_QUERY_WEIGHT = 30  # % of users doing quick queries
    ANALYSIS_QUERY_WEIGHT = 50  # % of users doing analysis queries
    CONVERSATION_WEIGHT = 20  # % of users doing multi-turn conversations

    # Wait Times (seconds)
    MIN_WAIT = 5
    MAX_WAIT = 15
    THINK_TIME = (2, 8)  # Between messages in conversation

    @classmethod
    def get_auth_header(cls) -> dict:
        """Get authorization header for machine user."""
        return {"Authorization": f"Bearer {cls.MACHINE_USER_TOKEN}"}

    @classmethod
    def validate_config(cls) -> None:
        """Validate configuration before running tests."""
        if not cls.MACHINE_USER_TOKEN:
            raise ValueError(
                "ZENO_MACHINE_USER_TOKEN environment variable must be set"
            )

        if not cls.MACHINE_USER_TOKEN.startswith("zeno-key:"):
            raise ValueError("Machine user token must start with 'zeno-key:'")

        parts = cls.MACHINE_USER_TOKEN.split(":")
        if len(parts) != 3:
            raise ValueError(
                "Machine user token format invalid (should be zeno-key:<prefix>:<secret>)"
            )


# Scenario-specific configurations
class ScenarioConfig:
    """Configuration for different load testing scenarios."""

    # Smoke Test - Basic functionality
    SMOKE = {
        "users": 1,
        "spawn_rate": 1,
        "run_time": "2m",
        "description": "Basic functionality validation with 1 user",
    }

    # Load Test - Normal usage
    LOAD = {
        "users": 10,
        "spawn_rate": 2,
        "run_time": "5m",
        "description": "Normal usage simulation with 10 concurrent users",
    }

    # Stress Test - High load
    STRESS = {
        "users": 50,
        "spawn_rate": 5,
        "run_time": "10m",
        "description": "High load testing with 50 concurrent users",
    }

    # Spike Test - Traffic bursts
    SPIKE = {
        "users": 50,
        "spawn_rate": 10,
        "run_time": "3m",
        "description": "Sudden traffic spike with 50 users",
    }
