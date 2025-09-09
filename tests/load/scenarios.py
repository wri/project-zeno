"""
Predefined load testing scenarios for Project Zeno.

This module provides easy-to-use scenario runners that can be executed
directly or imported into other test scripts.
"""

import os
import subprocess
import sys
import time
from typing import Dict

from config import LoadTestConfig, ScenarioConfig


class ScenarioRunner:
    """Handles execution of different load testing scenarios."""

    def __init__(self, host: str = None):
        self.host = host or LoadTestConfig.BASE_URL
        self.locustfile = os.path.join(
            os.path.dirname(__file__), "locustfile.py"
        )

    def run_scenario(
        self, scenario_name: str, headless: bool = True, **kwargs
    ) -> subprocess.CompletedProcess:
        """
        Run a specific load testing scenario.

        Args:
            scenario_name: Name of scenario (smoke, load, stress, spike)
            headless: Run without web UI (default True)
            **kwargs: Additional arguments to pass to locust

        Returns:
            CompletedProcess object with results
        """
        if scenario_name.upper() not in ScenarioConfig.__dict__:
            raise ValueError(
                f"Unknown scenario: {scenario_name}. Available: smoke, load, stress, spike"
            )

        config = getattr(ScenarioConfig, scenario_name.upper())

        # Build locust command
        cmd = [
            "locust",
            "-f",
            self.locustfile,
            "--host",
            self.host,
            "--users",
            str(config["users"]),
            "--spawn-rate",
            str(config["spawn_rate"]),
            "-t",
            config["run_time"],
        ]

        if headless:
            cmd.append("--headless")

        # Add any additional arguments
        for key, value in kwargs.items():
            cmd.extend([f"--{key}", str(value)])

        print(f"🚀 Starting {scenario_name} scenario: {config['description']}")
        print(
            f"📊 Users: {config['users']}, Spawn rate: {config['spawn_rate']}, Duration: {config['run_time']}"
        )
        print(f"🎯 Target: {self.host}")
        print(f"💻 Command: {' '.join(cmd)}")
        print("-" * 50)

        try:
            result = subprocess.run(
                cmd, check=True, capture_output=False, text=True
            )
            print(
                f"✅ {scenario_name.capitalize()} scenario completed successfully"
            )
            return result
        except subprocess.CalledProcessError as e:
            print(
                f"❌ {scenario_name.capitalize()} scenario failed with exit code {e.returncode}"
            )
            raise

    def run_smoke_test(self, **kwargs) -> subprocess.CompletedProcess:
        """Run smoke test scenario."""
        return self.run_scenario("smoke", **kwargs)

    def run_load_test(self, **kwargs) -> subprocess.CompletedProcess:
        """Run load test scenario."""
        return self.run_scenario("load", **kwargs)

    def run_stress_test(self, **kwargs) -> subprocess.CompletedProcess:
        """Run stress test scenario."""
        return self.run_scenario("stress", **kwargs)

    def run_spike_test(self, **kwargs) -> subprocess.CompletedProcess:
        """Run spike test scenario."""
        return self.run_scenario("spike", **kwargs)

    def run_all_scenarios(self, delay_between: int = 30) -> Dict[str, bool]:
        """
        Run all scenarios in sequence with delays between them.

        Args:
            delay_between: Seconds to wait between scenarios

        Returns:
            Dict mapping scenario names to success/failure
        """
        scenarios = ["smoke", "load", "stress", "spike"]
        results = {}

        print("🎯 Running all load testing scenarios sequentially")
        print(f"⏱️  Delay between scenarios: {delay_between}s")
        print("=" * 60)

        for i, scenario in enumerate(scenarios):
            try:
                self.run_scenario(scenario, headless=True)
                results[scenario] = True
                print(f"✅ {scenario.capitalize()} completed")
            except subprocess.CalledProcessError:
                results[scenario] = False
                print(f"❌ {scenario.capitalize()} failed")

            # Add delay between scenarios (except after the last one)
            if i < len(scenarios) - 1:
                print(f"⏳ Waiting {delay_between}s before next scenario...")
                time.sleep(delay_between)

        # Print summary
        print("\n" + "=" * 60)
        print("📈 LOAD TEST SUMMARY")
        print("=" * 60)
        for scenario, success in results.items():
            status = "✅ PASSED" if success else "❌ FAILED"
            print(f"{scenario.upper():10s} - {status}")

        return results


def main():
    """Command line interface for scenario runner."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Run Project Zeno load testing scenarios"
    )
    parser.add_argument(
        "scenario",
        choices=["smoke", "load", "stress", "spike", "all"],
        help="Scenario to run",
    )
    parser.add_argument(
        "--host",
        default=LoadTestConfig.BASE_URL,
        help=f"Target host (default: {LoadTestConfig.BASE_URL})",
    )
    parser.add_argument(
        "--web-ui",
        action="store_true",
        help="Run with web UI instead of headless mode",
    )
    parser.add_argument("--csv", help="Save results to CSV file")
    parser.add_argument("--html", help="Save HTML report")

    args = parser.parse_args()

    # Validate configuration
    try:
        LoadTestConfig.validate_config()
    except ValueError as e:
        print(f"❌ Configuration error: {e}")
        print("💡 Set ZENO_MACHINE_USER_TOKEN environment variable")
        sys.exit(1)

    runner = ScenarioRunner(host=args.host)

    # Additional arguments for locust
    kwargs = {}
    if args.csv:
        kwargs["csv"] = args.csv
    if args.html:
        kwargs["html"] = args.html

    try:
        if args.scenario == "all":
            results = runner.run_all_scenarios()
            # Exit with error if any scenario failed
            if not all(results.values()):
                sys.exit(1)
        else:
            runner.run_scenario(
                args.scenario, headless=not args.web_ui, **kwargs
            )
    except KeyboardInterrupt:
        print("\n🛑 Load test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Load test failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
