"""Read-only governance evidence for the local MVP."""

import json
from typing import Any

from costopt.config import settings


def get_source_catalogue() -> dict[str, Any]:
    """Return the versioned source catalogue without exposing source payloads."""
    catalogue_path = settings.data_dir / "governance" / "source_catalogue.json"
    with catalogue_path.open(encoding="utf-8") as catalogue_file:
        return json.load(catalogue_file)
