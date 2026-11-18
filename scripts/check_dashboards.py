import base64
import json
import math
import time
import urllib.request

AUTH = "Basic " + base64.b64encode(b"admin:fraud_monitoring").decode()
BASE = "http://grafana:3000"


def request(path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(BASE + path, data=data, headers={"Authorization": AUTH, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def execute(target, states="'CA','NY','TX','FL','WA'", merchants="'market','travel','electronics','fuel','cafe'"):
    target = dict(target)
    if "rawSql" in target:
        target["rawSql"] = target["rawSql"].replace("${us_state:sqlstring}", states).replace("${merch:sqlstring}", merchants)
    target.update(intervalMs=1000, maxDataPoints=900)
    result = request("/api/ds/query", {"from": str(int((time.time() - 900) * 1000)), "to": str(int(time.time() * 1000)), "queries": [target]})
    query = result["results"]["A"]
    assert not query.get("error"), query
    assert query.get("frames"), query
    return query["frames"]


def has_numeric_data(frames):
    """Require a finite measurement; timestamps and category labels are not data."""
    for frame in frames:
        fields = frame.get("schema", {}).get("fields", [])
        columns = frame.get("data", {}).get("values", [])
        for field, values in zip(fields, columns):
            if field.get("type") != "number":
                continue
            if any(isinstance(value, (int, float)) and not isinstance(value, bool)
                   and math.isfinite(value) for value in values):
                return True
    return False


def main():
    count = 0
    business = None
    for uid in ["fraud-scoring", "fraud-writer", "fraud-system", "fraud-business"]:
        dashboard = request(f"/api/dashboards/uid/{uid}")["dashboard"]
        if uid == "fraud-business":
            business = dashboard
        for panel in dashboard["panels"]:
            frames = execute(panel["targets"][0])
            assert has_numeric_data(frames), f"No numeric data: {uid} / {panel['title']}"
            count += 1
            print("OK", uid, panel["title"])
    for panel in business["panels"]:
        frames = execute(panel["targets"][0], "'CA'", "'market'")
        assert has_numeric_data(frames), f"No numeric data for CA / market: {panel['title']}"
    sample_panel = business["panels"][-1]["targets"][0]
    all_count = execute(sample_panel)[0]["data"]["values"][0][0]
    filtered_count = execute(sample_panel, "'CA'", "'market'")[0]["data"]["values"][0][0]
    assert 0 < filtered_count < all_count, (filtered_count, all_count)
    density = execute(business["panels"][1]["targets"][0], "'CA'", "'market'")[0]["data"]["values"][1]
    assert abs(sum(density) * 0.05 - 1) < 1e-9, density
    print(json.dumps({"panels_checked": count, "all_count": all_count, "filtered_count": filtered_count, "density_area": sum(density) * 0.05}, indent=2))


if __name__ == "__main__":
    main()
