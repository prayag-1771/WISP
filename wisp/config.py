"""Load config/pipeline.yaml (S2.7). Thin helper so scripts share one source of params.

Modules themselves take plain arguments with sensible defaults; the scripts read the
YAML and pass values in. Keeping the loader tiny avoids a config framework the MVP
does not need.
"""

from __future__ import annotations

import os
from typing import Any, Dict

import yaml

_DEFAULT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "pipeline.yaml")


def load(path: str = _DEFAULT_PATH) -> Dict[str, Any]:
    """Return the pipeline config as a nested dict."""
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)
