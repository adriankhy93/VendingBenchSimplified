import json
from fastapi.testclient import TestClient
import pytest
from viewer.api import create_app
from viewer.store import RunStore


def write_run(root, name="run-a", complete=True):
    path = root / name
    path.mkdir(parents=True)
    (path / "config.json").write_text(
        json.dumps(dict(agent="negotiating", seed=42, scenario_id="smoke-v1"))
    )
    records = [
        dict(
            action="observe",
            payload={},
            response=dict(
                sim_time=dict(day=1, minute_of_day=5),
                result=dict(
                    products=[dict(product_id="p01", name="Water")],
                    slots=[],
                    storage={},
                ),
                metrics=dict(
                    cash_cents=50000,
                    machine_cash_cents=0,
                    fee_debt_cents=0,
                    units_sold=0,
                ),
                events=[],
            ),
        ),
        dict(
            action="end_day",
            payload={},
            response=dict(
                sim_time=dict(day=2, minute_of_day=0),
                result={},
                metrics=dict(
                    cash_cents=49800,
                    machine_cash_cents=500,
                    fee_debt_cents=0,
                    units_sold=5,
                ),
                events=[dict(type="sales", product_id="p01", quantity=5)],
            ),
        ),
    ]
    (path / "actions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
    (path / "memory.md").write_text("<script>window.bad=true</script>")
    if complete:
        (path / "summary.json").write_text(
            json.dumps(
                dict(
                    classification="completed",
                    complete=True,
                    env_id="env_abc",
                    terminal=dict(
                        score=dict(score_cents=50300),
                        simulated_minutes=1440,
                        termination_reason="smoke_day_cap",
                    ),
                    usage=dict(calls=1),
                )
            )
        )
    return path


def test_api_lists_runs_filters_and_pages(tmp_path):
    write_run(tmp_path)
    write_run(tmp_path, "run-b", False)
    (tmp_path / "service").mkdir()
    (tmp_path / "suite.json").write_text("{}")
    with TestClient(create_app(tmp_path)) as c:
        data = c.get("/api/runs?limit=1").json()
        assert data["total"] == 2 and len(data["runs"]) == 1
        assert c.get("/api/runs?classification=completed").json()["total"] == 1
        assert c.get("/api/runs?q=42").json()["total"] == 2
        assert c.get("/api/runs?q=nothing").json()["total"] == 0
        assert c.get("/api/runs?limit=1000").status_code == 422
        assert c.get("/api/runs/missing").status_code == 404
        assert c.post("/api/runs/run-a").status_code == 405


def test_details_chart_sales_and_action_pagination(tmp_path):
    write_run(tmp_path)
    with TestClient(create_app(tmp_path)) as c:
        d = c.get("/api/runs/run-a").json()
        assert d["score"]["score_cents"] == 50300 and d["score_source"] == "terminal"
        assert d["timeline"][-1]["minute"] == 1440
        assert d["sales"] == [dict(product_id="p01", name="Water", quantity=5)]
        assert d["action_total"] == 2 and d["memory"].startswith("<script>")
        assert (
            c.get("/api/runs/run-a/actions?offset=1&limit=1").json()["actions"][0][
                "index"
            ]
            == 2
        )
        assert c.get("/api/runs/run-a/actions?action=observe").json()["total"] == 1
        assert c.get("/").status_code == 200
        assert "Run explorer" in c.get("/").text
        assert (
            c.get("/assets/app.js")
            .headers["content-type"]
            .startswith("text/javascript")
        )
        assert c.get("/assets/secrets").status_code == 404
        assert "script-src 'self'" in c.get("/").headers["content-security-policy"]


def test_partial_logs_and_missing_summary_are_unfinished(tmp_path):
    path = write_run(tmp_path, complete=False)
    with (path / "actions.jsonl").open("a") as f:
        f.write('{"action":')
    (path / "summary.json").write_text("{")
    d = RunStore(tmp_path).detail("run-a")
    assert d["classification"] == "unfinished" and d["score"] == {}
    assert d["action_total"] == 2 and d["simulated_minutes"] == 1440
    assert len(d["warnings"]) == 2


def test_truncated_score_uses_only_trusted_summary(tmp_path):
    path = write_run(tmp_path, complete=False)
    (path / "summary.json").write_text(
        json.dumps(
            dict(
                classification="budget_truncated", env_id="env_abc", reason="max_calls"
            )
        )
    )
    (tmp_path / "service").mkdir()
    (tmp_path / "service" / "env_abc.json").write_text(
        json.dumps(
            dict(
                summary=dict(score=dict(score_cents=49800), complete=False),
                evaluator=dict(secret="hidden"),
            )
        )
    )
    d = RunStore(tmp_path).detail("run-a")
    assert (
        d["classification"] == "budget_truncated"
        and d["score_source"] == "pre_deletion"
    )
    assert d["score"]["score_cents"] == 49800 and "hidden" not in json.dumps(d)


def test_symlinks_and_traversal_do_not_expose_files(tmp_path):
    root = tmp_path / "runs"
    root.mkdir()
    outside = write_run(tmp_path, "outside")
    (root / "link").symlink_to(outside, target_is_directory=True)
    safe = write_run(root, "safe")
    (safe / "memory.md").unlink()
    (safe / "memory.md").symlink_to(outside / "memory.md")
    with TestClient(create_app(root)) as c:
        assert c.get("/api/runs/link").status_code == 404
        assert c.get("/api/runs/..%2Foutside").status_code == 404
        assert c.get("/api/runs/safe").json()["memory"] == ""
        assert c.get("/api/runs").json()["total"] == 1


def test_empty_run_directory(tmp_path):
    with TestClient(create_app(tmp_path / "missing")) as c:
        assert c.get("/api/runs").json()["runs"] == []


def test_live_pi_session_is_listed_and_read_while_growing(tmp_path):
    pi_sessions = tmp_path / "pi-sessions"
    pi_sessions.mkdir()
    session_id = "2026-09-14T09-23-22-743Z_01a09f3a-71f7-70dd-a035-96cfbbf85d1b"
    session = pi_sessions / f"{session_id}.jsonl"
    session.write_text(
        "\n".join(
            json.dumps(record)
            for record in [
                dict(type="session", timestamp="2026-09-14T09:23:22.743Z"),
                dict(type="model_change", modelId="qwen3.5-2b"),
                dict(
                    type="message",
                    message=dict(
                        role="assistant",
                        usage=dict(input=10, output=2),
                        content=[
                            dict(
                                type="toolCall",
                                id="call-1",
                                name="bash",
                                arguments=dict(
                                    command="curl -X POST http://localhost/env/env_abc/observe"
                                ),
                            )
                        ],
                    ),
                ),
                dict(
                    type="message",
                    message=dict(
                        role="toolResult",
                        toolCallId="call-1",
                        content=[
                            dict(
                                type="text",
                                text=json.dumps(
                                    dict(
                                        sim_time=dict(day=1, minute_of_day=5),
                                        metrics=dict(
                                            cash_cents=50000,
                                            machine_cash_cents=0,
                                            fee_debt_cents=0,
                                        ),
                                    )
                                ),
                            )
                        ],
                    ),
                ),
            ]
        )
        + "\n"
    )
    run_id = f"pi-{session_id}"
    with TestClient(create_app(tmp_path)) as c:
        assert c.get("/api/runs").json()["runs"][0]["run_id"] == run_id
        assert c.get(f"/api/runs/{run_id}").json()["action_total"] == 1
        assert (
            c.get(f"/api/runs/{run_id}/actions").json()["actions"][0]["action"]
            == "observe"
        )


def test_live_pi_inventory_value_uses_acquisition_cost():
    actions = [
        dict(
            action="make_offer",
            payload=dict(product_id="p01", quantity=10, unit_price_cents=80),
            response=dict(result=dict(outcome="accepted")),
        ),
        dict(
            action="stock_items",
            payload=dict(product_id="p01", slot_id="r1s1", quantity=10),
            response=dict(result=dict(moved_quantity=10)),
        ),
        dict(
            action="end_day",
            payload={},
            response=dict(events=[dict(type="sales", product_id="p01", quantity=3)]),
        ),
    ]
    assert RunStore.pi_inventory_value(actions) == 560


def test_daily_tokens_and_action_attribution(tmp_path):
    path = write_run(tmp_path, complete=False)
    config = json.loads((path / "config.json").read_text()) | dict(
        agent="model", token_tracking_version=1
    )
    (path / "config.json").write_text(json.dumps(config))
    records = [json.loads(s) for s in (path / "actions.jsonl").read_text().splitlines()]
    records[0]["token_usage"] = dict(
        input_tokens=100,
        output_tokens=20,
        total_tokens=120,
        estimated=False,
        model_call=1,
        attribution="provider_call",
    )
    records[0]["start_sim_time"] = dict(day=1, minute_of_day=0)
    records[1]["token_usage"] = dict(
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
        estimated=False,
        model_call=1,
        attribution="shared_call",
    )
    records[1]["start_sim_time"] = dict(day=1, minute_of_day=5)
    (path / "actions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
    # An inference timeout on day two has usage even without a completed business day.
    usage = [
        dict(
            call=1,
            input_tokens=100,
            output_tokens=20,
            sim_time=dict(day=1, minute_of_day=0),
        ),
        dict(
            call=2,
            input_tokens=200,
            output_tokens=30,
            estimated=True,
            sim_time=dict(day=2, minute_of_day=0),
        ),
    ]
    (path / "usage.jsonl").write_text("".join(json.dumps(r) + "\n" for r in usage))
    with TestClient(create_app(tmp_path)) as c:
        d = c.get("/api/runs/run-a").json()
        assert [row["total_tokens"] for row in d["tokens_by_day"]] == [120, 230]
        assert d["tokens_by_day"][1]["estimated"] is True
        assert d["tokens_by_day"][1]["estimated_input_tokens"] == 200
        assert d["usage"]["input_tokens"] == 300
        actions = c.get("/api/runs/run-a/actions").json()["actions"]
        assert actions[0]["token_usage"]["total_tokens"] == 120
        assert actions[1]["token_usage"]["attribution"] == "shared_call"
        assert "Tokens by simulated day" in c.get("/").text


def test_legacy_scripted_zeroes_and_unknown_model_usage(tmp_path):
    path = write_run(tmp_path, complete=False)
    store = RunStore(tmp_path)
    assert store.actions("run-a")["actions"][0]["token_usage"]["total_tokens"] == 0
    assert store.detail("run-a")["tokens_by_day"][0]["total_tokens"] == 0
    config = json.loads((path / "config.json").read_text()) | dict(agent="model")
    (path / "config.json").write_text(json.dumps(config))
    (path / "usage.jsonl").write_text(
        json.dumps(dict(call=1, input_tokens=100, output_tokens=5)) + "\n"
    )
    assert store.actions("run-a")["actions"][0]["token_usage"]["total_tokens"] is None
    detail = store.detail("run-a")
    assert detail["tokens_by_day"][0]["total_tokens"] is None
    assert detail["unattributed_tokens"]["total_tokens"] == 105
    assert detail["unattributed_tokens"]["model_calls"] == 1
    assert detail["token_tracking_available"] is False


def test_daily_activity_crosses_midnight_without_double_counting():
    from viewer.activity import Activity

    activity = Activity()
    activity.add(dict(action="make_offer", payload=dict(product_id="p01", quantity=10),
                      response=dict(sim_time=dict(day=1, minute_of_day=75), elapsed_minutes=75,
                                    result=dict(outcome="accepted", total_cents=800))))
    activity.add(dict(action="make_offer", payload=dict(product_id="p01", quantity=10),
                      response=dict(sim_time=dict(day=1, minute_of_day=150), elapsed_minutes=75,
                                    result=dict(outcome="rejected"))))
    activity.add(dict(action="end_day", response=dict(
        sim_time=dict(day=2, minute_of_day=0), elapsed_minutes=1290,
        events=[dict(type="sales", product_id="p01", quantity=3),
                dict(type="day", day=1, sales=dict(p01=3))])))
    activity.add(dict(action="get_machine", response=dict(
        sim_time=dict(day=2, minute_of_day=5), elapsed_minutes=5,
        result=dict(slots=[], prices={}, products=[dict(product_id="p01", name="Water")]),
        events=[dict(type="sales", product_id="p01", quantity=2)])))
    fields = activity.fields()
    first, second = fields["daily_activity"]
    assert first["actions"] == dict(make_offer=2, end_day=1)
    assert first["purchase_cost_cents"] == 800
    assert len(first["purchases"]) == 1
    assert first["completed"] and first["sales"] == dict(p01=3)
    assert not second["completed"] and second["sales"] == dict(p01=2)
    assert fields["sales"] == [dict(product_id="p01", name="Water", quantity=5)]
    assert fields["machine"]["slots"] == []


def test_pi_daily_activity_matches_saved_run(tmp_path):
    path = write_run(tmp_path)
    records = [json.loads(line) for line in (path / "actions.jsonl").read_text().splitlines()]
    records[-1]["response"]["events"].append(dict(type="day", day=1, sales=dict(p01=5)))
    (path / "actions.jsonl").write_text("\n".join(map(json.dumps, records)))
    sessions = tmp_path / "pi-sessions"
    sessions.mkdir()
    messages = []
    for index, record in enumerate(records):
        messages.extend([
            dict(type="message", message=dict(role="assistant", content=[dict(
                type="toolCall", name="bash", id=str(index), arguments=dict(
                    command=f"curl -X POST http://localhost/env/env_abc/{record['action']} -d '{{}}'"))])),
            dict(type="message", message=dict(role="toolResult", toolCallId=str(index),
                                              content=[dict(type="text", text=json.dumps(record["response"]))])),
        ])
    (sessions / "daily.jsonl").write_text("\n".join(map(json.dumps, messages)))
    store = RunStore(tmp_path)
    pi, saved = store.detail("pi-daily"), store.detail("run-a")
    for key in ["sales", "day_events", "daily_activity", "machine", "inventory", "product_names"]:
        assert pi[key] == saved[key]
    assert pi["daily_activity"][0]["sales"] == dict(p01=5)


def test_pi_live_profit_counts_inventory_machine_cash_and_debt():
    actions = [
        dict(action="observe", payload={}, response=dict(
            action_id="act_0001", sim_time=dict(day=1, minute_of_day=5),
            elapsed_minutes=5, metrics=dict(cash_cents=10000))),
        dict(action="make_offer", payload=dict(product_id="p01", quantity=10, unit_price_cents=80),
             response=dict(action_id="act_0002", result=dict(outcome="accepted"))),
        dict(action="stock_items", payload=dict(product_id="p01", slot_id="r1s1", quantity=10),
             response=dict(action_id="act_0003", result=dict(moved_quantity=10))),
        dict(action="end_day", payload={}, response=dict(
            action_id="act_0004", events=[dict(type="sales", product_id="p01", quantity=3)],
            metrics=dict(cash_cents=9000, machine_cash_cents=600, fee_debt_cents=50))),
    ]
    score = RunStore.pi_live_score(actions)
    assert score["inventory_value_cents"] == 560
    assert score["score_cents"] == 10110
    assert score["net_profit_cents"] == 110
    assert RunStore.pi_live_score(actions[1:]) == {}
    assert RunStore.pi_live_score(actions[:2] + actions[3:]) == {}
    actions[-1]["response"]["metrics"]["machine_cash_cents"] = 0
    assert RunStore.pi_live_score(actions)["net_profit_cents"] == -490
