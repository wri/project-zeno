"""
CSV data loading for E2E testing framework.
"""

from typing import List

import pandas as pd

from ..types import ExpectedData


class CSVLoader:
    """Handles loading test data from CSV files."""

    @staticmethod
    def load_test_data(
        csv_file: str, sample_size: int = 0
    ) -> List[ExpectedData]:
        """
        Load test data from CSV file.

        Args:
            csv_file: Path to CSV test file
            sample_size: Number of test cases to load (0 means all)

        Returns:
            List of ExpectedData objects
        """
        # Read CSV as strings and clean up
        df = pd.read_csv(csv_file, dtype=str, keep_default_na=False)

        # Simple cleanup: replace NaN/null with empty string
        df = df.fillna("")

        # Clean all string values
        for col in df.columns:
            df[col] = df[col].astype(str).str.strip()
            df[col] = df[col].replace(
                ["nan", "NaN", "null", "NULL", "None"], ""
            )

        # Filter by status - only include tests that should be run
        # Skip tests with status: done, fail, skip
        runnable_statuses = ["ready", "rerun"]
        if "status" in df.columns:
            original_count = len(df)
            df = df[
                df["status"]
                .str.lower()
                .isin([s.lower() for s in runnable_statuses])
            ]
            filtered_count = len(df)
            if filtered_count < original_count:
                print(
                    f"Filtered {original_count - filtered_count} tests based on status (keeping only: {', '.join(runnable_statuses)})"
                )

        # Sample if requested (-1 means run all rows, 0+ means run that many)
        if sample_size > 0 and sample_size < len(df):
            df = df.sample(n=sample_size)
        # sample_size == -1 means run all rows (no sampling)

        test_cases = []
        for _, row in df.iterrows():
            test_case = ExpectedData(
                expected_aoi_id=row.get("expected_aoi_id", ""),
                expected_aoi_name=row.get("expected_aoi_name", ""),
                expected_subregion=row.get("expected_subregion", ""),
                expected_aoi_subtype=row.get("expected_aoi_subtype", ""),
                expected_aoi_source=row.get("expected_aoi_source", ""),
                expected_dataset_id=row.get("expected_dataset_id", ""),
                expected_dataset_name=row.get("expected_dataset_name", ""),
                expected_context_layer=row.get("expected_context_layer", ""),
                expected_start_date=row.get("expected_start_date", ""),
                expected_end_date=row.get("expected_end_date", ""),
                expected_answer=row.get("expected_answer", ""),
                test_group=row.get("test_group", "unknown"),
                status=row.get("status", "ready"),
            )
            # Add query field to the test case
            test_case.query = row.get("query", "")
            test_cases.append(test_case)

        return test_cases
