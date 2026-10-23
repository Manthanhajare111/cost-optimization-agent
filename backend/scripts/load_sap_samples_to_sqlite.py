"""Load SAP samples into staging and promote complete worker mappings to canonical data."""

from __future__ import annotations

import argparse

from costopt.integrations.sap.ingestion import ingest_sap_samples
from costopt.observability.logging import configure_logging


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        choices=("all", "fieldglass", "ariba"),
        default="all",
        help="Limit ingestion to one SAP product; defaults to all captured samples.",
    )
    args = parser.parse_args()
    configure_logging()
    print(ingest_sap_samples(args.source).model_dump_json(indent=2))


if __name__ == "__main__":
    main()
