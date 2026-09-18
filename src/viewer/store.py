"""Read existing artifacts without loading private demand logs or changing runs."""

from collections import deque
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from .tokens import DailyTokens, action_tokens
from .activity import Activity


class RunNotFound(ValueError):
    pass


class RunStore:
    def __init__(
        self, directory="runs", service_directory=None, pi_sessions_directory=None
    ):
        self.directory = Path(directory).resolve()
        self.service_directory = (
            Path(service_directory).resolve()
            if service_directory
            else self.directory / "service"
        )
        self.pi_sessions_directory = (
            Path(pi_sessions_directory).resolve()
            if pi_sessions_directory
            else self.directory / "pi-sessions"
        )

    @staticmethod
    def pi_run_id(path):
        return f"pi-{path.stem}"

    def pi_path(self, run_id):
        if not run_id.startswith("pi-"):
            raise RunNotFound("Run not found")
        session_id = run_id.removeprefix("pi-")
        if not re.fullmatch(r"[0-9A-Za-z_-]{1,127}", session_id):
            raise RunNotFound("Run not found")
        path = self.pi_sessions_directory / f"{session_id}.jsonl"
        if path.is_symlink() or not path.is_file():
            raise RunNotFound("Run not found")
        return path

    def run_path(self, run_id):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", run_id):
            raise RunNotFound("Run not found")
        path = self.directory / run_id
        if (
            path.is_symlink()
            or not path.is_dir()
            or not self.file(path, "config.json").is_file()
        ):
            raise RunNotFound("Run not found")
        return path

    @staticmethod
    def file(path, name):
        target = path / name
        if target.is_symlink():
            raise RunNotFound("Artifact symlinks are not supported")
        return target

    def read_json(self, path, name, warnings):
        try:
            value = json.loads(
                self.file(path, name).read_text(), parse_constant=lambda _: None
            )
            if not isinstance(value, dict):
                raise ValueError("expected object")
            return value
        except FileNotFoundError:
            return None
        except (ValueError, OSError) as exc:
            warnings.append(f"{name} is unreadable or still being written.")
            return None

    def records(self, path, name, warnings):
        try:
            with self.file(path, name).open() as stream:
                bad = 0
                for line in stream:
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line, parse_constant=lambda _: None)
                        if not isinstance(record, dict):
                            raise ValueError("expected object")
                    except ValueError:
                        bad += 1
                        continue
                    yield record
                if bad:
                    warnings.append(
                        f"{name}: skipped {bad} incomplete or malformed records."
                    )
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            warnings.append(f"{name} could not be read.")

    def pi_data(self, path, warnings):
        model, created_at, pending, actions, usage = (
            None,
            None,
            {},
            [],
            dict(calls=0, input_tokens=0, output_tokens=0),
        )
        try:
            with path.open() as stream:
                for line in stream:
                    try:
                        record = json.loads(line, parse_constant=lambda _: None)
                    except ValueError:
                        warnings.append(
                            "Pi session contains an incomplete record that will be retried on refresh."
                        )
                        continue
                    created_at = created_at or record.get("timestamp")
                    if record.get("type") == "model_change":
                        model = record.get("modelId", model)
                    message = record.get("message") or {}
                    if record.get("type") != "message" or not isinstance(message, dict):
                        continue
                    if message.get("role") == "assistant":
                        call_usage = message.get("usage") or {}
                        usage["calls"] += 1
                        usage["input_tokens"] += call_usage.get("input", 0) or 0
                        usage["output_tokens"] += call_usage.get("output", 0) or 0
                        for content in message.get("content") or []:
                            if (
                                content.get("type") != "toolCall"
                                or content.get("name") != "bash"
                            ):
                                continue
                            command = (content.get("arguments") or {}).get(
                                "command", ""
                            )
                            match = re.search(r'/env/[^/\s"\\]+/([a-z_]+)', command)
                            if match:
                                payload_match = re.search(r"-d\s+'([^']*)'", command)
                                try:
                                    payload = (
                                        json.loads(payload_match.group(1))
                                        if payload_match
                                        else {}
                                    )
                                except ValueError:
                                    payload = {}
                                pending[content.get("id")] = dict(
                                    action=match.group(1), payload=payload
                                )
                    elif message.get("role") == "toolResult":
                        request = pending.pop(message.get("toolCallId"), None)
                        if not request:
                            continue
                        text = "".join(
                            part.get("text", "")
                            for part in message.get("content") or []
                        )
                        try:
                            response = json.loads(text)
                        except ValueError:
                            response = {}
                        actions.append(dict(**request, response=response))
        except OSError:
            warnings.append("Pi session could not be read.")
        return dict(model=model, created_at=created_at, actions=actions, usage=usage)

    @staticmethod
    def pi_inventory_value(actions):
        storage, slots = {}, {}

        def move(source, target, quantity):
            while quantity and source:
                lot = source[0]
                moved = min(quantity, lot["quantity"])
                target.append(
                    dict(quantity=moved, unit_cost_cents=lot["unit_cost_cents"])
                )
                lot["quantity"] -= moved
                quantity -= moved
                if not lot["quantity"]:
                    source.popleft()

        for record in actions:
            action, payload, response = (
                record["action"],
                record["payload"],
                record["response"],
            )
            result = response.get("result") or {}
            if action == "make_offer" and result.get("outcome") == "accepted":
                product_id = payload.get("product_id")
                if product_id:
                    storage.setdefault(product_id, deque()).append(
                        dict(
                            quantity=payload.get("quantity", 0),
                            unit_cost_cents=payload.get("unit_price_cents", 0),
                        )
                    )
            elif action == "stock_items" and "moved_quantity" in result:
                product_id, slot_id = payload.get("product_id"), payload.get("slot_id")
                if product_id and slot_id:
                    slot = slots.setdefault(
                        slot_id, dict(product_id=product_id, lots=deque())
                    )
                    slot["product_id"] = product_id
                    move(
                        storage.setdefault(product_id, deque()),
                        slot["lots"],
                        result["moved_quantity"],
                    )
            elif action == "unstock_items" and "moved_quantity" in result:
                slot = slots.get(payload.get("slot_id"))
                if slot:
                    move(
                        slot["lots"],
                        storage.setdefault(slot["product_id"], deque()),
                        result["moved_quantity"],
                    )
                    if not slot["lots"]:
                        slot["product_id"] = None
            for event in response.get("events") or []:
                if event.get("type") != "sales":
                    continue
                quantity = event.get("quantity", 0)
                for slot_id in sorted(slots):
                    slot = slots[slot_id]
                    if slot["product_id"] != event.get("product_id") or not quantity:
                        continue
                    before = sum(lot["quantity"] for lot in slot["lots"])
                    move(slot["lots"], deque(), quantity)
                    quantity -= min(quantity, before)
                    if not slot["lots"]:
                        slot["product_id"] = None
        return sum(
            lot["quantity"] * lot["unit_cost_cents"]
            for lots in storage.values()
            for lot in lots
        ) + sum(
            lot["quantity"] * lot["unit_cost_cents"]
            for slot in slots.values()
            for lot in slot["lots"]
        )

    @classmethod
    def pi_live_score(cls, actions):
        """Reconstruct profit only when the session includes a complete action history."""
        if not actions:
            return {}
        first = actions[0]["response"]
        clock = first.get("sim_time") or {}
        if (actions[0]["action"] != "observe"
                or clock.get("day") != 1
                or clock.get("minute_of_day") != first.get("elapsed_minutes")
                or first.get("events")):
            return {}
        for index, record in enumerate(actions, 1):
            if record["response"].get("action_id") != f"act_{index:04}":
                return {}
        initial = (first.get("metrics") or {}).get("cash_cents")
        balances = actions[-1]["response"].get("metrics") or {}
        keys = ("cash_cents", "machine_cash_cents", "fee_debt_cents")
        if initial is None or any(key not in balances for key in keys):
            return {}
        inventory = cls.pi_inventory_value(actions)
        gross = balances["cash_cents"] + balances["machine_cash_cents"] + inventory
        net = gross - balances["fee_debt_cents"]
        return dict(
            **{key: balances[key] for key in keys},
            inventory_value_cents=inventory, gross_assets_cents=gross,
            score_cents=net, net_profit_cents=net - initial,
        )

    def pi_metadata(self, path):
        warnings = []
        data = self.pi_data(path, warnings)
        return (
            dict(
                run_id=self.pi_run_id(path),
                agent="pi",
                model=data["model"],
                run_name="Pi live session",
                environment="live API session",
                seed=None,
                scenario_version=None,
                classification="unfinished",
                reason=None,
                created_at=data["created_at"]
                or datetime.fromtimestamp(
                    path.stat().st_mtime, timezone.utc
                ).isoformat(),
                score={},
                score_source=None,
                simulated_minutes=None,
                usage=data["usage"],
                errors=[],
                warnings=warnings,
            ),
            data,
        )

    def metadata(self, path):
        warnings = []
        config = self.read_json(path, "config.json", warnings) or {}
        summary = self.read_json(path, "summary.json", warnings)
        terminal = (summary or {}).get("terminal") or {}
        source = "terminal" if terminal else None
        # A stopped runner may have a trusted pre-deletion score outside its public log.
        env_id = (summary or {}).get("env_id")
        if (
            summary
            and not terminal
            and isinstance(env_id, str)
            and re.fullmatch(r"env_[a-f0-9]+", env_id)
        ):
            artifact = self.read_json(
                self.service_directory, f"{env_id}.json", warnings
            )
            if artifact and isinstance(artifact.get("summary"), dict):
                terminal = artifact["summary"]
                source = "pre_deletion"
        score = terminal.get("score") or {}
        modified = self.file(path, "config.json").stat().st_mtime
        evaluator = (summary or {}).get("evaluator") or {}
        item = dict(
            run_id=path.name,
            agent=config.get("agent", "unknown"),
            model=config.get("model"),
            run_name=config.get("run_name"),
            environment=evaluator.get("environment_name")
            or config.get("environment_name")
            or config.get("scenario_id", "unknown"),
            seed=evaluator.get("seed", config.get("seed")),
            scenario_version=terminal.get("scenario_version"),
            classification=(summary or {}).get("classification", "unfinished"),
            reason=terminal.get("termination_reason") or (summary or {}).get("reason"),
            created_at=config.get("created_at")
            or datetime.fromtimestamp(modified, timezone.utc).isoformat(),
            score=score,
            score_source=source,
            simulated_minutes=terminal.get("simulated_minutes"),
            usage=(summary or {}).get("usage") or {},
            errors=(summary or {}).get("errors") or [],
            warnings=warnings,
        )
        return item, config, summary, terminal

    def list_runs(self, query="", classification="", offset=0, limit=50):
        items = []
        if self.directory.is_dir():
            for path in self.directory.iterdir():
                try:
                    path = self.run_path(path.name)
                    item, *_ = self.metadata(path)
                except (RunNotFound, OSError, TypeError, AttributeError):
                    continue
                haystack = " ".join(
                    str(item[k])
                    for k in (
                        "run_id",
                        "run_name",
                        "agent",
                        "model",
                        "environment",
                        "seed",
                    )
                ).lower()
                if query.lower() in haystack and (
                    not classification or item["classification"] == classification
                ):
                    items.append(item)
        if self.pi_sessions_directory.is_dir():
            for path in self.pi_sessions_directory.glob("*.jsonl"):
                if path.is_symlink():
                    continue
                try:
                    item, _ = self.pi_metadata(path)
                except (OSError, TypeError, AttributeError):
                    continue
                haystack = " ".join(
                    str(item[k])
                    for k in (
                        "run_id",
                        "run_name",
                        "agent",
                        "model",
                        "environment",
                        "seed",
                    )
                ).lower()
                if query.lower() in haystack and (
                    not classification or item["classification"] == classification
                ):
                    items.append(item)
        items.sort(key=lambda x: (x["created_at"], x["run_id"]), reverse=True)
        return dict(
            runs=items[offset : offset + limit],
            total=len(items),
            offset=offset,
            limit=limit,
        )

    def detail(self, run_id):
        if run_id.startswith("pi-"):
            path = self.pi_path(run_id)
            item, data = self.pi_metadata(path)
            timeline, action_counts, last_response = [], {}, None
            activity = Activity()
            for index, record in enumerate(data["actions"], 1):
                activity.add(record)
                action = record["action"]
                action_counts[action] = action_counts.get(action, 0) + 1
                response = record["response"]
                if "sim_time" in response and "metrics" in response:
                    last_response = response
                    clock = response["sim_time"]
                    timeline.append(
                        dict(
                            index=index,
                            minute=(clock["day"] - 1) * 1440 + clock["minute_of_day"],
                            **response["metrics"],
                        )
                    )
            if last_response:
                item["simulated_minutes"] = timeline[-1]["minute"]
                item["last_balances"] = last_response["metrics"]
            item["inventory_value_cents"] = self.pi_inventory_value(data["actions"])
            item["live_score"] = self.pi_live_score(data["actions"])
            if last_response and last_response.get("score"):
                item["score"] = last_response["score"]
                item["score_source"] = "terminal"
                item["classification"] = "completed"
                item["reason"] = last_response.get("termination_reason")
            return dict(
                **item,
                config={},
                terminal={},
                summary=None,
                timeline=timeline,
                **activity.fields(),
                action_counts=action_counts,
                action_total=len(data["actions"]),
                memory="",
                usage_records=[],
                tokens_by_day=[],
                token_tracking_available=False,
                unattributed_tokens=dict(total_tokens=None, model_calls=0),
            )
        path = self.run_path(run_id)
        item, config, summary, terminal = self.metadata(path)
        warnings = item["warnings"]
        token_days = DailyTokens(config)
        timeline, day_events, sold, action_counts, names = [], [], {}, {}, {}
        last_machine, last_inventory, last_response = None, None, None
        count = 0
        activity = Activity()
        for record in self.records(path, "actions.jsonl", warnings):
            activity.add(record)
            token_days.action(record)
            count += 1
            action = record.get("action", "unknown")
            action_counts[action] = action_counts.get(action, 0) + 1
            response = record.get("response") or {}
            result = response.get("result") or {}
            for product in result.get("products", []):
                names[product["product_id"]] = product.get(
                    "name", product["product_id"]
                )
            if "slots" in result:
                last_machine = dict(
                    slots=result["slots"],
                    prices=result.get("prices", {}),
                    sim_time=response.get("sim_time"),
                )
            if "storage" in result:
                last_inventory = dict(
                    storage=result["storage"], sim_time=response.get("sim_time")
                )
            for event in response.get("events", []):
                if event.get("type") == "sales":
                    pid = event["product_id"]
                    sold[pid] = sold.get(pid, 0) + event.get("quantity", 0)
                elif event.get("type") == "day":
                    day_events.append(event)
                    day_events = day_events[-100:]
            if "sim_time" in response and "metrics" in response:
                last_response = response
                clock = response["sim_time"]
                point = dict(
                    index=count,
                    minute=(clock["day"] - 1) * 1440 + clock["minute_of_day"],
                    **response["metrics"],
                )
                timeline.append(point)
                if len(timeline) > 600:
                    timeline = timeline[::2]
        if last_response:
            last_point = dict(
                index=count,
                minute=(last_response["sim_time"]["day"] - 1) * 1440
                + last_response["sim_time"]["minute_of_day"],
                **last_response["metrics"],
            )
            if not timeline or timeline[-1]["minute"] != last_point["minute"]:
                timeline.append(last_point)
            if item["simulated_minutes"] is None:
                item["simulated_minutes"] = last_point["minute"]
            item["last_balances"] = last_response["metrics"]
        usage_records = deque(maxlen=1000)
        usage_totals = dict(calls=0, input_tokens=0, output_tokens=0)
        for record in self.records(path, "usage.jsonl", warnings):
            usage_records.append(record)
            token_days.usage(record)
            usage_totals["calls"] += 1
            usage_totals["input_tokens"] += record.get("input_tokens", 0)
            usage_totals["output_tokens"] += record.get("output_tokens", 0)
        if not item["usage"]:
            item["usage"] = usage_totals
        try:
            memory = self.file(path, "memory.md").read_text()
        except (OSError, ValueError):
            memory = ""
        # Explicitly return only the public summary section of a trusted service artifact.
        return dict(
            **item,
            config=config,
            terminal=terminal,
            summary=summary,
            timeline=timeline,
            sales=[
                dict(product_id=pid, name=names.get(pid, pid), quantity=qty)
                for pid, qty in sorted(sold.items())
            ],
            daily_activity=activity.fields()["daily_activity"],
            day_events=day_events,
            action_counts=action_counts,
            action_total=count,
            machine=last_machine,
            inventory=last_inventory,
            product_names=names,
            memory=memory,
            usage_records=list(usage_records),
            tokens_by_day=token_days.rows(),
            token_tracking_available=token_days.available,
            unattributed_tokens=token_days.unattributed,
        )

    def actions(self, run_id, action="", offset=0, limit=50):
        if run_id.startswith("pi-"):
            path = self.pi_path(run_id)
            _, data = self.pi_metadata(path)
            records = [
                record
                for record in data["actions"]
                if not action or record["action"] == action
            ]
            items = [
                dict(index=index, **record, token_usage=dict(total_tokens=None))
                for index, record in enumerate(
                    records[offset : offset + limit], offset + 1
                )
            ]
            return dict(
                actions=items,
                total=len(records),
                offset=offset,
                limit=limit,
                warnings=[],
            )
        path = self.run_path(run_id)
        warnings, items, total = [], [], 0
        config = self.read_json(path, "config.json", warnings) or {}
        for index, record in enumerate(
            self.records(path, "actions.jsonl", warnings), 1
        ):
            if action and action != record.get("action"):
                continue
            if offset <= total < offset + limit:
                items.append(
                    dict(
                        index=index,
                        **(record | {"token_usage": action_tokens(record, config)}),
                    )
                )
            total += 1
        return dict(
            actions=items, total=total, offset=offset, limit=limit, warnings=warnings
        )
