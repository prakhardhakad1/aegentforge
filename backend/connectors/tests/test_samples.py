"""Sample dataset contract + story-sanity tests.

Verifies the four committed CSVs exist with exact row counts, documented
columns, clean ids, and the analytical stories they were built to tell
(cross-checked against data/samples/EXPECTED_INSIGHTS.md).
"""

from __future__ import annotations

import csv
import importlib.util
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from connectors import (
    DATA_DICTIONARIES,
    SAMPLE_IDS,
    SAMPLE_META,
    load_sample,
    samples_dir,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SAMPLES_DIR = samples_dir()

EXPECTED_ROWS = {"saas_churn": 2000, "ecommerce_sales": 5000, "support_tickets": 1500, "marketing_spend": 800}
EXPECTED_COLUMNS = {
    "saas_churn": [
        "customer_id", "signup_date", "plan", "monthly_price", "region",
        "months_active", "logins_last_30d", "tickets_raised", "is_churned",
    ],
    "ecommerce_sales": [
        "order_id", "order_date", "product_category", "product_name", "region",
        "channel", "quantity", "unit_price", "revenue", "is_returned",
    ],
    "support_tickets": [
        "ticket_id", "created_date", "category", "priority", "subject",
        "first_response_hours", "resolution_hours", "is_resolved", "csat",
    ],
    "marketing_spend": [
        "week_start_date", "channel", "spend", "impressions", "clicks",
        "signups", "conversions",
    ],
}


def _rows(sample_id: str) -> list[dict[str, str]]:
    path = SAMPLES_DIR / f"{sample_id}.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


# --------------------------------------------------------------------------- #
# Files, shapes, ids
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sample_id", sorted(EXPECTED_ROWS))
def test_csv_exists_with_exact_row_count(sample_id: str) -> None:
    path = SAMPLES_DIR / f"{sample_id}.csv"
    assert path.is_file(), f"missing sample CSV: {path} — run scripts/generate_samples.py"
    rows = _rows(sample_id)
    assert len(rows) == EXPECTED_ROWS[sample_id]


@pytest.mark.parametrize("sample_id", sorted(EXPECTED_COLUMNS))
def test_expected_columns_present_in_order(sample_id: str) -> None:
    rows = _rows(sample_id)
    assert list(rows[0]) == EXPECTED_COLUMNS[sample_id]


@pytest.mark.parametrize("sample_id", sorted(EXPECTED_ROWS))
def test_id_column_unique_and_never_empty(sample_id: str) -> None:
    id_column = {
        "saas_churn": "customer_id",
        "ecommerce_sales": "order_id",
        "support_tickets": "ticket_id",
    }.get(sample_id)
    rows = _rows(sample_id)
    if id_column is None:
        return  # marketing_spend is a time series with no single id column
    values = [row[id_column] for row in rows]
    assert all(value.strip() for value in values), f"empty {id_column} found"
    assert len(set(values)) == len(values), f"duplicate {id_column} found"


def test_no_empty_cells_in_key_dimensions() -> None:
    for sample_id, columns in (
        ("saas_churn", ["signup_date", "plan", "region", "is_churned"]),
        ("ecommerce_sales", ["order_date", "product_category", "channel", "revenue"]),
        ("support_tickets", ["created_date", "category", "priority", "is_resolved"]),
        ("marketing_spend", ["week_start_date", "channel", "spend", "signups"]),
    ):
        rows = _rows(sample_id)
        for column in columns:
            assert all(row[column].strip() for row in rows), f"empty {column} in {sample_id}"


def test_data_dictionaries_cover_all_samples_and_columns() -> None:
    for sample_id in SAMPLE_IDS:
        dictionary = DATA_DICTIONARIES.get(sample_id)
        assert dictionary, f"DATA_DICTIONARIES missing section for {sample_id}"
        missing = set(EXPECTED_COLUMNS[sample_id]) - set(dictionary)
        assert not missing, f"{sample_id} dictionary missing columns: {missing}"


# --------------------------------------------------------------------------- #
# load_sample / SAMPLE_META contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sample_id", sorted(SAMPLE_IDS))
def test_load_sample_returns_dataset_and_dictionary(sample_id: str) -> None:
    dataset, dictionary = load_sample(sample_id)
    assert dataset.row_count == EXPECTED_ROWS[sample_id]
    assert dataset.columns == EXPECTED_COLUMNS[sample_id]
    assert dictionary["sample_id"] == sample_id
    assert dictionary["row_count"] == EXPECTED_ROWS[sample_id]
    assert dictionary["story"]
    assert dictionary["name"]
    assert set(dictionary["columns"]) == set(EXPECTED_COLUMNS[sample_id])
    assert (SAMPLES_DIR / f"{sample_id}.csv") == Path(dictionary["path"])


def test_load_sample_unknown_id_raises_keyerror_with_ids() -> None:
    with pytest.raises(KeyError) as excinfo:
        load_sample("does_not_exist")
    assert "saas_churn" in str(excinfo.value)


def test_sample_meta_row_counts_match_generated_data() -> None:
    for sample_id in SAMPLE_IDS:
        assert SAMPLE_META[sample_id]["row_count"] == EXPECTED_ROWS[sample_id]
        rows = _rows(sample_id)
        assert len(rows) == SAMPLE_META[sample_id]["row_count"]


# --------------------------------------------------------------------------- #
# Story sanity — saas_churn
# ---------------------------------------------------------------------------


def test_saas_overall_churn_between_20_and_30_percent() -> None:
    rows = _rows("saas_churn")
    churn_rate = sum(int(r["is_churned"]) for r in rows) / len(rows)
    assert 0.20 <= churn_rate <= 0.30, f"churn rate {churn_rate:.1%} outside story range"


def test_saas_basic_plan_churns_much_more_than_enterprise() -> None:
    rows = _rows("saas_churn")
    by_plan: dict[str, list[int]] = {}
    for row in rows:
        by_plan.setdefault(row["plan"], []).append(int(row["is_churned"]))
    assert set(by_plan) == {"basic", "pro", "enterprise"}
    rates = {plan: sum(v) / len(v) for plan, v in by_plan.items()}
    assert rates["basic"] > 2 * rates["pro"]
    assert rates["pro"] > 2 * rates["enterprise"]


def test_saas_churned_customers_show_collapsed_usage() -> None:
    rows = _rows("saas_churn")
    active_logins = sorted(int(r["logins_last_30d"]) for r in rows if r["is_churned"] == "0")
    churned_logins = sorted(int(r["logins_last_30d"]) for r in rows if r["is_churned"] == "1")
    median_active = active_logins[len(active_logins) // 2]
    median_churned = churned_logins[len(churned_logins) // 2]
    assert median_churned * 2 <= median_active  # usage collapse signal
    churned_tickets = sum(int(r["tickets_raised"]) for r in rows if r["is_churned"] == "1")
    active_tickets = sum(int(r["tickets_raised"]) for r in rows if r["is_churned"] == "0")
    assert churned_tickets / max(1, sum(1 for r in rows if r["is_churned"] == "1")) > \
        active_tickets / max(1, sum(1 for r in rows if r["is_churned"] == "0"))


def test_saas_prices_consistent_with_plan() -> None:
    rows = _rows("saas_churn")
    bands = {"basic": (0, 60), "pro": (60, 200), "enterprise": (200, 1100)}
    for row in rows:
        price = float(row["monthly_price"])
        lo, hi = bands[row["plan"]]
        assert lo <= price <= hi


# --------------------------------------------------------------------------- #
# Story sanity — ecommerce_sales
# ---------------------------------------------------------------------------


def test_ecommerce_revenue_equals_quantity_times_price() -> None:
    for row in _rows("ecommerce_sales"):
        expected = round(int(row["quantity"]) * float(row["unit_price"]), 2)
        assert abs(float(row["revenue"]) - expected) < 0.01


def test_ecommerce_q4_holiday_spike() -> None:
    monthly: Counter[str] = Counter()
    for row in _rows("ecommerce_sales"):
        monthly[row["order_date"][:7]] += float(row["revenue"])
    assert monthly["2025-12"] > 2 * monthly["2025-10"]  # December >= 2x October
    q4 = monthly["2025-11"] + monthly["2025-12"]
    total = sum(monthly.values())
    assert q4 / total > 0.20  # Nov+Dec clearly above the 1/6 baseline


def test_ecommerce_return_rate_6_to_10_percent() -> None:
    rows = _rows("ecommerce_sales")
    rate = sum(int(r["is_returned"]) for r in rows) / len(rows)
    assert 0.06 <= rate <= 0.10


def test_ecommerce_mobile_share_grows_and_books_declines() -> None:
    rows = _rows("ecommerce_sales")
    early = [r for r in rows if r["order_date"] <= "2026-01-31"]
    late = [r for r in rows if r["order_date"] >= "2026-07-01"]
    early_mobile = sum(1 for r in early if r["channel"] == "mobile") / len(early)
    late_mobile = sum(1 for r in late if r["channel"] == "mobile") / len(late)
    assert late_mobile > early_mobile
    early_books = sum(1 for r in early if r["product_category"] == "books") / len(early)
    late_books = sum(1 for r in late if r["product_category"] == "books") / len(late)
    assert late_books < early_books


def test_ecommerce_dates_within_12_month_window() -> None:
    for row in _rows("ecommerce_sales"):
        day = date.fromisoformat(row["order_date"])
        assert date(2025, 10, 1) <= day <= date(2026, 9, 30)


# --------------------------------------------------------------------------- #
# Story sanity — support_tickets
# ---------------------------------------------------------------------------


def test_support_billing_and_login_bug_dominate_volume() -> None:
    rows = _rows("support_tickets")
    counts = Counter(r["category"] for r in rows)
    combined = (counts["billing"] + counts["login_bug"]) / len(rows)
    assert combined >= 0.45


def test_support_integration_resolution_about_3x_others() -> None:
    rows = _rows("support_tickets")
    integration = sorted(float(r["resolution_hours"]) for r in rows if r["category"] == "integration")
    others = sorted(float(r["resolution_hours"]) for r in rows if r["category"] != "integration")
    median_integration = integration[len(integration) // 2]
    median_others = others[len(others) // 2]
    ratio = median_integration / median_others
    assert 2.0 <= ratio <= 5.0, f"integration ratio {ratio:.1f}x off-story"


def test_support_response_time_worsened_in_recent_months() -> None:
    rows = _rows("support_tickets")
    early = [float(r["first_response_hours"]) for r in rows if r["created_date"] < "2026-01-01"]
    late = [float(r["first_response_hours"]) for r in rows if r["created_date"] >= "2026-07-01"]
    early.sort()
    late.sort()
    assert late[len(late) // 2] > early[len(early) // 2]


def test_support_csat_only_when_resolved_and_in_range() -> None:
    rows = _rows("support_tickets")
    for row in rows:
        resolved = row["is_resolved"] == "1"
        if resolved:
            assert row["csat"].strip(), f"resolved ticket {row['ticket_id']} missing csat"
            assert 1 <= int(row["csat"]) <= 5
        else:
            assert not row["csat"].strip(), f"unresolved ticket {row['ticket_id']} has csat"


# --------------------------------------------------------------------------- #
# Story sanity — marketing_spend
# ---------------------------------------------------------------------------


def test_marketing_spend_row_shape_channels_and_weeks() -> None:
    rows = _rows("marketing_spend")
    weeks = {r["week_start_date"] for r in rows}
    assert len(weeks) == 160
    channels = {r["channel"] for r in rows}
    assert channels == {"search", "social", "email", "content", "referral"}
    per_week: dict[str, set[str]] = {}
    for row in rows:
        per_week.setdefault(row["week_start_date"], set()).add(row["channel"])
    assert all(len(channels_) == 5 for channels_ in per_week.values())


def test_marketing_funnel_internally_consistent() -> None:
    for row in _rows("marketing_spend"):
        impressions, clicks = int(row["impressions"]), int(row["clicks"])
        signups, conversions = int(row["signups"]), int(row["conversions"])
        assert clicks <= impressions
        assert signups <= clicks
        assert conversions <= signups
        assert float(row["spend"]) > 0


def test_marketing_email_and_search_beat_social_on_roi() -> None:
    rows = _rows("marketing_spend")
    spend: dict[str, float] = Counter()
    signups: dict[str, int] = Counter()
    for row in rows:
        spend[row["channel"]] += float(row["spend"])
        signups[row["channel"]] += int(row["signups"])
    efficiency = {ch: signups[ch] / spend[ch] for ch in spend}
    assert efficiency["email"] > efficiency["search"] > efficiency["social"] * 5
    assert efficiency["social"] == min(efficiency.values())
    assert efficiency["content"] > efficiency["referral"] * 0.9  # content compounds to parity


def test_marketing_content_efficiency_compounds() -> None:
    rows = [r for r in _rows("marketing_spend") if r["channel"] == "content"]
    rows.sort(key=lambda r: r["week_start_date"])
    first, last = rows[:20], rows[-20:]
    first_eff = sum(int(r["signups"]) for r in first) / sum(float(r["spend"]) for r in first)
    last_eff = sum(int(r["signups"]) for r in last) / sum(float(r["spend"]) for r in last)
    assert last_eff > first_eff * 1.3


def test_marketing_spend_positively_drives_signups_per_channel() -> None:
    """The story is per-channel spend->signups elasticity, so test it per channel."""
    rows = _rows("marketing_spend")
    by_channel: dict[str, list[tuple[float, int]]] = {}
    for row in rows:
        by_channel.setdefault(row["channel"], []).append((float(row["spend"]), int(row["signups"])))
    assert set(by_channel) == {"search", "social", "email", "content", "referral"}
    for channel, pairs in by_channel.items():
        spend = [s for s, _ in pairs]
        signups = [g for _, g in pairs]
        mean_s, mean_g = sum(spend) / len(spend), sum(signups) / len(signups)
        cov = sum((s - mean_s) * (g - mean_g) for s, g in pairs)
        var_s = sum((s - mean_s) ** 2 for s in spend)
        var_g = sum((g - mean_g) ** 2 for g in signups)
        correlation = cov / ((var_s * var_g) ** 0.5)
        assert correlation > 0.4, f"{channel} spend->signups corr {correlation:.2f} too weak"


# --------------------------------------------------------------------------- #
# Generator determinism
# ---------------------------------------------------------------------------


def test_generator_is_deterministic(tmp_path: Path, sample_id: str = "saas_churn") -> None:
    spec = importlib.util.spec_from_file_location(
        "agentforge_generate_samples", REPO_ROOT / "scripts" / "generate_samples.py"
    )
    assert spec and spec.loader
    module: Any = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    run_a, run_b = tmp_path / "a", tmp_path / "b"
    module.generate_all(20261005, run_a)
    module.generate_all(20261005, run_b)
    for name in EXPECTED_ROWS:
        assert (run_a / f"{name}.csv").read_bytes() == (run_b / f"{name}.csv").read_bytes()

    committed = SAMPLES_DIR / f"{sample_id}.csv"
    assert committed.read_bytes() == (run_a / f"{sample_id}.csv").read_bytes(), (
        "committed CSVs must match the generator output (seed 20261005)"
    )
