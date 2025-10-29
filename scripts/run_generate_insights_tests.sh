#!/bin/bash
# Hacky solution to run generate_insights tests individually
# This works around the event loop closure issue when running multiple tests together

set -e  # Exit on first failure

echo "🧪 Running generate_insights tests individually..."
echo "================================================"
echo ""

# Array of test names
tests=(
    # "test_generate_insights_comparison"
    "test_simple_line_chart"
    "test_simple_bar_chart"
    "test_stacked_bar_chart"
    "test_grouped_bar_chart"
    "test_pie_chart"
)

# Track results
passed=0
failed=0
failed_tests=()

# Run each test individually
for test in "${tests[@]}"; do
    echo "Running: $test"
    if uv run pytest "tests/tools/test_generate_insights.py::$test" -v --tb=short; then
        echo "✅ PASSED: $test"
        ((passed++))
    else
        echo "❌ FAILED: $test"
        ((failed++))
        failed_tests+=("$test")
    fi
    echo ""
done

# Summary
echo "================================================"
echo "📊 Test Summary"
echo "================================================"
echo "Total tests: ${#tests[@]}"
echo "Passed: $passed"
echo "Failed: $failed"
echo ""

if [ $failed -gt 0 ]; then
    echo "❌ Failed tests:"
    for test in "${failed_tests[@]}"; do
        echo "  - $test"
    done
    exit 1
else
    echo "✅ All tests passed!"
    exit 0
fi
