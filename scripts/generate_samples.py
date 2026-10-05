#!/usr/bin/env python
"""Generate the four AgentForge sample business datasets (deterministic).

Writes realistic, internally consistent CSVs with real-world-shaped noise,
trends, and clear analytical stories to ``<repo>/data/samples/``:

    saas_churn.csv      2,000 rows  churn driven by plan + declining usage
    ecommerce_sales.csv 5,000 rows  Q4 holiday spike, mobile share growth,
                                    declining books category, ~8% returns
    support_tickets.csv 1,500 rows  billing/login_bug dominate, integration
                                    ~3x slower, response times worsening
    marketing_spend.csv   800 rows  5 channels x 160 weeks; search+email best
                                    ROI, content compounds, social underperforms

Stdlib only (csv, random, datetime). Every random draw comes from
``random.Random`` instances seeded from a single fixed seed, so re-running
this script reproduces the CSVs byte-for-byte.

Usage (from the repo root)::

    python scripts/generate_samples.py [--seed 20261005] [--out-dir data/samples]
"""

from __future__ import annotations

import argparse
import csv
import math
import random
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

DEFAULT_SEED = 20261005
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "samples"

# ---------------------------------------------------------------------------
# 1. saas_churn.csv — 2,000 customers
# ---------------------------------------------------------------------------

_SAAS_ROWS = 2000
_SAAS_SIGNUP_START = date(2023, 10, 1)
_SAAS_SIGNUP_END = date(2026, 8, 31)  # guarantees >= 1 month of tenure before cutoff
_SAAS_CUTOFF = date(2026, 9, 30)

# Monthly churn hazard baselines by plan: basic month-to-month churns hardest.
_SAAS_PLAN_WEIGHTS = {"basic": 50, "pro": 35, "enterprise": 15}
_SAAS_PLAN_HAZARD = {"basic": 0.040, "pro": 0.015, "enterprise": 0.006}
_SAAS_PLAN_PRICE = {"basic": (29.0, 4.0, 19.0, 49.0), "pro": (99.0, 12.0, 79.0, 149.0), "enterprise": (499.0, 90.0, 299.0, 999.0)}
_SAAS_REGION_WEIGHTS = {"north_america": 40, "europe": 30, "apac": 20, "latam": 10}
# Usage classes: declining-usage customers are the churn engine of the story.
_SAAS_USAGE_WEIGHTS = {"engaged": 55, "average": 30, "declining": 15}
_SAAS_USAGE_BASE = {"engaged": 45.0, "average": 20.0, "declining": 26.0}
_SAAS_USAGE_DECAY = {"engaged": 1.0, "average": 0.995, "declining": 0.92}


def _usage_multiplier(logins: int) -> float:
    """Hazard multiplier from monthly logins: collapsing usage -> big risk."""
    if logins < 5:
        return 3.2
    if logins < 15:
        return 1.8
    if logins < 30:
        return 1.0
    return 0.45


def _months_between(start: date, end: date) -> int:
    """Full calendar months from ``start`` to ``end`` (>= 1 by construction)."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    return max(1, months)


def generate_saas_churn(rng: random.Random) -> tuple[list[str], list[list[str]]]:
    """Simulate month-by-month subscriptions; hazard depends on plan + usage."""
    header = [
        "customer_id", "signup_date", "plan", "monthly_price", "region",
        "months_active", "logins_last_30d", "tickets_raised", "is_churned",
    ]
    span_days = (_SAAS_SIGNUP_END - _SAAS_SIGNUP_START).days
    plans = list(_SAAS_PLAN_WEIGHTS)
    regions = list(_SAAS_REGION_WEIGHTS)
    rows: list[list[str]] = []
    for i in range(1, _SAAS_ROWS + 1):
        # Skew signups toward recent months (the business is growing).
        u = rng.random() ** 0.6
        signup = _SAAS_SIGNUP_START + timedelta(days=int(u * span_days))
        plan = rng.choices(plans, weights=list(_SAAS_PLAN_WEIGHTS.values()))[0]
        region = rng.choices(regions, weights=list(_SAAS_REGION_WEIGHTS.values()))[0]
        mean, sd, lo, hi = _SAAS_PLAN_PRICE[plan]
        price = round(min(hi, max(lo, rng.gauss(mean, sd))), 2)
        usage_class = rng.choices(
            list(_SAAS_USAGE_WEIGHTS), weights=list(_SAAS_USAGE_WEIGHTS.values())
        )[0]
        tenure_pool = _months_between(signup, _SAAS_CUTOFF)

        base = _SAAS_USAGE_BASE[usage_class]
        decay = _SAAS_USAGE_DECAY[usage_class]
        churned = False
        months_active = tenure_pool
        last_logins = 0
        for month in range(1, tenure_pool + 1):
            level = (base * (decay ** (month - 1))) + rng.gauss(0, 3)
            logins_this = max(0, int(round(level)))
            hazard = (
                _SAAS_PLAN_HAZARD[plan]
                * _usage_multiplier(logins_this)
                * (1.9 if month <= 2 else 1.0)  # onboarding drop-off spike
            )
            if rng.random() < hazard:
                churned = True
                months_active = month
                # Usage collapses before the cancellation lands.
                last_logins = max(0, int(round(logins_this * 0.6)))
                break
            last_logins = logins_this

        if churned:
            tickets = max(0, min(14, int(round(rng.gauss(2.4, 1.6)))))
        else:
            tickets = max(0, min(14, int(round(rng.gauss(0.9, 1.0)))))

        rows.append([
            f"CUST-{i:05d}", signup.isoformat(), plan, f"{price:.2f}", region,
            str(months_active), str(last_logins), str(tickets),
            "1" if churned else "0",
        ])
    return header, rows


# ---------------------------------------------------------------------------
# 2. ecommerce_sales.csv — 5,000 orders across 12 months
# ---------------------------------------------------------------------------

_ECOM_ROWS = 5000
_ECOM_START = date(2025, 10, 1)
_ECOM_DAYS = 365  # 2025-10-01 .. 2026-09-30
# Monthly demand weights: Q4 holiday spike (Nov/Dec), softer Q1.
_ECOM_MONTH_WEIGHTS = {
    (2025, 10): 1.00, (2025, 11): 1.60, (2025, 12): 2.20,
    (2026, 1): 0.90, (2026, 2): 0.85, (2026, 3): 1.00, (2026, 4): 0.95,
    (2026, 5): 1.05, (2026, 6): 1.00, (2026, 7): 1.10, (2026, 8): 1.05,
    (2026, 9): 1.10,
}
# Base category mix; "books" share decays linearly across the year.
_ECOM_CATEGORY_WEIGHTS = {
    "electronics": 24, "apparel": 26, "home_kitchen": 18,
    "beauty": 14, "sports": 10, "books": 8,
}
_ECOM_BOOKS_DECAY = 0.55  # books weight falls to 45% of base by year end
# price = (mean, sd, lo, hi); returns = baseline return probability.
_ECOM_CATEGORY = {
    "electronics": {"price": (180.0, 60.0, 25.0, 900.0), "returns": 0.07,
        "products": ["Wireless Earbuds X2", "Smart Watch S9", "4K Action Camera",
                      "Bluetooth Speaker Pro", "USB-C Hub 7-in-1", "Noise-Cancel Headphones"]},
    "apparel": {"price": (45.0, 15.0, 9.99, 150.0), "returns": 0.12,
        "products": ["Classic Denim Jacket", "Merino Wool Sweater", "DryFit Running Tee",
                      "Slim Chino Trousers", "Rain Shell Jacket", "Graphic Cotton Tee"]},
    "home_kitchen": {"price": (65.0, 25.0, 12.99, 400.0), "returns": 0.06,
        "products": ["Cast Iron Skillet 12in", "Ceramic Mug Set (4)", "Robot Vacuum R5",
                      "Stainless Knife Block", "Linen Throw Pillow", "Espresso Machine E2"]},
    "beauty": {"price": (28.0, 10.0, 5.99, 120.0), "returns": 0.05,
        "products": ["Vitamin C Serum 30ml", "Hydrating Day Cream", "Matte Lipstick Trio",
                      "Argan Hair Oil", "Charcoal Face Mask", "Bamboo Toothbrush Set"]},
    "sports": {"price": (75.0, 30.0, 14.99, 500.0), "returns": 0.07,
        "products": ["Yoga Mat Pro 6mm", "Adjustable Dumbbell 24kg", "Trail Running Shoes",
                      "Aero Cycling Helmet", "Resistance Band Set", "2P Camping Tent"]},
    "books": {"price": (18.0, 6.0, 4.99, 60.0), "returns": 0.03,
        "products": ["The Lean Startup", "Thinking, Fast and Slow", "Atomic Habits",
                      "The Pragmatic Programmer", "Sapiens", "Deep Work"]},
}
# Mobile share grows ~30% -> ~50% across the year; web declines; marketplace flat.
_ECOM_CHANNELS = ("web", "mobile", "marketplace")


def _ecom_channel_shares(t: float) -> tuple[float, float, float]:
    mobile = 0.30 + 0.20 * t
    web = 0.48 - 0.18 * t
    marketplace = 0.22
    return web, mobile, marketplace


def _ecom_quantity(rng: random.Random) -> int:
    return rng.choices([1, 2, 3, 4, 5], weights=[55, 22, 12, 7, 4])[0]


def generate_ecommerce_sales(rng: random.Random) -> tuple[list[str], list[list[str]]]:
    """Orders with Q4 spike, growing mobile share, declining books, ~8% returns."""
    header = [
        "order_id", "order_date", "product_category", "product_name", "region",
        "channel", "quantity", "unit_price", "revenue", "is_returned",
    ]
    # Bucket days by month weight, then pick a uniform day inside the month.
    month_days: list[tuple[float, list[date]]] = []
    day = _ECOM_START
    buckets: dict[tuple[int, int], list[date]] = {}
    for _ in range(_ECOM_DAYS):
        buckets.setdefault((day.year, day.month), []).append(day)
        day += timedelta(days=1)
    for (year, month), days in buckets.items():
        weight = _ECOM_MONTH_WEIGHTS.get((year, month), 1.0)
        month_days.append((weight * len(days), days))

    regions = ["north_america", "europe", "apac", "latam"]
    raw_rows: list[list[str]] = []
    for _ in range(_ECOM_ROWS):
        total_weight = sum(w for w, _ in month_days)
        pick = rng.uniform(0, total_weight)
        cumulative = 0.0
        chosen_days = month_days[-1][1]
        for weight, days in month_days:
            cumulative += weight
            if pick <= cumulative:
                chosen_days = days
                break
        order_date = rng.choice(chosen_days)
        t = (order_date - _ECOM_START).days / (_ECOM_DAYS - 1)

        weights = dict(_ECOM_CATEGORY_WEIGHTS)
        weights["books"] = weights["books"] * (1.0 - _ECOM_BOOKS_DECAY * t)
        category = rng.choices(list(weights), weights=list(weights.values()))[0]
        info = _ECOM_CATEGORY[category]
        product = rng.choice(info["products"])

        web, mobile, marketplace = _ecom_channel_shares(t)
        channel = rng.choices(_ECOM_CHANNELS, weights=[web, mobile, marketplace])[0]
        region = rng.choices(regions, weights=[42, 28, 18, 12])[0]

        quantity = _ecom_quantity(rng)
        mean, sd, lo, hi = info["price"]
        unit_price = round(min(hi, max(lo, rng.gauss(mean, sd))), 2)
        revenue = round(quantity * unit_price, 2)
        returned = 1 if rng.random() < info["returns"] else 0

        raw_rows.append([
            order_date.isoformat(), category, product, region, channel,
            str(quantity), f"{unit_price:.2f}", f"{revenue:.2f}", str(returned),
        ])

    # Chronological order with sequential ids reads like a real order log.
    raw_rows.sort(key=lambda row: row[0])
    rows = [[f"ORD-{100001 + index}", *row] for index, row in enumerate(raw_rows)]
    return header, rows


# ---------------------------------------------------------------------------
# 3. support_tickets.csv — 1,500 tickets across 12 months
# ---------------------------------------------------------------------------

_SUPPORT_ROWS = 1500
_SUPPORT_START = date(2025, 10, 1)
_SUPPORT_DAYS = 365
_SUPPORT_CUTOFF = date(2026, 9, 30)
# Volume mix: billing + login_bug dominate (55% combined).
_SUPPORT_CATEGORY_WEIGHTS = {
    "billing": 30, "login_bug": 25, "how_to": 18, "feature_request": 15, "integration": 12,
}
_SUPPORT_PRIORITIES = ("low", "medium", "high", "urgent")
_SUPPORT_PRIORITY_WEIGHTS = {
    "billing": (20, 45, 25, 10),
    "login_bug": (10, 30, 40, 20),
    "how_to": (50, 35, 12, 3),
    "feature_request": (45, 35, 15, 5),
    "integration": (5, 25, 45, 25),
}
# Baseline resolution hours; integration lands ~3x the volume-weighted average.
_SUPPORT_RESOLUTION_BASE = {
    "billing": 10.0, "login_bug": 14.0, "how_to": 4.0,
    "feature_request": 45.0, "integration": 45.0,
}
_SUPPORT_RESPONSE_BASE = {"urgent": 0.5, "high": 1.5, "medium": 6.0, "low": 20.0}
_SUPPORT_RESOLUTION_PRIORITY = {"urgent": 0.5, "high": 0.75, "medium": 1.0, "low": 1.4}
_SUPPORT_CSAT_ADJ = {
    "billing": -0.4, "login_bug": -0.2, "how_to": 0.4,
    "feature_request": 0.0, "integration": -0.1,
}

_SUPPORT_SUBJECTS: dict[str, list[str]] = {
    "billing": [
        "Double charged on invoice #{n}",
        "Refund for order #{n} not received",
        "Update credit card details fails",
        "Invoice VAT number is incorrect",
        "Downgrade not applied to my bill",
        "Pricing tier discrepancy on renewal",
        "Failed payment — card declined but subscription active",
        "Requesting annual plan discount",
        "Unexpected overage charges this month",
        "Cancel subscription and refund prorated amount",
        "Charged after cancellation on {date}",
        "Invoice PDF download broken",
    ],
    "login_bug": [
        "Cannot reset password — email never arrives",
        "SSO redirect loop after password change",
        "Account locked after 2FA attempts",
        "Session expires every few minutes",
        "403 error on login from new device",
        "Magic link opens a blank page",
        "Google sign-in fails with 500 error",
        "Password reset link expires immediately",
        "Two-factor codes rejected on mobile",
        "Cannot log in after workspace merge",
        "Login page infinite loading spinner",
    ],
    "feature_request": [
        "Add CSV export for dashboards",
        "Dark mode support",
        "Slack notifications for failed jobs",
        "Bulk edit for user roles",
        "API rate limit increase request",
        "Custom fields in reports",
        "SAML support for enterprise plan",
        "Calendar sync for deadlines",
        "Audit log retention longer than 90 days",
        "Webhook signing secret rotation UI",
    ],
    "integration": [
        "Salesforce sync drops contact records",
        "Zapier webhook returns 401",
        "Shopify order import fails nightly",
        "Slack integration not posting alerts",
        "Webhook retries create duplicate events",
        "OAuth token refresh fails silently",
        "API returns CORS errors from dashboard",
        "Jira two-way sync has stalled",
        "HubSpot mapping ignores custom fields",
        "Stripe webhook signature mismatch",
    ],
    "how_to": [
        "How do I invite teammates?",
        "Where can I find audit logs?",
        "How to set up usage alerts?",
        "Reset dashboard filters to default",
        "How to change the account email?",
        "Export data to Excel",
        "How do usage-based charges work?",
        "Set up two-factor authentication",
        "How to archive old projects?",
        "Where do I manage API keys?",
    ],
}


def _support_subject(rng: random.Random, category: str) -> str:
    template = rng.choice(_SUPPORT_SUBJECTS[category])
    return template.format(
        n=rng.randint(1000, 99999),
        date=(date(2025, 10, 1) + timedelta(days=rng.randint(0, 364))).isoformat(),
    )


def _support_era_factor(created: date) -> float:
    """First-response staffing got worse over time: recent months respond ~1.8x slower."""
    if created >= date(2026, 4, 1):
        return 1.8
    if created >= date(2026, 1, 1):
        return 1.2
    return 1.0


def generate_support_tickets(rng: random.Random) -> tuple[list[str], list[list[str]]]:
    """Tickets with realistic mix, slow integrations, worsening response times."""
    header = [
        "ticket_id", "created_date", "category", "priority", "subject",
        "first_response_hours", "resolution_hours", "is_resolved", "csat",
    ]
    categories = list(_SUPPORT_CATEGORY_WEIGHTS)
    rows: list[list[str]] = []
    for i in range(1, _SUPPORT_ROWS + 1):
        # Slight volume growth over the year (business is scaling).
        skew = rng.random() ** 0.85
        created = _SUPPORT_START + timedelta(days=int(skew * (_SUPPORT_DAYS - 1)))
        category = rng.choices(
            categories, weights=list(_SUPPORT_CATEGORY_WEIGHTS.values())
        )[0]
        priority = rng.choices(
            list(_SUPPORT_PRIORITIES), weights=list(_SUPPORT_PRIORITY_WEIGHTS[category])
        )[0]
        subject = _support_subject(rng, category)

        response = (
            _SUPPORT_RESPONSE_BASE[priority]
            * _support_era_factor(created)
            * _lognoise(rng, 0.45)
        )
        response = max(0.1, round(response, 1))

        resolution = (
            _SUPPORT_RESOLUTION_BASE[category]
            * _SUPPORT_RESOLUTION_PRIORITY[priority]
            * _lognoise(rng, 0.40)
        )
        resolution = max(0.2, round(resolution, 1))

        age_days = (_SUPPORT_CUTOFF - created).days
        resolve_prob = 0.97 if age_days > 45 else (0.90 if age_days > 14 else 0.55)
        if category == "feature_request":
            resolve_prob *= 0.75
        if priority == "low":
            resolve_prob *= 0.90
        resolved = rng.random() < min(resolve_prob, 0.99)

        csat = ""
        if resolved:
            score = (
                4.3
                - min(1.0, resolution / 48.0 * 0.8)  # slow resolution -> lower CSAT
                - (0.3 if priority == "urgent" else 0.0)
                + _SUPPORT_CSAT_ADJ[category]
                + rng.gauss(0, 0.6)
            )
            csat = str(max(1, min(5, int(round(score)))))

        rows.append([
            f"TKT-{i:05d}", created.isoformat(), category, priority, subject,
            f"{response:.1f}", f"{resolution:.1f}", "1" if resolved else "0", csat,
        ])
    rows.sort(key=lambda row: row[1])
    return header, rows


# ---------------------------------------------------------------------------
# 4. marketing_spend.csv — 800 weekly rows (5 channels x 160 weeks)
# ---------------------------------------------------------------------------

_MARKETING_WEEKS = 160
_MARKETING_LAST_WEEK = date(2026, 9, 28)  # Monday
_MARKETING_CHANNELS = ("content", "email", "referral", "search", "social")
_MARKETING_CPM = {"search": 12.0, "social": 8.0, "email": 5.0, "content": 6.0, "referral": 10.0}
_MARKETING_CTR = {"search": 0.035, "social": 0.009, "email": 0.045, "content": 0.025, "referral": 0.030}
_MARKETING_SIGNUP_RATE = {"search": 0.13, "social": 0.03, "email": 0.11, "content": 0.05, "referral": 0.09}
_MARKETING_CONV_RATE = {"search": 0.27, "social": 0.18, "email": 0.30, "content": 0.22, "referral": 0.25}
_MARKETING_SPEND0 = {"search": 1200.0, "social": 900.0, "email": 400.0, "content": 250.0, "referral": 300.0}
_MARKETING_GROWTH = {"search": 0.0035, "social": 0.004, "email": 0.002, "content": 0.006, "referral": 0.0025}
_MARKETING_Q4_BUMP = {"search": 1.25, "social": 1.35, "email": 1.10, "content": 1.05, "referral": 1.10}


def _lognoise(rng: random.Random, sigma: float) -> float:
    """Multiplicative lognormal-ish noise centred on 1.0."""
    return max(0.05, math.exp(rng.gauss(0.0, sigma)))


def generate_marketing_spend(rng: random.Random) -> tuple[list[str], list[list[str]]]:
    """Weekly channel performance; efficiency differs per channel, content compounds."""
    header = [
        "week_start_date", "channel", "spend", "impressions", "clicks",
        "signups", "conversions",
    ]
    rows: list[list[str]] = []
    for week_index in range(_MARKETING_WEEKS):
        week_start = _MARKETING_LAST_WEEK - timedelta(weeks=_MARKETING_WEEKS - 1 - week_index)
        is_q4 = week_start.month in (11, 12)
        for channel in _MARKETING_CHANNELS:
            base_spend = _MARKETING_SPEND0[channel] * ((1.0 + _MARKETING_GROWTH[channel]) ** week_index)
            if is_q4:
                base_spend *= _MARKETING_Q4_BUMP[channel]
            spend = base_spend * _lognoise(rng, 0.10)
            spend = max(50.0, round(spend, 2))

            impressions = int(max(0, spend / _MARKETING_CPM[channel] * 1000.0 * _lognoise(rng, 0.12)))
            clicks = int(max(0, min(impressions, impressions * _MARKETING_CTR[channel] * _lognoise(rng, 0.15))))
            signup_rate = _MARKETING_SIGNUP_RATE[channel]
            if channel == "content":
                # Compounding: content authority builds over time.
                signup_rate = signup_rate * (1.0 + 0.005 * week_index)
            signups = int(max(0, min(clicks, clicks * signup_rate * _lognoise(rng, 0.15))))
            conversions = int(
                max(0, min(signups, signups * _MARKETING_CONV_RATE[channel] * _lognoise(rng, 0.12)))
            )

            rows.append([
                week_start.isoformat(), channel, f"{spend:.2f}",
                str(impressions), str(clicks), str(signups), str(conversions),
            ])
    return header, rows


# ---------------------------------------------------------------------------
# Writer + CLI
# ---------------------------------------------------------------------------

_GENERATORS: dict[str, Callable[[random.Random], tuple[list[str], list[list[str]]]]] = {
    "saas_churn": generate_saas_churn,
    "ecommerce_sales": generate_ecommerce_sales,
    "support_tickets": generate_support_tickets,
    "marketing_spend": generate_marketing_spend,
}

#: Independent per-dataset seed offsets so tweaking one dataset's generator
#: never shifts another dataset's random stream.
_SEED_OFFSETS = {
    "saas_churn": 0,
    "ecommerce_sales": 10_000,
    "support_tickets": 20_000,
    "marketing_spend": 30_000,
}


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def generate_all(seed: int, out_dir: Path) -> dict[str, int]:
    """Generate all four CSVs; returns {dataset: row_count} for verification."""
    out_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for sample_id, generator in _GENERATORS.items():
        rng = random.Random(seed + _SEED_OFFSETS[sample_id])
        header, rows = generator(rng)
        target = out_dir / f"{sample_id}.csv"
        _write_csv(target, header, rows)
        counts[sample_id] = len(rows)
        print(f"wrote {target} ({len(rows)} data rows, {len(header)} columns)")
    return counts


def _summarize(out_dir: Path) -> None:
    """Print the headline story numbers so a human can eyeball the datasets."""
    def column(path: Path, name: str) -> list[str]:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            return [row[name] for row in reader]

    saas = out_dir / "saas_churn.csv"
    churned = [int(v) for v in column(saas, "is_churned")]
    print(f"  saas_churn: overall churn {sum(churned) / len(churned):.1%}")
    for plan in ("basic", "pro", "enterprise"):
        with saas.open(encoding="utf-8", newline="") as handle:
            plan_rows = [row for row in csv.DictReader(handle) if row["plan"] == plan]
        rate = sum(int(r["is_churned"]) for r in plan_rows) / len(plan_rows)
        print(f"    {plan}: churn {rate:.1%} (n={len(plan_rows)})")

    ecom = out_dir / "ecommerce_sales.csv"
    with ecom.open(encoding="utf-8", newline="") as handle:
        ecom_rows = list(csv.DictReader(handle))
    returned = sum(int(r["is_returned"]) for r in ecom_rows)
    print(f"  ecommerce_sales: return rate {returned / len(ecom_rows):.1%}")
    q4 = sum(
        float(r["revenue"]) for r in ecom_rows
        if r["order_date"][5:7] in ("11", "12")  # Q4 months in the 12-month window
    )
    total = sum(float(r["revenue"]) for r in ecom_rows)
    print(f"    Nov+Dec revenue share: {q4 / total:.1%}")

    support = out_dir / "support_tickets.csv"
    with support.open(encoding="utf-8", newline="") as handle:
        support_rows = list(csv.DictReader(handle))
    integration = [float(r["resolution_hours"]) for r in support_rows if r["category"] == "integration"]
    others = [float(r["resolution_hours"]) for r in support_rows if r["category"] != "integration"]
    integration.sort()
    others.sort()
    med_i = integration[len(integration) // 2]
    med_o = others[len(others) // 2]
    print(f"  support_tickets: integration median resolution {med_i:.1f}h vs others {med_o:.1f}h ({med_i / med_o:.1f}x)")

    marketing = out_dir / "marketing_spend.csv"
    with marketing.open(encoding="utf-8", newline="") as handle:
        mkt_rows = list(csv.DictReader(handle))
    for channel in sorted({r["channel"] for r in mkt_rows}):
        ch_rows = [r for r in mkt_rows if r["channel"] == channel]
        spend = sum(float(r["spend"]) for r in ch_rows)
        signups = sum(int(r["signups"]) for r in ch_rows)
        print(f"    {channel}: {signups / spend:.3f} signups per $ (n={len(ch_rows)})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="master RNG seed (default 20261005)")
    parser.add_argument(
        "--out-dir", type=Path, default=DEFAULT_OUT_DIR,
        help="output directory (default: <repo>/data/samples)",
    )
    args = parser.parse_args(argv)
    counts = generate_all(args.seed, args.out_dir)
    expected = {"saas_churn": 2000, "ecommerce_sales": 5000, "support_tickets": 1500, "marketing_spend": 800}
    mismatched = {k: (v, expected[k]) for k, v in counts.items() if v != expected[k]}
    if mismatched:
        raise SystemExit(f"Row-count verification failed: {mismatched}")
    print("row counts verified: 2000 / 5000 / 1500 / 800")
    print("story summary:")
    _summarize(args.out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
