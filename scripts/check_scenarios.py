import base64
import json
import subprocess
import time
import urllib.parse
import urllib.request


def compose(*args):
    return subprocess.check_output(["docker", "compose", *args], text=True).strip()


def get(url, auth=False):
    headers = {}
    if auth:
        headers["Authorization"] = "Basic " + base64.b64encode(b"admin:fraud_monitoring").decode()
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=10) as response:
        return json.load(response)


def prom(expr):
    response = get("http://localhost:9090/api/v1/query?" + urllib.parse.urlencode({"query": expr}))
    return response["data"]["result"]


def wait_for(check, description, timeout=150):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            print("OK:", description, flush=True)
            return
        time.sleep(5)
    raise AssertionError("Timeout: " + description)


def alert_state(name, state):
    groups = get("http://localhost:3000/api/prometheus/grafana/api/v1/rules", True)["data"]["groups"]
    return any(rule.get("name") == name and rule.get("state") == state for group in groups for rule in group["rules"])


def main():
    container = compose("ps", "-q", "scorer")
    before = subprocess.check_output(["docker", "inspect", "--format", "{{.State.StartedAt}}", container], text=True).strip()
    initial = sum(float(item["value"][1]) for item in prom("fraud_model_updates_total"))
    print(compose("run", "--rm", "trainer"), flush=True)
    wait_for(lambda: sum(float(item["value"][1]) for item in prom("fraud_model_updates_total")) > initial, "model update counter increased", 30)
    assert prom("fraud_model_loaded_timestamp_seconds > (time() - 30)")
    after = subprocess.check_output(["docker", "inspect", "--format", "{{.State.StartedAt}}", container], text=True).strip()
    assert compose("ps", "-q", "scorer") == container and before == after
    print("OK: model switched without container restart", flush=True)
    try:
        print(compose("exec", "-T", "generator", "python", "-m", "app.scenario", "fraud"), flush=True)
        wait_for(lambda: alert_state("Высокая доля фрода", "firing"), "high fraud alert firing")
        print(compose("exec", "-T", "generator", "python", "-m", "app.scenario", "normal"), flush=True)
        wait_for(lambda: alert_state("Высокая доля фрода", "inactive"), "high fraud alert recovered")
        print(compose("exec", "-T", "generator", "python", "-m", "app.scenario", "paused"), flush=True)
        wait_for(lambda: alert_state("Поток остановился", "firing"), "stopped stream alert firing", 90)
    finally:
        print(compose("exec", "-T", "generator", "python", "-m", "app.scenario", "normal"), flush=True)
    wait_for(lambda: alert_state("Поток остановился", "inactive"), "stopped stream alert recovered", 60)


if __name__ == "__main__":
    main()
