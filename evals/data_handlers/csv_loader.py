"""
CSV data loading for E2E testing framework.
"""

from typing import List

import pandas as pd

from evals.utils.eval_types import ExpectedData


class CSVLoader:
    """Handles loading test data from CSV files."""

    @staticmethod
    def load_test_data(
        csv_file: str,
        sample_size: int = 0,
        test_group_filter: str = None,
        status_filter: str = None,
        random_seed: int = 42,
        offset: int = 0,
    ) -> List[ExpectedData]:
        """
        Load test data from CSV file.

        Args:
            csv_file: Path to CSV test file
            sample_size: Number of test cases to load (0 means all)
            test_group_filter: Filter by test_group column (optional)
            status_filter: Filter by status column (optional)
            random_seed: Random seed for sampling (optional)
            offset: Offset for sampling (optional)
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
        if "status" in df.columns and status_filter:
            original_count = len(df)
            df = df[
                df["status"]
                .str.lower()
                .isin([s.lower() for s in status_filter])
            ]
            filtered_count = len(df)
            if filtered_count < original_count:
                print(
                    f"Filtered {original_count - filtered_count} tests based on status (keeping only: {', '.join(status_filter)})"
                )

        # Filter by test_group if specified
        if test_group_filter and "test_group" in df.columns:
            original_count = len(df)
            df = df[
                df["test_group"]
                .str.lower()
                .str.contains(test_group_filter.lower(), na=False)
            ]
            filtered_count = len(df)
            if filtered_count < original_count:
                print(
                    f"Filtered {original_count - filtered_count} tests based on test_group filter '{test_group_filter}'"
                )

        # Sample if requested (-1 means run all rows, 0+ means run that many)
        if sample_size > 0 and sample_size < len(df):
            df = df.sample(n=sample_size, random_state=42)
        # sample_size == -1 means run all rows (no sampling)

        print(f"Final test count after all filters: {len(df)} tests")

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
