"""Load SAP-shaped fixtures into staging and promote workers into canonical resources."""

from __future__ import annotations

import argparse

from costopt.integrations.sap.synthetic import ingest_synthetic_sap_data
from costopt.observability.logging import configure_logging


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        choices=("all", "fieldglass", "ariba"),
        default="all",
        help="Limit synthetic fixture loading to one SAP product.",
    )
    args = parser.parse_args()
    configure_logging()
    print(ingest_synthetic_sap_data(args.source).model_dump_json(indent=2))


if __name__ == "__main__":
    main()
