"""
Load testing for Project Zeno chat endpoint using Locust.

This script simulates realistic user behavior patterns:
- Quick queries (30%): Simple geographic questions
- Analysis queries (50%): Complex data analysis requests
- Conversations (20%): Multi-turn conversations with thread_id

Usage:
    # Smoke test (1 user)
    locust -f locustfile.py --users 1 --spawn-rate 1 -t 2m

    # Load test (10 users)
    locust -f locustfile.py --users 10 --spawn-rate 2 -t 5m

    # Stress test (50 users)
    locust -f locustfile.py --users 50 --spawn-rate 5 -t 10m

    # With web UI
    locust -f locustfile.py --host http://localhost:8000
"""

import json
import logging
import random
from typing import Dict, Optional

from config import LoadTestConfig, ScenarioConfig
from locust import HttpUser, between, events, task
from test_data import TestDataGenerator

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ZenoChatUser(HttpUser):
    """Simulates a user interacting with the Zeno chat endpoint."""

    wait_time = between(LoadTestConfig.MIN_WAIT, LoadTestConfig.MAX_WAIT)
    weight = 1

    def on_start(self):
        """Initialize user session."""
        LoadTestConfig.validate_config()
        self.data_generator = TestDataGenerator()
        self.thread_id = None  # For conversation continuity
        self.conversation_turns = 0
        self.max_conversation_turns = random.randint(3, 6)

        logger.info(f"User {self.environment.runner.user_count} started")

    def make_chat_request(
        self, payload: Dict, request_name: str = "chat"
    ) -> Optional[Dict]:
        """Make a chat request and handle streaming response."""
        headers = {
            **LoadTestConfig.get_auth_header(),
            "Content-Type": "application/json",
            "Accept": "application/x-ndjson",
        }

        try:
            with self.client.post(
                LoadTestConfig.API_ENDPOINT,
                json=payload,
                headers=headers,
                timeout=LoadTestConfig.REQUEST_TIMEOUT,
                stream=True,
                name=request_name,
                catch_response=True,
            ) as response:
                if response.status_code != 200:
                    response.failure(
                        f"HTTP {response.status_code}: {response.text}"
                    )
                    return None

                # Process streaming response
                response_data = []
                bytes_received = 0

                try:
                    for line in response.iter_lines():
                        if line:
                            # Decode bytes to string if needed
                            if isinstance(line, bytes):
                                line = line.decode("utf-8")

                            line = line.strip()
                            if line:
                                bytes_received += len(line)
                                try:
                                    data = json.loads(line)
                                    response_data.append(data)

                                    # Extract thread_id from response for conversation continuity
                                    if "thread_id" in data:
                                        self.thread_id = data["thread_id"]

                                except json.JSONDecodeError as e:
                                    logger.debug(
                                        f"JSON decode error: {e}, line: {line[:100]}"
                                    )
                                    continue

                    # Mark as success if we received data
                    if response_data:
                        response.success()
                        self._record_custom_metrics(
                            response, bytes_received, len(response_data)
                        )
                        return response_data[-1] if response_data else None
                    else:
                        response.failure(
                            "No data received in streaming response"
                        )
                        return None

                except Exception as e:
                    response.failure(f"Error processing stream: {str(e)}")
                    return None

        except Exception as e:
            logger.error(f"Request failed: {str(e)}")
            return None

    def _record_custom_metrics(
        self, response, bytes_received: int, chunks_received: int
    ):
        """Record custom metrics for streaming responses."""
        # Record quota usage from headers
        if "X-Prompts-Used" in response.headers:
            try:
                prompts_used = int(response.headers["X-Prompts-Used"])
                prompts_quota = int(response.headers.get("X-Prompts-Quota", 0))

                # Log quota usage every 10 requests
                if random.random() < 0.1:
                    logger.info(f"Quota usage: {prompts_used}/{prompts_quota}")

            except ValueError:
                pass

        # Could add more custom metrics here (bytes received, chunks, etc.)

    @task(LoadTestConfig.QUICK_QUERY_WEIGHT)
    def quick_query(self):
        """Execute a quick geographic query."""
        payload = self.data_generator.get_quick_query()

        result = self.make_chat_request(payload, "quick_query")
        if result:
            logger.debug(f"Quick query completed: {payload['query'][:50]}...")

    @task(LoadTestConfig.ANALYSIS_QUERY_WEIGHT)
    def analysis_query(self):
        """Execute a complex analysis query."""
        payload = self.data_generator.get_analysis_query()

        result = self.make_chat_request(payload, "analysis_query")
        if result:
            logger.debug(
                f"Analysis query completed: {payload['query'][:50]}..."
            )

    @task(LoadTestConfig.CONVERSATION_WEIGHT)
    def conversation_flow(self):
        """Execute multi-turn conversation."""
        if (
            not self.thread_id
            or self.conversation_turns >= self.max_conversation_turns
        ):
            # Start new conversation
            payload = self.data_generator.get_conversation_starter()
            self.conversation_turns = 0
            request_name = "conversation_start"
        else:
            # Continue existing conversation
            payload = self.data_generator.get_follow_up(self.thread_id)
            request_name = "conversation_followup"

        result = self.make_chat_request(payload, request_name)
        if result:
            self.conversation_turns += 1
            logger.debug(
                f"Conversation turn {self.conversation_turns}: {payload['query'][:30]}..."
            )

            # Wait between conversation turns (just sleep directly)
            think_time = random.uniform(*LoadTestConfig.THINK_TIME)
            import time

            time.sleep(think_time)


# Event handlers for custom reporting
@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Log test start information."""
    logger.info("=== Zeno Chat Load Test Starting ===")
    logger.info(f"Target host: {LoadTestConfig.BASE_URL}")
    logger.info(f"Endpoint: {LoadTestConfig.API_ENDPOINT}")
    logger.info("Using machine user authentication")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Log test completion information."""
    logger.info("=== Zeno Chat Load Test Completed ===")

    stats = environment.stats.total
    logger.info(f"Total requests: {stats.num_requests}")
    logger.info(f"Failures: {stats.num_failures}")
    logger.info(f"Average response time: {stats.avg_response_time:.2f}ms")
    logger.info(
        f"95th percentile: {stats.get_response_time_percentile(0.95):.2f}ms"
    )


@events.request.add_listener
def on_request(
    request_type, name, response_time, response_length, exception, **kwargs
):
    """Log request failures for debugging."""
    if exception:
        logger.warning(f"Request failed: {name} - {str(exception)}")


# Define user classes for different scenarios
class SmokeTestUser(ZenoChatUser):
    """Smoke test user with minimal load."""

    weight = 1
    wait_time = between(2, 5)


class LoadTestUser(ZenoChatUser):
    """Normal load test user."""

    weight = 3  # More common user type


class StressTestUser(ZenoChatUser):
    """Stress test user with aggressive patterns."""

    weight = 1
    wait_time = between(1, 3)  # Faster interaction

    def on_start(self):
        super().on_start()
        # Stress test users do longer conversations
        self.max_conversation_turns = random.randint(6, 10)


# For running specific scenarios via command line
if __name__ == "__main__":
    import sys

    scenario = sys.argv[1] if len(sys.argv) > 1 else "load"

    if scenario in ScenarioConfig.__dict__:
        config = getattr(ScenarioConfig, scenario.upper())
        print(f"Running {scenario} test: {config['description']}")
        print(
            f"Users: {config['users']}, Spawn rate: {config['spawn_rate']}, Duration: {config['run_time']}"
        )
    else:
        print("Available scenarios: smoke, load, stress, spike")
        print("Usage: python locustfile.py [scenario]")
