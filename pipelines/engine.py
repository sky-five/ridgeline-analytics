"""The simulated business comes from the saas-world-sim package, pinned to a tag in requirements.txt.

Everything in this repo imports the engine through this module, so the pin and the cache folder are set
in one place. The full seeded history is cached as parquet in .cache/ at the repo root (as before the
engine moved out), whatever folder a command runs from.
"""
import os
from pathlib import Path

ENGINE_TAG = "v0.5.0"  # keep in step with the saas-world-sim line in requirements.txt
os.environ.setdefault("SAAS_WORLD_SIM_CACHE", str(Path(__file__).resolve().parent.parent / ".cache"))

from saas_world_sim import TABLES, MockApi, __version__, world_as_of  # noqa: E402
from saas_world_sim.packs import (  # noqa: E402
    BILLING_TABLES,
    SALES_CRM_TABLES,
    billing_as_of,
    build_sales_crm_history,
    sales_crm_as_of,
)
from saas_world_sim.packs.billing import PLANS as BILLING_PLANS  # noqa: E402
from saas_world_sim.packs.billing import add_months, prorate  # noqa: E402

__all__ = [
    "ENGINE_TAG", "TABLES", "MockApi", "__version__", "world_as_of",
    "SALES_CRM_TABLES", "build_sales_crm_history", "sales_crm_as_of",
    "BILLING_TABLES", "BILLING_PLANS", "billing_as_of", "add_months", "prorate",
]
