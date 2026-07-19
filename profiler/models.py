"""Canonical column schema for the intake sheet.

The order here MUST match Sheet1 of codebase_sheet.xlsx exactly. Each column maps a
spreadsheet header to a stable internal key; collectors emit values keyed by that
internal key and the writer renders them back in this order.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Column:
    """One spreadsheet column: its sheet header and the internal key collectors use."""

    key: str
    header: str
    #: True for fields the vendor supplies / that cannot be derived from code.
    vendor_provided: bool = False


# Order is authoritative — matches codebase_sheet.xlsx Sheet1.
COLUMNS: list[Column] = [
    Column("row_marker", "", vendor_provided=True),
    Column("dataset_id", "Dataset ID", vendor_provided=True),
    Column("type", "Type", vendor_provided=True),
    Column("vendor_name", "Vendor Name", vendor_provided=True),
    Column("originating_company", "Originating company", vendor_provided=True),
    Column("repo_name", "Dataset / Repo Name"),
    Column("description", "Description", vendor_provided=True),
    Column("num_repos", "# Repos in Dataset"),
    Column("raw_loc", "Raw LOC (incl blanks & comments)"),
    Column("logical_loc", "Logical LOC (excl blanks & comments)"),
    Column("dependency_loc", "Dependency dirs LOC"),
    Column("public_loc", "Public LOC", vendor_provided=True),
    Column("autogen_loc", "Auto-Generated LOC"),
    Column("duplication_ratio", "Duplication Ratio (0.00-1.00)"),
    Column("fork_pct", "Fork % (0.00-1.00)"),
    Column("total_source_files", "Total Source Files"),
    Column("primary_language", "Primary Language"),
    Column("language_distribution", "Language Distribution (% breakdown)"),
    Column("non_merge_commits", "Non-Merge Commit Count"),
    Column("unique_contributors", "Unique Contributors"),
    Column("total_prs", "Total PR Count"),
    Column("reviewed_prs", "Reviewed PR Count"),
    Column("ci_checks", "CI Checks on PRs? (Yes/No)"),
    Column("deployment_infra", "Deployment Infrastructure"),
    Column("monitoring", "Monitoring & Observability"),
    Column("test_suite", "Test Suite Presence"),
    Column("unit_test_coverage_pct", "Unit test coverage % (branch > line > function)"),
    Column("containerized", "Containerized? (Yes/No)"),
    Column("holdout_verification", "Holdout Verification", vendor_provided=True),
    Column("docstring_ratio", "Docstring Ratio (0.00-1.00)"),
    Column("readme_quality", "README Quality"),
    Column("issue_tracker", "Issue Tracker"),
    Column("avg_function_length", "Avg Function Length (lines)"),
    Column("llm_written_pct", "(if any) % of code written with LLM"),
    Column("quoted_price", "Quoted Price ($)", vendor_provided=True),
    Column("dataset_cost_per_repo", "Dataset cost per Repo", vendor_provided=True),
]

KEYS: list[str] = [c.key for c in COLUMNS]


@dataclass
class ProfileResult:
    """Accumulated column values plus any per-collector warnings."""

    values: dict[str, object] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def merge(self, key_to_value: dict[str, object]) -> None:
        self.values.update(key_to_value)

    def as_row(self) -> list[object]:
        """Render values in canonical column order; missing keys become blank."""
        return [self.values.get(c.key, "") for c in COLUMNS]
