"""API tests: the MVP acceptance workflow over HTTP, plus validation and errors."""

import pytest

SIMPLE = {
    "name": "Tiny",
    "components": [
        {"id": "api", "type": "gateway", "entry_point": True},
        {"id": "db", "type": "database"},
    ],
    "dependencies": [{"source_id": "api", "target_id": "db"}],
}


def by_name(client, system_id):
    return {s["name"]: s for s in client.get(f"/api/systems/{system_id}/scenarios").json()}


# ---- systems ----------------------------------------------------------
def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_system_crud(client):
    r = client.post("/api/systems", json=SIMPLE)
    assert r.status_code == 201
    sys_ = r.json()
    assert sys_["dependencies"][0]["id"] == "api->db"
    assert sys_["components"][0]["name"] == "api"

    assert [s["id"] for s in client.get("/api/systems").json()] == [sys_["id"]]

    updated = {**SIMPLE, "name": "Tiny v2",
               "components": SIMPLE["components"] + [{"id": "cache", "type": "cache"}]}
    r = client.put(f"/api/systems/{sys_['id']}", json=updated)
    assert r.status_code == 200 and len(r.json()["components"]) == 3

    assert client.delete(f"/api/systems/{sys_['id']}").status_code == 204
    assert client.get(f"/api/systems/{sys_['id']}").status_code == 404


def test_component_layout_round_trips(client):
    data = {**SIMPLE, "components": [{**SIMPLE["components"][0], "layout": {"x": 10, "y": 20}},
                                     SIMPLE["components"][1]]}
    sys_ = client.post("/api/systems", json=data).json()
    assert client.get(f"/api/systems/{sys_['id']}").json()["components"][0]["layout"] == {"x": 10, "y": 20}


@pytest.mark.parametrize("bad, fragment", [
    ({**SIMPLE, "dependencies": [{"source_id": "api", "target_id": "ghost"}]}, "ghost"),
    ({**SIMPLE, "dependencies": [{"source_id": "api", "target_id": "api"}]}, "itself"),
    ({**SIMPLE, "components": SIMPLE["components"] * 2}, "Duplicate"),
    ({**SIMPLE, "domain": "astrology"}, "Unknown domain"),
])
def test_invalid_systems_are_rejected_with_reason(client, bad, fragment):
    r = client.post("/api/systems", json=bad)
    assert r.status_code == 422 and fragment in r.json()["detail"]


def test_schema_validation(client):
    r = client.post("/api/systems", json={**SIMPLE, "dependencies": [
        {"source_id": "api", "target_id": "db", "dependency_type": "sometimes"}]})
    assert r.status_code == 422
    r = client.post("/api/systems", json={**SIMPLE, "components": [{"id": "has space"}]})
    assert r.status_code == 422


def test_analysis_reports_cycles_and_blast_radius(client):
    cyclic = {**SIMPLE, "dependencies": SIMPLE["dependencies"] + [{"source_id": "db", "target_id": "api"}]}
    a = client.post("/api/analysis", json=cyclic).json()
    assert a["valid"] and a["cycle"] and a["topological_order"] is None
    assert any("cycle" in w for w in a["warnings"])

    a = client.post("/api/analysis", json=SIMPLE).json()
    assert a["topological_order"] == ["db", "api"]
    assert a["blast_radius"] == {"api": [], "db": ["api"]}

    bad = client.post("/api/analysis", json={**SIMPLE, "dependencies": [{"source_id": "x", "target_id": "db"}]})
    assert bad.status_code == 200 and bad.json()["valid"] is False


# ---- acceptance workflow ----------------------------------------------
def test_mvp_acceptance_workflow(client, imported):
    """Create a system, fail the DB, branch two recoveries, compare."""
    sid = imported["system_id"]
    scen = by_name(client, sid)
    db_down = scen["DB fails, no intervention"]

    run = client.post(f"/api/scenarios/{db_down['id']}/runs", json={"until": 30})
    assert run.status_code == 201
    run = run.json()
    assert run["metrics"]["downtime"] == 10
    assert run["timelines"]["api_gateway"] == [[0, "healthy"], [7, "failed"], [17, "healthy"]]

    # Explain why the gateway failed.
    gw_fail = next(e for e in run["log"] if e["component_id"] == "api_gateway" and e["new_status"] == "failed")
    chain = client.get(f"/api/runs/{run['id']}/explain/{gw_fail['seq']}").json()
    assert [e["component_id"] for e in chain] == ["postgres", "postgres", "user_service", "api_gateway"]
    assert chain[0]["event_id"] == "db_failure"

    # Compare the two recovery branches against doing nothing.
    ids = [db_down["id"], scen["DB fails + cache fallback"]["id"], scen["DB fails + read replica"]["id"]]
    cmp = client.post("/api/compare", json={"scenario_ids": ids, "until": 30}).json()
    downtimes = [r["metrics"]["downtime"] for r in cmp["runs"]]
    assert downtimes == [10, 0, 0]
    replica_run = cmp["runs"][2]["id"]
    assert cmp["best"]["degraded_time"] == [cmp["runs"][0]["id"], replica_run]  # both 0
    assert cmp["best"]["affected_components"] == [replica_run]
    assert cmp["best"]["cost"] == [cmp["runs"][0]["id"]]

    # The run reports the system as simulated, including added components.
    replica_full = client.get(f"/api/runs/{replica_run}").json()
    assert "postgres_replica" in {c["id"] for c in replica_full["system"]["components"]}

    # Runs are stored and listed.
    assert len(client.get(f"/api/scenarios/{db_down['id']}/runs").json()) == 2


def test_compare_existing_runs(client, imported):
    scen = by_name(client, imported["system_id"])
    r1 = client.post(f"/api/scenarios/{scen['Baseline (no incidents)']['id']}/runs").json()
    r2 = client.post(f"/api/scenarios/{scen['DB fails, no intervention']['id']}/runs").json()
    cmp = client.post("/api/compare", json={"run_ids": [r1["id"], r2["id"]]}).json()
    assert cmp["best"]["availability"] == [r1["id"]]
    assert "recovery_time" in cmp["best"] and cmp["best"]["recovery_time"] == [r2["id"]]

    r3 = client.post(f"/api/scenarios/{scen['Baseline (no incidents)']['id']}/runs", json={"until": 60}).json()
    assert client.post("/api/compare", json={"run_ids": [r1["id"], r3["id"]]}).status_code == 422
    assert client.post("/api/compare", json={"run_ids": [], "scenario_ids": []}).status_code == 422


# ---- scenarios --------------------------------------------------------
def test_scenario_inheritance_is_resolved(client, imported):
    scen = by_name(client, imported["system_id"])
    replica = client.get(f"/api/scenarios/{scen['DB fails + read replica']['id']}").json()
    assert [e["id"] for e in replica["resolved_events"]] == ["db_failure"]
    assert replica["events"] == []
    assert len(replica["lineage"]) == 3
    assert replica["seed"] == 42


def test_branch_then_override(client, imported):
    scen = by_name(client, imported["system_id"])
    parent = scen["DB fails, no intervention"]
    child = client.post(f"/api/scenarios/{parent['id']}/branch", json={"name": "Shorter outage"}).json()
    assert child["parent_id"] == parent["id"] and child["resolved_events"][0]["id"] == "db_failure"

    # Override the inherited event by reusing its id.
    body = {"name": "Shorter outage", "parent_id": parent["id"], "events": [
        {"id": "db_failure", "type": "component_failure", "target_id": "postgres",
         "start_time": 5, "duration": 2}]}
    assert client.put(f"/api/scenarios/{child['id']}", json=body).status_code == 200
    run = client.post(f"/api/scenarios/{child['id']}/runs").json()
    assert run["metrics"]["downtime"] == 2


def test_scenario_validation_errors(client, imported):
    sid = imported["system_id"]
    bad_target = {"name": "x", "events": [
        {"id": "e", "type": "component_failure", "target_id": "nope", "start_time": 1}]}
    r = client.post(f"/api/systems/{sid}/scenarios", json=bad_target)
    assert r.status_code == 422 and "nope" in r.json()["detail"]

    dup = {"name": "x", "events": [
        {"id": "e", "type": "component_failure", "target_id": "postgres", "start_time": 1}] * 2}
    assert client.post(f"/api/systems/{sid}/scenarios", json=dup).status_code == 422

    bad_iv = {"name": "x", "interventions": [
        {"id": "i", "type": "remove_dependency", "params": {}}]}
    assert client.post(f"/api/systems/{sid}/scenarios", json=bad_iv).status_code == 422

    bad_remove = {"name": "x", "remove_events": ["not_inherited"]}
    assert client.post(f"/api/systems/{sid}/scenarios", json=bad_remove).status_code == 422

    assert client.post(f"/api/systems/{sid}/scenarios", json={"name": "x", "parent_id": "missing"}).status_code == 404
    # Failed creates leave nothing behind.
    assert len(client.get(f"/api/systems/{sid}/scenarios").json()) == 6


def test_events_can_target_components_added_by_interventions(client, imported):
    scen = by_name(client, imported["system_id"])
    body = {"name": "Replica also fails", "parent_id": scen["DB fails + read replica"]["id"], "events": [
        {"id": "replica_fail", "type": "component_failure", "target_id": "postgres_replica", "start_time": 6}]}
    r = client.post(f"/api/systems/{imported['system_id']}/scenarios", json=body)
    assert r.status_code == 201
    run = client.post(f"/api/scenarios/{r.json()['id']}/runs").json()
    assert run["metrics"]["downtime"] > 0


def test_no_parent_cycles(client, imported):
    scen = by_name(client, imported["system_id"])
    root = scen["Baseline (no incidents)"]
    leaf = scen["DB fails + read replica"]
    r = client.put(f"/api/scenarios/{root['id']}", json={"name": root["name"], "parent_id": leaf["id"]})
    assert r.status_code == 422 and "ancestor" in r.json()["detail"]


def test_cannot_delete_scenario_with_branches(client, imported):
    scen = by_name(client, imported["system_id"])
    assert client.delete(f"/api/scenarios/{scen['DB fails, no intervention']['id']}").status_code == 409
    assert client.delete(f"/api/scenarios/{scen['DB fails + read replica']['id']}").status_code == 204


def test_system_edit_that_breaks_a_scenario_is_refused(client, imported):
    sid = imported["system_id"]
    current = client.get(f"/api/systems/{sid}").json()
    without_pg = {
        "name": current["name"],
        "components": [c for c in current["components"] if c["id"] != "postgres"],
        "dependencies": [d for d in current["dependencies"] if d["target_id"] != "postgres"],
    }
    r = client.put(f"/api/systems/{sid}", json=without_pg)
    assert r.status_code == 422 and "postgres" in r.json()["detail"]
    assert len(client.get(f"/api/systems/{sid}").json()["components"]) == 4  # unchanged


def test_delete_system_removes_scenario_tree(client, imported):
    sid = imported["system_id"]
    scen = by_name(client, sid)
    client.post(f"/api/scenarios/{scen['DB fails, no intervention']['id']}/runs")
    assert client.delete(f"/api/systems/{sid}").status_code == 204
    assert client.get(f"/api/scenarios/{scen['Baseline (no incidents)']['id']}").status_code == 404


# ---- reproducibility --------------------------------------------------
def test_replay_is_identical_even_after_edits(client, imported):
    sid = imported["system_id"]
    scen = by_name(client, sid)
    run = client.post(f"/api/scenarios/{scen['DB fails + cache fallback']['id']}/runs").json()

    # Edit the system after the run: the snapshot must still replay exactly.
    current = client.get(f"/api/systems/{sid}").json()
    for d in current["dependencies"]:
        d["propagation_delay"] = 5
    current = {k: current[k] for k in ("name", "domain", "description", "components", "dependencies")}
    assert client.put(f"/api/systems/{sid}", json=current).status_code == 200

    replay = client.post(f"/api/runs/{run['id']}/replay").json()
    assert replay == {"run_id": run["id"], "identical": True, "differences": []}
    # ...while a fresh run reflects the edit.
    fresh = client.post(f"/api/scenarios/{scen['DB fails + cache fallback']['id']}/runs").json()
    assert fresh["timelines"]["api_gateway"] != run["timelines"]["api_gateway"]


def test_probabilistic_runs_reproduce_by_seed(client):
    sys_ = client.post("/api/systems", json=SIMPLE).json()
    events = [{"id": f"e{i}", "type": "latency_increase", "target_id": "db", "start_time": i,
               "duration": 0.5, "probability": 0.5} for i in range(20)]
    s = client.post(f"/api/systems/{sys_['id']}/scenarios", json={"name": "p", "seed": 7, "events": events}).json()
    a = client.post(f"/api/scenarios/{s['id']}/runs").json()
    b = client.post(f"/api/scenarios/{s['id']}/runs").json()
    assert a["skipped_events"] == b["skipped_events"] and a["metrics"] == b["metrics"]
    assert 0 < len(a["skipped_events"]) < 20


# ---- import / export --------------------------------------------------
def test_export_import_round_trip(client, imported):
    exported = client.get(f"/api/systems/{imported['system_id']}/export").json()
    again = client.post("/api/experiments/import", json=exported)
    assert again.status_code == 201, again.text
    names_a = sorted(by_name(client, imported["system_id"]))
    names_b = sorted(by_name(client, again.json()["system_id"]))
    assert names_a == names_b


def test_failed_import_leaves_nothing(client, example):
    example["scenarios"].append({"id": "broken", "name": "broken", "parent": "baseline", "events": [
        {"id": "x", "type": "component_failure", "target_id": "ghost", "start_time": 1}]})
    assert client.post("/api/experiments/import", json=example).status_code == 422
    assert client.get("/api/systems").json() == []


def test_not_found(client):
    assert client.get("/api/runs/nope").status_code == 404
    assert client.post("/api/scenarios/nope/runs").status_code == 404
