import base64
import json
import time
import urllib.parse
import urllib.request

import psycopg2
import os


def get(url, auth=False):
    request = urllib.request.Request(url)
    if auth:
        token = base64.b64encode(b"admin:fraud_monitoring").decode()
        request.add_header("Authorization", f"Basic {token}")
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def query(expr):
    response = get("http://prometheus:9090/api/v1/query?" + urllib.parse.urlencode({"query": expr}))
    assert response["status"] == "success", response
    return response["data"]["result"]


def main():
    targets = get("http://prometheus:9090/api/v1/targets")["data"]["activeTargets"]
    assert len(targets) == 3 and all(item["health"] == "up" for item in targets), targets
    before = float(query("fraud_processed_total")[0]["value"][1])
    time.sleep(5)
    after = float(query("fraud_processed_total")[0]["value"][1])
    assert after > before, (before, after)
    with psycopg2.connect(os.environ["DATABASE_URL"]) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*), count(DISTINCT model_version), count(DISTINCT us_state), count(DISTINCT merch) FROM scores")
            rows = cursor.fetchone()
            assert rows[0] > 0 and rows[2] > 1 and rows[3] > 1, rows
    for uid in ["fraud-scoring", "fraud-writer", "fraud-system", "fraud-business"]:
        dashboard = get(f"http://grafana:3000/api/dashboards/uid/{uid}", True)
        assert dashboard["dashboard"]["panels"], uid
    rules = get("http://grafana:3000/api/v1/provisioning/alert-rules", True)
    assert {rule["uid"] for rule in rules} >= {"fraud-high-share", "fraud-stream-stopped"}, rules
    for uid in ["postgres", "prometheus"]:
        health = get(f"http://grafana:3000/api/datasources/uid/{uid}/health", True)
        assert health["status"] == "OK", health
    print(json.dumps({"targets": "3/3 up", "processed_before": before, "processed_after": after,
                      "database_rows": rows[0], "model_versions": rows[1], "dashboards": 4, "alerts": len(rules)}, indent=2))


if __name__ == "__main__":
    main()
