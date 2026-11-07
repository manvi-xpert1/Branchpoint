"""API tests: the MVP acceptance workflow over HTTP, plus validation and errors."""

import json
from pathlib import Path

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
    assert len(client.get(f"/api/systems/{sid}/scenarios").json()) == 7


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


# ---- Monte Carlo ------------------------------------------------------
def test_monte_carlo_on_a_probabilistic_scenario(client, imported):
    flaky = by_name(client, imported["system_id"])["Flaky week (probabilistic)"]
    r = client.post(f"/api/scenarios/{flaky['id']}/montecarlo",
                    json={"runs": 500, "until": 30, "base_seed": 1})
    assert r.status_code == 201, r.text
    mc = r.json()
    agg = mc["aggregates"]
    assert mc["runs"] == 500 and len(mc["downtimes"]) == 500
    assert not mc["deterministic"]
    # db_outage (p=0.3) causes 10 downtime, users_crash (p=0.2) causes 4.
    assert set(mc["downtimes"]) <= {0, 4, 10, 14}
    assert agg["downtime_max"] <= 14
    assert agg["event_frequency"]["db_outage"] == pytest.approx(0.3, abs=0.07)
    # P(any downtime) = 1 - 0.7 * 0.8 = 0.44
    assert agg["p_any_downtime"] == pytest.approx(0.44, abs=0.07)

    # Stored and listed, newest first, and fetchable by id.
    listed = client.get(f"/api/scenarios/{flaky['id']}/montecarlo").json()
    assert [m["id"] for m in listed] == [mc["id"]]
    fetched = client.get(f"/api/montecarlo/{mc['id']}").json()
    # created_at can differ in timezone formatting on SQLite, so compare the rest.
    assert {k: v for k, v in fetched.items() if k != "created_at"} == \
        {k: v for k, v in mc.items() if k != "created_at"}


def test_monte_carlo_is_reproducible_by_base_seed(client, imported):
    flaky = by_name(client, imported["system_id"])["Flaky week (probabilistic)"]
    body = {"runs": 100, "base_seed": 9}
    a = client.post(f"/api/scenarios/{flaky['id']}/montecarlo", json=body).json()
    b = client.post(f"/api/scenarios/{flaky['id']}/montecarlo", json=body).json()
    assert a["aggregates"] == b["aggregates"] and a["downtimes"] == b["downtimes"]


def test_monte_carlo_on_a_deterministic_scenario(client, imported):
    db_down = by_name(client, imported["system_id"])["DB fails, no intervention"]
    mc = client.post(f"/api/scenarios/{db_down['id']}/montecarlo", json={"runs": 10}).json()
    assert mc["deterministic"] and mc["base_seed"] == db_down["seed"]
    assert mc["aggregates"]["downtime_p95"] == mc["aggregates"]["downtime_mean"] == 10


def test_monte_carlo_validation_and_errors(client, imported):
    sid = by_name(client, imported["system_id"])["Baseline (no incidents)"]["id"]
    assert client.post(f"/api/scenarios/{sid}/montecarlo", json={"runs": 0}).status_code == 422
    assert client.post(f"/api/scenarios/{sid}/montecarlo", json={"runs": 10_001}).status_code == 422
    assert client.post("/api/scenarios/missing/montecarlo", json={"runs": 5}).status_code == 404
    assert client.get("/api/montecarlo/missing").status_code == 404


def test_deleting_a_system_removes_its_monte_carlo_runs(client, imported):
    flaky = by_name(client, imported["system_id"])["Flaky week (probabilistic)"]
    mc = client.post(f"/api/scenarios/{flaky['id']}/montecarlo", json={"runs": 5}).json()
    assert client.delete(f"/api/systems/{imported['system_id']}").status_code == 204
    assert client.get(f"/api/montecarlo/{mc['id']}").status_code == 404


# ---- Phase 2: domains and free-form data -----------------------------------------
def test_domains_endpoint_serves_the_catalog(client):
    domains = client.get("/api/domains").json()
    infra = next(d for d in domains if d["name"] == "software_infrastructure")
    assert {m["key"] for m in infra["metrics"]} >= {"availability", "downtime", "cost"}
    assert next(m for m in infra["metrics"] if m["key"] == "availability")["better"] == "higher"
    assert infra["assumptions"]
    assert client.get("/api/domains/software_infrastructure").json()["label"] == "Software infrastructure"
    assert client.get("/api/domains/weather").status_code == 404


def test_parameters_and_relationship_attributes_are_saved(client):
    body = {
        "name": "Params", "parameters": {"traffic_multiplier": 2},
        "components": [{"id": "a", "entry_point": True}, {"id": "b"}],
        "dependencies": [{"source_id": "a", "target_id": "b", "attributes": {"note": "x"}}],
    }
    sid = client.post("/api/systems", json=body).json()["id"]
    saved = client.get(f"/api/systems/{sid}").json()
    assert saved["parameters"] == {"traffic_multiplier": 2}
    assert saved["dependencies"][0]["attributes"] == {"note": "x"}
    exported = client.get(f"/api/systems/{sid}/export").json()
    assert exported["system"]["parameters"] == {"traffic_multiplier": 2}


def test_event_params_are_saved_and_runs_include_series_and_domain(client, imported):
    sid = by_name(client, imported["system_id"])["DB fails, no intervention"]["id"]
    scenario = client.get(f"/api/scenarios/{sid}").json()
    event = {**scenario["events"][0], "params": {"note": "disk full"}}
    body = {k: scenario[k] for k in ("name", "description", "parent_id", "seed", "remove_events", "interventions")}
    r = client.put(f"/api/scenarios/{sid}", json={**body, "events": [event]})
    assert r.status_code == 200, r.text
    assert r.json()["events"][0]["params"] == {"note": "disk full"}
    run = client.post(f"/api/scenarios/{sid}/runs", json={"until": 30}).json()
    assert run["domain"] == "software_infrastructure" and run["series"] == {}


def test_unknown_types_are_rejected_with_422(client):
    r = client.post("/api/systems", json={"name": "x", "components": [{"id": "a"}, {"id": "b"}],
                                          "dependencies": [{"source_id": "a", "target_id": "b",
                                                            "dependency_type": "sometimes"}]})
    assert r.status_code == 422
    r = client.post("/api/systems", json={"name": "x", "domain": "weather"})
    assert r.status_code == 422


# ---- decision layer (Phase 3) -----------------------------------------------
def db_down_branches(imported):
    ids = imported["scenario_ids"]
    return [ids[k] for k in ("db-down", "db-down-cache-fallback", "db-down-replica", "db-down-fast-restore")]


def test_objectives_default_save_and_reset(client, imported):
    sid = imported["system_id"]
    default = client.get(f"/api/systems/{sid}/objectives").json()
    assert default["is_default"] and default["objectives"][0] == {"metric": "downtime", "weight": 3.0,
                                                                  "direction": None}
    model = {"objectives": [{"metric": "downtime", "weight": 2}, {"metric": "cost"}],
             "constraints": [{"metric": "availability", "op": ">=", "value": 0.95}]}
    saved = client.put(f"/api/systems/{sid}/objectives", json=model).json()
    assert not saved["is_default"] and saved["constraints"][0]["value"] == 0.95
    assert client.get(f"/api/systems/{sid}/objectives").json() == saved
    assert client.put(f"/api/systems/{sid}/objectives").json()["is_default"]  # empty body resets


@pytest.mark.parametrize("bad", [
    {"objectives": [{"metric": "happiness"}]},
    {"objectives": [{"metric": "downtime", "weight": 0}]},
    {"objectives": [], "constraints": [{"metric": "downtime", "op": "<=", "value": 1}]},
    {"objectives": [{"metric": "downtime", "weight": -1}]},
])
def test_invalid_objectives_are_rejected(client, imported, bad):
    assert client.put(f"/api/systems/{imported['system_id']}/objectives", json=bad).status_code == 422


def test_evaluate_ranks_the_db_failure_decisions(client, imported):
    """Default objectives: downtime x3, degraded time x1, intervention cost x1 (scores checked by hand)."""
    ids = imported["scenario_ids"]
    ev = client.post(f"/api/systems/{imported['system_id']}/evaluate",
                     json={"scenario_ids": db_down_branches(imported)}).json()
    order = [f["id"] for f in ev["futures"]]
    assert order == [ids["db-down-fast-restore"], ids["db-down-replica"], ids["db-down-cache-fallback"], ids["db-down"]]
    assert [round(f["score"], 3) for f in ev["futures"]] == [0.82, 0.8, 0.767, 0.4]
    assert ev["recommended"] == ids["db-down-fast-restore"]
    assert ev["baseline_id"] == ids["db-down"]  # the scenario the others branch from
    assert ev["skipped_objectives"] == ["mean_latency", "running_cost"]  # no latency or cost data
    by_id = {f["id"]: f for f in ev["futures"]}
    assert not by_id[ids["db-down"]]["pareto"]
    assert by_id[ids["db-down"]]["dominated_by"] == [ids["db-down-fast-restore"]]
    assert by_id[ids["db-down-replica"]]["metrics"]["cost"] == 300
    kinds = {i["kind"] for i in ev["insights"]}
    assert {"recommendation", "tradeoff", "dominated", "opportunity"} <= kinds


def test_a_constraint_changes_the_recommendation_and_unsaved_models_can_be_tried(client, imported):
    ids = imported["scenario_ids"]
    model = {"objectives": [{"metric": "downtime", "weight": 3}, {"metric": "degraded_time"}, {"metric": "cost"}],
             "constraints": [{"metric": "availability", "op": ">=", "value": 0.95}]}
    ev = client.post(f"/api/systems/{imported['system_id']}/evaluate",
                     json={"scenario_ids": db_down_branches(imported), "model": model}).json()
    assert ev["recommended"] == ids["db-down-replica"]  # fast restore only reaches 90%
    restore = next(f for f in ev["futures"] if f["id"] == ids["db-down-fast-restore"])
    assert not restore["feasible"] and restore["constraints"][0]["value"] == 0.9
    # trying a model does not save it
    assert client.get(f"/api/systems/{imported['system_id']}/objectives").json()["is_default"]


def test_evaluate_with_monte_carlo_reports_spread_and_drivers(client, imported):
    ids = imported["scenario_ids"]
    ev = client.post(f"/api/systems/{imported['system_id']}/evaluate",
                     json={"scenario_ids": [ids["baseline"], ids["flaky"]], "runs": 300}).json()
    flaky = next(f for f in ev["futures"] if f["id"] == ids["flaky"])
    assert flaky["stats"]["downtime"]["p95"] == 14 and flaky["risk"]["metric"] == "downtime"
    assert flaky["drivers"][0]["event_id"] == "db_outage"
    assert ev["recommended"] == ids["baseline"]
    assert any(i["kind"] == "risk" for i in ev["insights"])


def test_evaluate_errors(client, imported):
    other = client.post("/api/systems", json=SIMPLE).json()["id"]
    assert client.post(f"/api/systems/{other}/evaluate", json={}).status_code == 422  # no scenarios
    r = client.post(f"/api/systems/{other}/evaluate", json={"scenario_ids": [imported["scenario_ids"]["baseline"]]})
    assert r.status_code == 422 and "another system" in r.json()["detail"]
    assert client.post("/api/systems/nope/evaluate", json={}).status_code == 404


def test_sensitivity_endpoint(client, imported):
    sid = imported["scenario_ids"]["flaky"]
    out = client.post(f"/api/scenarios/{sid}/sensitivity", json={"runs": 100}).json()
    assert out["metric"] == "downtime" and out["runs"] == 100
    swings = [r["swing"] for r in out["rows"]]
    assert swings == sorted(swings, reverse=True) and swings[0] > 0
    assert {r["id"] for r in out["rows"][:2]} <= {"event:db_outage:probability", "attribute:postgres:recovery_time",
                                                  "event:db_outage:duration"}
    assert client.post(f"/api/scenarios/{sid}/sensitivity", json={"metric": "nope"}).status_code == 422


def test_monte_carlo_reports_every_metric(client, imported):
    mc = client.post(f"/api/scenarios/{imported['scenario_ids']['flaky']}/montecarlo", json={"runs": 200}).json()
    assert mc["risk_metric"] == "downtime" and len(mc["risk_values"]) == 200
    assert mc["metric_stats"]["availability"]["mean"] == pytest.approx(mc["aggregates"]["availability_mean"])
    assert mc["drivers"][0]["event_id"] == "db_outage"


def test_objectives_survive_export_and_import(client, imported):
    sid = imported["system_id"]
    model = {"objectives": [{"metric": "cost", "weight": 1}], "constraints": []}
    client.put(f"/api/systems/{sid}/objectives", json=model)
    exported = client.get(f"/api/systems/{sid}/export").json()
    assert exported["objectives"]["objectives"][0]["metric"] == "cost"
    new_id = client.post("/api/experiments/import", json=exported).json()["system_id"]
    assert client.get(f"/api/systems/{new_id}/objectives").json()["objectives"][0]["metric"] == "cost"


# ---- hospital and cold chain through the API (Phases 5-6) -------------------
EXAMPLES = Path(__file__).resolve().parents[3] / "examples"


@pytest.mark.parametrize("name, domain, decisions", [
    ("hospital.json", "hospital", ["surge", "surge-ward-beds", "surge-ed-bays", "surge-icu"]),
    ("coldchain.json", "cold_chain", ["outage", "outage-generator", "outage-lean"]),
])
def test_every_domain_works_end_to_end(client, name, domain, decisions):
    data = json.loads((EXAMPLES / name).read_text())
    imported = client.post("/api/experiments/import", json=data)
    assert imported.status_code == 201, imported.text
    ids = imported.json()["scenario_ids"]
    sid = imported.json()["system_id"]
    assert client.get(f"/api/systems/{sid}").json()["domain"] == domain
    assert not client.get(f"/api/systems/{sid}/objectives").json()["is_default"]  # the example's own

    run = client.post(f"/api/scenarios/{ids[decisions[0]]}/runs", json={"until": data["until"]}).json()
    assert run["domain"] == domain and run["log"] and run["series"]
    assert client.post(f"/api/runs/{run['id']}/replay").json()["identical"]
    status_change = next(e for e in run["log"] if e["kind"] == "status_change")
    assert client.get(f"/api/runs/{run['id']}/explain/{status_change['seq']}").status_code == 200

    ev = client.post(f"/api/systems/{sid}/evaluate", json={
        "scenario_ids": [ids[d] for d in decisions], "until": data["until"]}).json()
    assert ev["domain"] == domain and len(ev["futures"]) == len(decisions)
    assert ev["baseline_id"] == ids[decisions[0]] and ev["insights"]

    cmp = client.post("/api/compare", json={"scenario_ids": [ids[d] for d in decisions], "until": data["until"]})
    assert cmp.status_code == 200
    mc = client.post(f"/api/scenarios/{ids[decisions[0]]}/montecarlo", json={"runs": 5, "until": data["until"]}).json()
    assert mc["aggregates"] is None and mc["domain"] == domain and len(mc["risk_values"]) == 5
    sens = client.post(f"/api/scenarios/{ids[decisions[0]]}/sensitivity", json={"until": data["until"]})
    assert sens.status_code == 200 and sens.json()["rows"]


def test_domain_rules_are_enforced_on_save(client):
    bad = {"name": "x", "domain": "hospital",
           "components": [{"id": "a", "type": "arrivals", "attributes": {"rate": 1}}, {"id": "w", "type": "ward"}],
           "dependencies": [{"source_id": "a", "target_id": "w", "dependency_type": "routes_to",
                             "attributes": {"probability": 2}}]}
    r = client.post("/api/systems", json=bad)
    assert r.status_code == 422 and "between 0 and 1" in r.json()["detail"]
    mixed = {"name": "x", "domain": "cold_chain", "components": [{"id": "db", "type": "database"}]}
    assert client.post("/api/systems", json=mixed).status_code == 422


def test_compare_rejects_mixed_domains(client, imported):
    data = json.loads((EXAMPLES / "hospital.json").read_text())
    h = client.post("/api/experiments/import", json=data).json()
    r = client.post("/api/compare", json={"scenario_ids": [imported["scenario_ids"]["baseline"],
                                                           h["scenario_ids"]["baseline"]], "until": 30})
    assert r.status_code == 422


def test_runs_with_gaps_in_a_time_series_can_be_read(client):
    """Latency has no value while the service is down; the run must still load (regression test)."""
    system = {"name": "lat", "components": [
        {"id": "api", "type": "gateway", "entry_point": True, "attributes": {"latency": 5}},
        {"id": "db", "type": "database", "attributes": {"latency": 10}}],
        "dependencies": [{"source_id": "api", "target_id": "db"}]}
    sid = client.post("/api/systems", json=system).json()["id"]
    scenario = client.post(f"/api/systems/{sid}/scenarios", json={"name": "down", "events": [
        {"id": "f", "type": "component_failure", "target_id": "db", "start_time": 2, "duration": 3}]}).json()
    run = client.post(f"/api/scenarios/{scenario['id']}/runs", json={"until": 10}).json()
    assert [2, None] in run["series"]["latency"]["entry points"]
    assert client.get(f"/api/runs/{run['id']}").status_code == 200


def test_requests_that_would_run_too_many_simulations_are_refused(client, imported, monkeypatch):
    r = client.post(f"/api/systems/{imported['system_id']}/evaluate", json={"runs": 5000})
    assert r.status_code == 422 and "limit per request" in r.json()["detail"]
    from app.services import decisions
    monkeypatch.setattr(decisions, "MAX_SIMULATIONS", 100)
    r = client.post(f"/api/scenarios/{imported['scenario_ids']['flaky']}/sensitivity", json={"runs": 20})
    assert r.status_code == 422 and "limit is" in r.json()["detail"]
