"""
Result export functionality for E2E testing framework.
"""

import csv
import os
from datetime import datetime
from typing import List

from ..types import TestResult


class ResultExporter:
    """Handles exporting test results to CSV files."""

    @staticmethod
    def save_results_to_csv(
        results: List[TestResult], filename: str = None
    ) -> str:
        """
        Save test results to two CSV files: summary and detailed.

        Args:
            results: List of test results
            filename: Base filename (optional)

        Returns:
            Path to summary CSV file
        """
        if not results:
            return ""

        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            base_filename = f"data/tests/simple_e2e_{timestamp}"
        else:
            base_filename = filename.replace(".csv", "")

        # Create directory if needed
        os.makedirs(
            os.path.dirname(f"{base_filename}_summary.csv"), exist_ok=True
        )

        # 1. Summary CSV - just query and scores
        summary_fields = [
            "query",
            "overall_score",
            "aoi_score",
            "dataset_score",
            "pull_data_score",
            "answer_score",
            "execution_time",
            "error",
        ]

        summary_filename = f"{base_filename}_summary.csv"
        with open(summary_filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, fieldnames=summary_fields, extrasaction="ignore"
            )
            writer.writeheader()
            writer.writerows([result.to_dict() for result in results])

        # 2. Detailed CSV - expected vs actual side by side
        detailed_fields = [
            # Basic info
            "query",
            "thread_id",
            "overall_score",
            "execution_time",
            "test_mode",
            # AOI: Expected vs Actual
            "expected_aoi_id",
            "actual_id",
            "aoi_score",
            "match_aoi_id",
            "expected_aoi_name",
            "actual_name",
            "expected_subregion",
            "match_subregion",
            "expected_aoi_subtype",
            "actual_subtype",
            "expected_aoi_source",
            "actual_source",
            # Dataset: Expected vs Actual
            "expected_dataset_id",
            "actual_dataset_id",
            "dataset_score",
            "expected_dataset_name",
            "actual_dataset_name",
            "expected_context_layer",
            "actual_context_layer",
            # Data Pull: Expected vs Actual
            "expected_start_date",
            "pull_data_score",
            "expected_end_date",
            "row_count",
            "data_pull_success",
            "date_success",
            # Answer: Expected vs Actual
            "expected_answer",
            "actual_answer",
            "answer_score",
            # Metadata
            "test_group",
            "error",
        ]

        detailed_filename = f"{base_filename}_detailed.csv"
        with open(detailed_filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, fieldnames=detailed_fields, extrasaction="ignore"
            )
            writer.writeheader()
            writer.writerows([result.to_dict() for result in results])

        print(f"Summary results saved to: {summary_filename}")
        print(f"Detailed results saved to: {detailed_filename}")
        return summary_filename
