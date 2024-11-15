import pandas as pd
from thefuzz import fuzz


class LocationMatcher:
    def __init__(self, csv_path):
        """
        Initialize the matcher with GADM CSV data
        """
        self.df = pd.read_csv(csv_path)
        self.df["full_name"] = (
            self.df["adm2_name"].fillna("")
            + " "
            + self.df["adm1_name"].fillna("")
            + " "
            + self.df["iso_name"].fillna("")
        ).str.strip()

    def find_matches(self, query, threshold=70):
        """
        Find matching locations for a given query.
        Priority order: ADM2 > ADM1 > ISO
        Returns top 3 for ADM2 matches, all matches for ADM1 and ISO
        """
        query = query.lower().strip()
        query_parts = query.split()
        matches = []

        # 1. Try exact matches first with ADM2 > ADM1 > ISO priority
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
        matches_by_type = {"adm2": [], "adm1": [], "iso": []}

        for match in matches:
            match_type = match["match_type"]
            if match_type in matches_by_type:
                matches_by_type[match_type].append(match)

        # Return based on priority and count rules
        if matches_by_type["adm2"]:
            return matches_by_type["adm2"][:3]  # Top 3 ADM2 matches
        elif matches_by_type["adm1"]:
            return matches_by_type["adm1"]  # All ADM1 matches
        elif matches_by_type["iso"]:
            return matches_by_type["iso"]  # All ISO matches
        else:
            return matches[:3]  # Top 3 for any other match types

    def _find_exact_matches(self, query):
        """Find exact matches in names with ADM2 > ADM1 > ISO priority"""
        # Check ADM2 names first
        exact_adm2 = self.df[self.df["adm2_name"].str.lower() == query]
        if not exact_adm2.empty:
            return self._format_results(exact_adm2, 100, "adm2")

        # Check ADM1 names next
        exact_adm1 = self.df[self.df["adm1_name"].str.lower() == query]
        if not exact_adm1.empty:
            return self._format_results(exact_adm1, 100, "adm1")

        # Check ISO names last
        exact_iso = self.df[self.df["iso_name"].str.lower() == query]
        if not exact_iso.empty:
            return self._format_results(exact_iso, 100, "iso")

        return []

    def _find_compound_matches(self, query_parts, threshold):
        """Find matches for compound queries"""
        matches = []
        for idx, row in self.df.iterrows():
            part_matches = []
            matched_levels = set()
            for part in query_parts:
                scores = {
                    "adm2": fuzz.ratio(part, str(row["adm2_name"]).lower()),
                    "adm1": fuzz.ratio(part, str(row["adm1_name"]).lower()),
                    "iso": fuzz.ratio(part, str(row["iso_name"]).lower()),
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
                        "adm2"
                        if "adm2" in matched_levels
                        else "adm1"
                        if "adm1" in matched_levels
                        else "iso"
                    )
                    matches.extend(
                        self._format_results(
                            self.df.iloc[[idx]], avg_score, match_type
                        )
                    )
        return matches

    def _find_fuzzy_matches(self, query, threshold):
        """Find fuzzy matches using string similarity with ADM2 > ADM1 > ISO priority"""
        matches = []
        for idx, row in self.df.iterrows():
            scores = {
                "adm2": fuzz.ratio(query, str(row["adm2_name"]).lower()),
                "adm1": fuzz.ratio(query, str(row["adm1_name"]).lower()),
                "iso": fuzz.ratio(query, str(row["iso_name"]).lower()),
            }

            # Find the best matching type based on priority and scores
            best_score = -1
            best_type = None

            # Check in priority order
            if scores["adm2"] >= threshold and scores["adm2"] > best_score:
                best_score = scores["adm2"]
                best_type = "adm2"
            elif scores["adm1"] >= threshold and scores["adm1"] > best_score:
                best_score = scores["adm1"]
                best_type = "adm1"
            elif scores["iso"] >= threshold and scores["iso"] > best_score:
                best_score = scores["iso"]
                best_type = "iso"

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
            key = f"{match['iso']}_{match['adm1']}_{match['adm2']}"
            if key not in seen or seen[key]["score"] < match["score"]:
                seen[key] = match
        return list(seen.values())

    def _format_results(self, matches, scores, match_type):
        """Format matching results into a standardized output"""
        if isinstance(scores, (int, float)):
            scores = [scores] * len(matches)

        results = []
        for (_, row), score in zip(matches.iterrows(), scores):
            results.append(
                {
                    "iso": row["iso"],
                    "adm1": int(row["adm1"]),
                    "adm2": int(row["adm2"]),
                    "names": {
                        "iso": row["iso_name"],
                        "adm1": row["adm1_name"],
                        "adm2": row["adm2_name"],
                    },
                    "score": score,
                    "match_type": match_type,
                }
            )
        return results


# Example usage with test cases
if __name__ == "__main__":
    # Sample data
    matcher = LocationMatcher("data/gadm.csv")

    # Test queries demonstrating priority order
    test_queries = [
        # ADM2 level queries
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
        # ISO level queries
        "india",
        "united states",
        # ADM1 level queries
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
            print(f"  ISO: {match['names']['iso']} ({match['iso']})")
            print(f"  ADM1: {match['names']['adm1']} ({match['adm1']})")
            print(f"  ADM2: {match['names']['adm2']} ({match['adm2']})")
        print("-" * 50)
