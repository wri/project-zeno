"""The subscriptions migration upgrades and downgrades cleanly, and marks the
existing dashboards that can have email alerts.

The rest of the suite builds its schema with ``create_all``, which never runs
a migration. This test builds the schema the same way in a throwaway
database, minus what this revision adds, stamps it at the previous head and
runs this revision both ways, so it doesn't depend on replaying the whole
history.
"""

import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from src.agent.datasets.handlers.analytics_handler import INTEGRATED_ALERTS_ID
from src.api.data_models import (
    Base,
    DashboardOrm,
    DashboardWidgetOrm,
    InsightChartOrm,
    InsightOrm,
    SubscriptionOrm,
    UserOrm,
)
from src.shared.aoi_search_sql import SEARCH_DDL
from tests.conftest import TEST_DB_URL

REVISION = "b5e2a9c41d07"
PREVIOUS = "f3a8c1d5b204"
DB_DIR = Path(__file__).resolve().parents[2] / "db"


@pytest.fixture
def migration_db_url(monkeypatch):
    base = make_url(TEST_DB_URL).set(drivername="postgresql+psycopg2")
    url = base.set(database=f"migration_{uuid.uuid4().hex[:8]}")
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{url.database}"'))

    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        for statement in SEARCH_DDL:
            conn.execute(text(statement))
        Base.metadata.create_all(
            conn,
            tables=[
                t
                for t in Base.metadata.sorted_tables
                if t.name != SubscriptionOrm.__tablename__
            ],
        )
        conn.execute(
            text(
                "ALTER TABLE dashboards DROP COLUMN eligible_for_subscription"
            )
        )
    engine.dispose()

    # db/alembic/env.py reads the URL from the environment.
    rendered = url.render_as_string(hide_password=False)
    monkeypatch.setenv("DATABASE_URL", rendered)
    yield rendered

    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE "{url.database}" WITH (FORCE)'))
    admin.dispose()


def test_subscriptions_migration_up_and_down(migration_db_url):
    config = Config(str(DB_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(DB_DIR / "alembic"))
    engine = create_engine(migration_db_url)

    command.stamp(config, PREVIOUS)
    command.upgrade(config, REVISION)

    table = inspect(engine)
    assert {c["name"] for c in table.get_columns("subscriptions")} == set(
        SubscriptionOrm.__table__.columns.keys()
    )
    assert [
        u["column_names"]
        for u in table.get_unique_constraints("subscriptions")
    ] == [["dashboard_id", "dataset", "mode"]]
    assert {
        fk["referred_table"]: fk["options"].get("ondelete")
        for fk in table.get_foreign_keys("subscriptions")
    } == {"dashboards": "CASCADE", "dashboard_aois": "CASCADE", "users": None}

    command.downgrade(config, PREVIOUS)
    assert not inspect(engine).has_table("subscriptions")
    assert "eligible_for_subscription" not in {
        c["name"] for c in inspect(engine).get_columns("dashboards")
    }

    command.upgrade(config, REVISION)
    assert inspect(engine).has_table("subscriptions")
    engine.dispose()


def _insert(conn, table, **values):
    return conn.execute(
        table.__table__.insert().values(**values).returning(table.id)
    ).scalar_one()


def _dashboard_with_widget(conn, *, chart_dataset=None, layer_dataset=None):
    dashboard = _insert(conn, DashboardOrm, user_id="owner", name="Area")
    insight = None
    if chart_dataset is not None:
        insight = _insert(conn, InsightOrm, insight_text="Alerts")
        _insert(
            conn,
            InsightChartOrm,
            insight_id=insight,
            title="Alerts",
            chart_type="line",
            chart_data=[],
            dataset_id=chart_dataset,
        )
    config = {}
    if layer_dataset is not None:
        config = {"dataset": {"dataset_id": layer_dataset}}
    _insert(
        conn,
        DashboardWidgetOrm,
        dashboard_id=dashboard,
        widget_type="insight" if insight else "alerts",
        insight_id=insight,
        config=config,
    )
    return dashboard


def test_upgrade_marks_dashboards_with_an_integrated_alerts_widget(
    migration_db_url,
):
    config = Config(str(DB_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(DB_DIR / "alembic"))
    engine = create_engine(migration_db_url)
    with engine.begin() as conn:
        _insert(conn, UserOrm, id="owner", name="owner", email="o@example.com")
        with_chart = _dashboard_with_widget(
            conn, chart_dataset=INTEGRATED_ALERTS_ID
        )
        with_layer = _dashboard_with_widget(
            conn, layer_dataset=INTEGRATED_ALERTS_ID
        )
        other_dataset = _dashboard_with_widget(conn, chart_dataset=1)

    command.stamp(config, PREVIOUS)
    command.upgrade(config, REVISION)

    with engine.connect() as conn:
        eligible = dict(
            conn.execute(
                text("SELECT id, eligible_for_subscription FROM dashboards")
            ).all()
        )
    engine.dispose()
    assert eligible == {
        with_chart: True,
        with_layer: True,
        other_dataset: False,
    }
