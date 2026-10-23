"""Read-only SAP-shaped mock responses for local integration demonstrations."""

from __future__ import annotations

from typing import Literal

from costopt.storage.sqlite import get_connection


MockResource = Literal["suppliers", "workers", "contracts", "purchase_orders", "rate_cards"]

_QUERIES: dict[str, str] = {
    "suppliers": "SELECT supplier_id AS id, name, region, capability FROM suppliers ORDER BY supplier_id",
    "workers": "SELECT resource_id AS id, supplier_id, squad_id, current_location_id, role, skill, availability FROM resources ORDER BY resource_id",
    "contracts": "SELECT contract_id AS id, supplier_id, contract_type, offshore_permitted, data_residency_restriction, customer_approval_required FROM contracts ORDER BY contract_id",
    "purchase_orders": "SELECT po_id AS id, supplier_id, category_id, business_unit, amount, currency, order_date FROM purchase_orders ORDER BY po_id",
    "rate_cards": "SELECT rate_card_id AS id, supplier_id, location_id, role, bill_rate, currency FROM rate_cards ORDER BY rate_card_id",
}


def get_mock_resource(resource: MockResource, offset: int = 0, limit: int = 25) -> dict[str, object]:
    """Return paged, read-only canonical projections with explicit mock provenance."""
    if resource not in _QUERIES:
        raise ValueError(f"Unsupported mock SAP resource: {resource}")
    if offset < 0 or not 1 <= limit <= 100:
        raise ValueError("offset must be non-negative and limit must be between 1 and 100.")
    with get_connection() as connection:
        rows = connection.execute(
            f"{_QUERIES[resource]} LIMIT ? OFFSET ?", (limit + 1, offset)
        ).fetchall()
    has_more = len(rows) > limit
    items = [dict(row) for row in rows[:limit]]
    return {
        "source": "local_mock_adapter",
        "resource": resource,
        "read_only": True,
        "live_sap_connected": False,
        "offset": offset,
        "limit": limit,
        "has_more": has_more,
        "next_offset": offset + limit if has_more else None,
        "items": items,
    }
