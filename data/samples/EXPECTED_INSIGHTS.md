# Expected Insights — Demo Rubric

What a good AgentForge analysis SHOULD find in each sample dataset. Every
number below was measured on the committed CSVs (generated deterministically
with seed 20261005), so the demo output can be checked against reality — no
invented metrics. Analyst/forecaster/critic outputs that hit most of these
points per dataset are on-script.

## saas_churn.csv (2,000 customers)

Facts baked into the data:
- Overall churn rate **24.8%** (496 of 2,000 customers).
- Churn by plan: **basic 37.4%**, **pro 15.5%**, **enterprise 7.6%** — basic
  month-to-month customers churn ~2.4x more than pro and ~4.9x more than
  enterprise.
- Usage is the strongest churn signal: median `logins_last_30d` is **13 for
  churned vs 42 for active** customers; correlation between
  `logins_last_30d` and `is_churned` is **-0.52**.
- **51%** of customers with fewer than 5 logins in their final month churned;
  customers with 30+ logins churn at **1.5%**.
- Churned customers raised ~**2.4x** more support tickets on average (2.5 vs 1.0).

Insights a good run should surface:
1. Churn rate is ~3x higher for basic plans than the blended average; enterprise
   is the stickiest tier.
2. Strong negative relationship between `logins_last_30d` and churn — collapsing
   usage precedes cancellation.
3. Churned customers are disproportionately heavy support users.

Predictions:
- A customer with <5 monthly logins has ~50% churn probability; 30+ logins is
  near-safe (~2%).
- Plan + logins-based scoring should separate churned/active far better than
  chance (basic-plan + low-usage customers are the at-risk core).

Recommendations (ranked):
1. Targeted save-offers for declining-usage pro/basic customers (logins dropping
   below ~15/month triggers an in-app check-in or discount).
2. Onboarding push in the first 2 months (early-tenure hazard is elevated).
3. Move basic month-to-month customers to annual commitments with a discount.

## ecommerce_sales.csv (5,000 orders, 2025-10 to 2026-09)

Facts baked into the data:
- Total revenue **$0.75M** across 5,000 orders; AOV **$149.33**.
- Clear Q4 holiday spike: December revenue **$121k** vs ~$55k typical month;
  **Nov+Dec contribute 27.1%** of annual revenue.
- Channel mix shift: **mobile grows from ~33% to ~44%** of orders between Q4 2025
  and Q3 2026, while web declines; marketplace holds steady.
- **Books decline -62%** (from ~42 to ~16 orders/month); every other category is
  stable or growing.
- Return rate **7.9%** overall — **apparel 12.0%** worst, **books 1.8%** best.

Insights:
1. Q4 (November-December) is the revenue engine — plan inventory and staffing
   around it.
2. Mobile is taking share month over month; web is fading.
3. Books is a structurally declining category.
4. Apparel returns are ~4x the books rate — sizing/quality issue worth auditing.

Predictions:
- Next-quarter revenue should land near the Sep-2026 run rate (~$60-70k/month)
  outside Q4, with a large Q4 spike.
- Mobile will be the majority channel within ~2 quarters at the current trend.

Recommendations:
1. Double down on mobile UX/conversion before the next Q4.
2. Investigate apparel sizing/returns (12% return rate erodes margin).
3. Sunset or reposition the books category; reallocate its shelf to beauty/home.

## support_tickets.csv (1,500 tickets, 2025-10 to 2026-09)

Facts baked into the data:
- Volume mix: **billing 31% + login_bug 25% = 56%** of all tickets; how_to 18%,
  feature_request 15%, integration 11%.
- **Integration tickets take ~3x longer to resolve** than everything else
  (median **32.5h** vs **10.0h** for all other categories combined).
- First-response times **worsened ~43%** in recent months (median 5.3h in the
  first quarter of the window vs **7.6h** in the last three months).
- **11.9%** of tickets are unresolved; CSAT exists **only for resolved tickets**
  (179 deliberate missing values).
- Slow resolution hurts satisfaction: correlation of `resolution_hours` with
  `csat` is **-0.27**; how_to scores best (4.57), billing worst (3.62).

Insights:
1. Billing + login bugs consume over half of support capacity — automation or
   product fixes there free the most agent time.
2. Integration issues are a queue of their own (3x resolution time) and deserve
   a specialist pod.
3. Response SLAs degraded in the last three months — capacity has not kept pace
   with ticket growth.
4. CSAT decays with resolution time; fast categories (how_to) are the happiest.

Predictions:
- At the current trend, median first response next month lands around 7.5-8h
  unless staffing changes.
- A new integration ticket is more likely than not to take >24h to resolve.

Recommendations:
1. Ship self-service billing tools (invoice download, card self-update) to cut
   the largest ticket category.
2. Create a dedicated integrations specialist rotation.
3. Staff up or route low-priority tickets async to restore the <6h response SLA.

## marketing_spend.csv (800 rows, 5 channels x 160 weeks)

Facts baked into the data:
- Efficiency (signups per $): **email 1.011** > **search 0.388** > **content
  0.321** > **referral 0.273** > **social 0.034** — social returns ~30x less
  per dollar than email.
- Conversions per $: **email 0.311** > **search 0.107** > content/referral
  0.067 > **social 0.006** — search + email are the best-ROI paid channels.
- **Content compounds**: its signups-per-dollar rose from **0.242** (first 20
  weeks) to **0.380** (last 20 weeks), overtaking referral.
- Spend strongly predicts signups within every channel (weekly correlation
  0.44-0.84; search 0.66, social 0.64, content 0.84).
- Q4 (Nov/Dec) carries **18.2%** of annual spend — seasonal budget bumps.

Insights:
1. Email and search are the efficient engines; social is underperforming on
   every efficiency metric.
2. Content is the slow-burn channel — efficiency grows monotonically with time
   (compounding authority).
3. Signups scale with spend within each channel, but efficiency differs ~30x
   between the best (email) and worst (social) channel.

Predictions:
- Shifting $100 of weekly social spend to email yields roughly +90 incremental
  signups per week at observed efficiencies.
- Content's efficiency trend implies it becomes the #2 channel by signups/$
  within the next year if the trend holds.

Recommendations:
1. Reallocate most of the social budget to email and search.
2. Keep investing in content — it compounds and is now ahead of referral.
3. Cap social spend at a brand-awareness floor (~current minimum) until its
   conversion tracking improves.
