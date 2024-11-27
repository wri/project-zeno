import pandas as pd
from thefuzz import fuzz
import geopandas as gpd


NAME_COLS = ["NAME_1", "NAME_2", "NAME_3"]

class LocationMatcher:
    def __init__(self, csv_path):
        """
        Initialize the matcher with GADM CSV data
        """
        # self.df = pd.read_csv(csv_path)
        self.df = gpd.read_file(csv_path, layer="ADM_ADM_3")
        self.df["full_name"] = self.df[NAME_COLS].agg(' '.join, axis=1)
        # "".join([self.df[col].fillna("").str.strip() for col in NAME_COLS])
        #     self.df["NAME_2_name"].fillna("")
        #     + " "
        #     + self.df["NAME_1_name"].fillna("")
        #     + " "
        #     + self.df["NAME_3_name"].fillna("")
        # ).str.strip()

    def find_matches(self, query, threshold=70):
        """
        Find matching locations for a given query.
        Priority order: NAME_2 > NAME_1 > NAME_3
        Returns top 3 for NAME_2 matches, all matches for NAME_1 and NAME_3
        """
        query = query.lower().strip()
        query_parts = query.split()
        matches = []

        # 1. Try exact matches first with NAME_2 > NAME_1 > NAME_3 priority
        exact_matches = self._find_exact_matches(query)
        if exact_matches:
            return self._filter_results_by_type(exact_matches)

        # 2. Try compound and fuzzy matching
        compound_matches = []
        if len(query_parts) > 1:
            compound_matches = self._find_compound_matches(
                query_parts, threshold
            )
        fuzzy_matches = self._find_fuzzy_matches(query, threshold)

        # Combine and deduplicate matches
        matches = compound_matches + fuzzy_matches
        unique_matches = self._deduplicate_matches(matches)
        sorted_matches = sorted(
            unique_matches, key=lambda x: x["score"], reverse=True
        )

        return self._filter_results_by_type(sorted_matches)

    def _filter_results_by_type(self, matches):
        """Filter results based on match type priority and count rules"""
        if not matches:
            return []

        # Group matches by type
        matches_by_type = {"NAME_2": [], "NAME_1": [], "NAME_3": []}

        for match in matches:
            match_type = match["match_type"]
            if match_type in matches_by_type:
                matches_by_type[match_type].append(match)

        # Return based on priority and count rules
        if matches_by_type["NAME_2"]:
            return matches_by_type["NAME_2"][:3]  # Top 3 NAME_2 matches
        elif matches_by_type["NAME_1"]:
            return matches_by_type["NAME_1"]  # All NAME_1 matches
        elif matches_by_type["NAME_3"]:
            return matches_by_type["NAME_3"]  # All NAME_3 matches
        else:
            return matches[:3]  # Top 3 for any other match types

    def _find_exact_matches(self, query):
        """Find exact matches in names with NAME_2 > NAME_1 > NAME_3 priority"""
        # Check NAME_2 names first
        exact_NAME_2 = self.df[self.df["NAME_2"].str.lower() == query]
        if not exact_NAME_2.empty:
            return self._format_results(exact_NAME_2, 100, "NAME_2")

        # Check NAME_1 names next
        exact_NAME_1 = self.df[self.df["NAME_1"].str.lower() == query]
        if not exact_NAME_1.empty:
            return self._format_results(exact_NAME_1, 100, "NAME_1")

        # Check NAME_3 names last
        exact_NAME_3 = self.df[self.df["NAME_3"].str.lower() == query]
        if not exact_NAME_3.empty:
            return self._format_results(exact_NAME_3, 100, "NAME_3")

        return []

    def _find_compound_matches(self, query_parts, threshold):
        """Find matches for compound queries"""
        matches = []
        for idx, row in self.df.iterrows():
            part_matches = []
            matched_levels = set()
            for part in query_parts:
                scores = {
                    "NAME_2": fuzz.ratio(part, str(row["NAME_2"]).lower()),
                    "NAME_1": fuzz.ratio(part, str(row["NAME_1"]).lower()),
                    "NAME_3": fuzz.ratio(part, str(row["NAME_3"]).lower()),
                }
                best_score = max(scores.values())
                best_type = max(scores.items(), key=lambda x: x[1])[0]
                if best_score >= threshold:
                    part_matches.append((best_score, best_type))
                    matched_levels.add(best_type)

            if part_matches:
                avg_score = sum(score for score, _ in part_matches) / len(
                    part_matches
                )
                if avg_score >= threshold:
                    # Determine match type based on highest priority level matched
                    match_type = (
                        "NAME_2"
                        if "NAME_2" in matched_levels
                        else "NAME_1"
                        if "NAME_1" in matched_levels
                        else "NAME_3"
                    )
                    matches.extend(
                        self._format_results(
                            self.df.iloc[[idx]], avg_score, match_type
                        )
                    )
        return matches

    def _find_fuzzy_matches(self, query, threshold):
        """Find fuzzy matches using string similarity with NAME_2 > NAME_1 > NAME_3 priority"""
        matches = []
        for idx, row in self.df.iterrows():
            scores = {
                "NAME_1": fuzz.ratio(query, str(row["NAME_1"]).lower()),
                "NAME_2": fuzz.ratio(query, str(row["NAME_2"]).lower()),
                "NAME_3": fuzz.ratio(query, str(row["NAME_3"]).lower()),
            }

            # Find the best matching type based on priority and scores
            best_score = -1
            best_type = None

            # Check in priority order
            if scores["NAME_2"] >= threshold and scores["NAME_2"] > best_score:
                best_score = scores["NAME_2"]
                best_type = "NAME_2"
            elif scores["NAME_1"] >= threshold and scores["NAME_1"] > best_score:
                best_score = scores["NAME_1"]
                best_type = "NAME_1"
            elif scores["NAME_3"] >= threshold and scores["NAME_3"] > best_score:
                best_score = scores["NAME_3"]
                best_type = "NAME_3"

            if best_type:
                matches.extend(
                    self._format_results(
                        self.df.iloc[[idx]], best_score, best_type
                    )
                )
        return matches

    def _deduplicate_matches(self, matches):
        """Remove duplicate matches, keeping the highest score"""
        seen = {}
        for match in matches:
            key = f"{match['NAME_3']}_{match['NAME_1']}_{match['NAME_2']}"
            if key not in seen or seen[key]["score"] < match["score"]:
                seen[key] = match
        return list(seen.values())

    def _format_results(self, matches, scores, match_type):
        """Format matching results into a standardized output"""
        if isinstance(scores, (int, float)):
            scores = [scores] * len(matches)

        results = []
        for (_, row), score in zip(matches.iterrows(), scores):
            row["score"] = score
            row["match_type"] = match_type
            results.append(row)

        return gpd.GeoDataFrame(results)


# Example usage with test cases
if __name__ == "__main__":
    # Sample data
    matcher = LocationMatcher("data/gadm.csv")

    # Test queries demonstrating priority order
    test_queries = [
        # NAME_2 level queries
        "san francisco",
        "manhattan",
        "greater london",
        "shenzhen",
        # Compound queries
        "paris france",
        "tokyo shibuya",
        "madrid spain",
        "moscow russia",
        # Variations and misspellings
        "sidney australia",  # Misspelling of Sydney
        "bankok",  # Misspelling of Bangkok
        "san fransisco",  # Common misspelling
        "neu york",  # German spelling
        # Partial matches
        "johannesburg gauteng",
        "toronto ontario canada",
        "cairo egypt",
        # Alternative forms
        "manhattan ny",
        "sf california",
        "london uk",
        # NAME_3 level queries
        "india",
        "united states",
        # NAME_1 level queries
        "california",
        "new york",
        "île de france",  # Accent variation
        "sao paulo",  # Missing accent
    ]

    for query in test_queries:
        print(f"\nQuery: {query}")
        matches = matcher.find_matches(query, threshold=60)
        print(f"Found {len(matches)} matches:")
        for match in matches:
            print(
                f"Match (score: {match['score']}, type: {match['match_type']}):"
            )
            print(f"  NAME_3: {match['names']['NAME_3']} ({match['NAME_3']})")
            print(f"  NAME_1: {match['names']['NAME_1']} ({match['NAME_1']})")
            print(f"  NAME_2: {match['names']['NAME_2']} ({match['NAME_2']})")
        print("-" * 50)
