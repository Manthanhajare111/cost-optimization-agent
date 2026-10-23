"""Run against an already-started local CostOpt API; exits nonzero on a failed journey."""

from __future__ import annotations

import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = "http://127.0.0.1:8000"


def request(path: str, method: str = "GET", payload: dict | None = None) -> dict | list:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request_headers = {"Content-Type": "application/json"} if body else {}
    request = Request(f"{BASE_URL}{path}", data=body, method=method, headers=request_headers)
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    try:
        health = request("/health")
        assert health["status"] == "ok"

        scenarios = request("/api/v1/scenarios")
        assert scenarios, "No seeded scenarios are available"
        scenario = scenarios[0]

        run = request("/api/v1/scenarios/run", "POST", {"scenario_id": scenario["scenario_id"]})
        assert run["run_id"] and run["recommendation_id"]
        assert run["recommendation"]["scenario_id"] == scenario["scenario_id"]
        assert run["requires_human_review"] is True

        recommendation_id = run["recommendation_id"]
        brief = request(f"/api/v1/recommendations/{recommendation_id}/explain", "POST")
        assert brief["executive_summary"]

        audit = request(f"/api/v1/agent-runs/{run['run_id']}")
        assert len(audit["stages"]) == 10

        catalogue = request("/api/v1/data-governance/source-catalogue")
        assert catalogue["open_gaps"], "The governance catalogue should disclose open gaps"
        print("PASS: health, scenario run, recommendation brief, audit trail, and governance catalogue verified.")
        return 0
    except (AssertionError, HTTPError, URLError, KeyError, TimeoutError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
