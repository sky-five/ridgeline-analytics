from datetime import date

from revrec.billing import AS_OF, add_months, generate, prorate


def test_add_months_clamps_to_month_end():
    assert add_months(date(2025, 1, 31), 1) == date(2025, 2, 28)
    assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert add_months(date(2025, 11, 15), 3) == date(2026, 2, 15)
    assert add_months(date(2025, 3, 10), 12) == date(2026, 3, 10)


def test_prorate_rest_of_period():
    # 10 of 30 days left on a $30 period: $10.
    assert prorate(3_000, date(2025, 4, 21), date(2025, 4, 1), date(2025, 5, 1)) == 1_000
    assert prorate(-3_000, date(2025, 4, 21), date(2025, 4, 1), date(2025, 5, 1)) == -1_000
    # Half a cent rounds away from zero.
    assert prorate(1, date(2025, 1, 2), date(2025, 1, 1), date(2025, 1, 3)) == 1


def test_generate_is_deterministic():
    a, b = generate(seed=3), generate(seed=3)
    assert a.invoice_lines == b.invoice_lines
    assert a.subscription_changes == b.subscription_changes


def test_generated_billing_is_well_formed():
    b = generate()
    kinds = {ln["kind"] for ln in b.invoice_lines}
    assert kinds == {"subscription", "proration", "credit"}
    for ln in b.invoice_lines:
        assert ln["period_start"] < ln["period_end"]
        assert ln["issued_on"] <= AS_OF
        assert ln["issued_on"] <= ln["period_start"]  # billed in advance, never in arrears
        assert (ln["amount_cents"] < 0) == (ln["kind"] == "credit")
    # Annual plans exist, so some revenue is deferred past the as-of date.
    assert any(ln["period_end"] > add_months(AS_OF, 3) for ln in b.invoice_lines)


def test_every_subscription_starts_with_a_new_row_and_ends_at_most_once():
    b = generate()
    by_sub: dict[str, list[dict]] = {}
    for c in b.subscription_changes:
        by_sub.setdefault(c["subscription_id"], []).append(c)
    for rows in by_sub.values():
        assert rows[0]["reason"] == "new"
        zeros = [r for r in rows if r["mrr_cents"] == 0]
        assert len(zeros) <= 1 and (not zeros or zeros[0] is rows[-1])
