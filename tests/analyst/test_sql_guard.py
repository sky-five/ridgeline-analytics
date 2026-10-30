"""The analyst's SQL guard: only one read-only SELECT ever reaches the warehouse."""
import duckdb
import pytest

from analyst.sql_guard import UnsafeSQL, check_sql, connect, run_sql


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "w.duckdb"
    with duckdb.connect(str(path)) as c:
        c.execute("create table t as select range as i from range(500)")
    return path


@pytest.mark.parametrize("sql", [
    "select 1", "SELECT * FROM t;", "  with a as (select 1 x) select x from a  ",
    "select count(*) from t where i > 3",
])
def test_selects_pass(sql):
    assert check_sql(sql).lower().lstrip().startswith(("select", "with"))


@pytest.mark.parametrize("sql", [
    "", ";", "insert into t values (1)", "delete from t", "drop table t", "update t set i = 0",
    "create table x as select 1", "copy t to 'out.csv'", "attach 'other.duckdb'",
    "select 1; drop table t", "install httpfs", "load httpfs", "set threads = 1",
    "explain select 1", "selec 1",
])
def test_everything_else_is_refused(sql):
    with pytest.raises(UnsafeSQL):
        check_sql(sql)


def test_connection_is_read_only_even_if_the_check_is_bypassed(db):
    con = connect(db)
    with pytest.raises(duckdb.Error):
        con.execute("insert into t values (1)")


def test_session_blocks_files_and_settings(db, tmp_path):
    secret = tmp_path / "secret.csv"
    secret.write_text("a\n1\n")
    con = connect(db)
    with pytest.raises(duckdb.Error):
        run_sql(con, f"select * from read_csv('{secret.as_posix()}')")
    with pytest.raises(duckdb.Error):
        con.execute("SET enable_external_access = true")


def test_rows_are_capped(db):
    res = run_sql(connect(db), "select i from t order by i", max_rows=10)
    assert res.rows == [[i] for i in range(10)] and res.truncated
    assert not run_sql(connect(db), "select i from t where i < 5").truncated


def test_values_are_json_friendly(db):
    res = run_sql(connect(db), "select 1.5::decimal(4,2) d, date '2026-01-02' dt, null n")
    assert res.rows == [[1.5, "2026-01-02", None]]


def test_missing_warehouse_is_a_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="run_all"):
        connect(tmp_path / "nope.duckdb")
