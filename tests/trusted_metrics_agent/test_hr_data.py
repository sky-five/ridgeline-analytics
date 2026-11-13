"""The synthetic exports: deterministic, ids only, and internally consistent. No warehouse needed."""
from trusted_metrics_agent.hr_data import AS_OF, START, exports


def test_same_rows_every_time():
    a = exports()
    exports.cache_clear()
    b = exports()
    for name, df in a.tables().items():
        assert df.equals(b.tables()[name]), name


def test_no_personal_fields():
    e = exports()
    assert list(e.employees.columns) == ["emp_id", "department", "location", "job_level", "employment_type",
                                         "hire_date"]
    assert e.employees["emp_id"].str.fullmatch(r"emp_\d{4}").all()


def test_field_crews_are_never_remote_and_levels_are_one_to_five():
    emp = exports().employees
    assert not ((emp["department"] == "Field Operations") & (emp["location"] == "Remote")).any()
    assert set(emp["job_level"]) == {1, 2, 3, 4, 5}


def test_leavers_leave_after_they_join_and_within_the_data():
    e = exports()
    t = e.terminations.merge(e.employees, on="emp_id")
    assert (t["term_date"] > t["hire_date"]).all()
    assert t["term_date"].between(START, AS_OF).all()


def test_pay_only_while_employed_and_never_negative():
    e = exports()
    p = e.pay_lines.merge(e.employees, on="emp_id").merge(e.terminations, on="emp_id", how="left")
    assert (p["amount_cents"] >= 0).all()
    assert (p["pay_date"] >= p["hire_date"]).all()
    left = p.dropna(subset=["term_date"])
    assert (left["pay_date"].map(lambda d: d.replace(day=1)) <= left["term_date"]).all()
