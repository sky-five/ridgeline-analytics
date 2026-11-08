"""The simulated business comes from the saas-world-sim package, pinned to a tag in requirements.txt.

Everything in this repo imports the engine through this module, so the pin and the cache folder are set
in one place. The full seeded history is cached as parquet in .cache/ at the repo root (as before the
engine moved out), whatever folder a command runs from.
"""
import os
from pathlib import Path

ENGINE_TAG = "v0.4.0"  # keep in step with the saas-world-sim line in requirements.txt
os.environ.setdefault("SAAS_WORLD_SIM_CACHE", str(Path(__file__).resolve().parent.parent / ".cache"))

from saas_world_sim import TABLES, MockApi, __version__, world_as_of  # noqa: E402

__all__ = ["ENGINE_TAG", "TABLES", "MockApi", "__version__", "world_as_of"]
