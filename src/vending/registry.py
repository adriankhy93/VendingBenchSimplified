"""Serialized lifecycle with copy-on-commit actions and private evaluator artifacts."""
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import secrets
import threading
import time
from pydantic import ValidationError
from .config import Scenario
from .engine import Engine
from .models import ACTIONS, DomainValidation

class APIError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message

@dataclass
class Entry:
    engine: Engine | None
    created: float
    deadline: float
    retention: int
    seed: int
    config: dict
    lock: threading.RLock = field(default_factory=threading.RLock)
    state: str = "running"
    terminal: dict | None = None
    finished: float | None = None
    deleted: bool = False
    replays: dict = field(default_factory=dict)
    private_metrics: dict = field(default_factory=dict)

class Registry:
    def __init__(self, scenario=None, clock=time.monotonic, artifact_dir="runs/service"):
        self.scenario = scenario or Scenario()
        self.clock = clock
        self.entries = {}
        self.lock = threading.RLock()
        self.artifact_dir = Path(artifact_dir)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)

    def create(self, options):
        config = self.scenario.model_dump()
        config.update({k: v for k, v in options.items() if k != "seed"})
        if options.get("scenario_id") == "smoke-v1" and "max_days" not in options:
            config["max_days"] = 14
        if options.get("scenario_id") == "benchmark-v1" and "max_days" not in options:
            config["max_days"] = None
        config = Scenario.model_validate(config)
        seed = options.get("seed", secrets.randbits(63))
        started = self.clock()
        engine = Engine(config, seed)
        engine.deadline_utc = (datetime.now(timezone.utc) + timedelta(seconds=config.runtime_seconds)).isoformat()
        entry = Entry(engine, started, started + config.runtime_seconds, config.retention_seconds, seed, config.model_dump(mode="json"))
        env_id = "env_" + secrets.token_hex(12)
        with self.lock:
            self.entries[env_id] = entry
        return env_id

    def lookup(self, env_id):
        with self.lock:
            entry = self.entries.get(env_id)
        if entry is None:
            raise APIError(404, "unknown_environment", "Environment not found")
        return entry

    def artifact(self, env_id, entry, summary):
        target = self.artifact_dir / f"{env_id}.json"
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(dict(summary=summary, evaluator=dict(seed=entry.seed, config=entry.config, metrics=entry.private_metrics))))
        temporary.replace(target)

    def finish(self, env_id, entry, state, reason):
        if entry.state != "running":
            return
        engine = entry.engine
        entry.private_metrics = dict(stockouts=dict(engine.stockouts))
        engine.state, engine.reason = state, reason
        summary = engine.summary(complete=state == "ended")
        summary["committed_action_count"] = engine.action_count
        summary["wall_duration_seconds"] = max(0, self.clock() - entry.created)
        entry.state, entry.terminal, entry.finished = state, summary, self.clock()
        entry.engine = None
        entry.replays.clear()
        try:
            self.artifact(env_id, entry, summary)
        except OSError:
            # Retain the in-memory terminal result even if evaluator storage fails.
            entry.terminal["artifact_error"] = "evaluator artifact could not be written"

    def check(self, env_id, entry):
        if entry.deleted:
            raise APIError(404, "unknown_environment", "Environment not found")
        if entry.state == "running" and self.clock() >= entry.deadline:
            self.finish(env_id, entry, "ended", "real_deadline")
        if entry.finished is not None and self.clock() >= entry.finished + entry.retention:
            entry.deleted = True
            with self.lock:
                self.entries.pop(env_id, None)
            raise APIError(404, "unknown_environment", "Environment retention expired")

    def status(self, env_id):
        entry = self.lookup(env_id)
        with entry.lock:
            self.check(env_id, entry)
            return {"state": entry.state}

    def result(self, env_id):
        entry = self.lookup(env_id)
        with entry.lock:
            self.check(env_id, entry)
            if entry.state == "running":
                raise APIError(409, "environment_running", "No terminal result yet")
            return deepcopy(entry.terminal)

    def invalid(self, env_id):
        entry = self.lookup(env_id)
        with entry.lock:
            if entry.engine:
                entry.engine.invalid_calls += 1

    def action(self, env_id, action, payload, key=None):
        entry = self.lookup(env_id)
        with entry.lock:
            self.check(env_id, entry)
            if action not in ACTIONS:
                if entry.engine:
                    entry.engine.invalid_calls += 1
                raise APIError(404, "unknown_action", "Unknown action")
            if entry.state != "running":
                status = 410 if entry.state == "ended" else 409
                raise APIError(status, f"environment_{entry.state}", f"Environment is {entry.state}")
            if key is not None and (not key or len(key) > 200):
                raise APIError(422, "invalid_idempotency_key", "Key must contain 1–200 characters")
            try:
                entry.engine.validate(action, payload)
            except (ValidationError, DomainValidation) as exc:
                entry.engine.invalid_calls += 1
                raise APIError(422, "invalid_action", "Invalid action fields, identifiers, quantity, or price") from exc
            fingerprint = hashlib.sha256(json.dumps([action, payload], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            if key in entry.replays:
                previous, response = entry.replays[key]
                if previous != fingerprint:
                    raise APIError(409, "idempotency_conflict", "Key already used for different action or payload")
                return deepcopy(response)
            try:
                staged = deepcopy(entry.engine)
                response = staged.execute(action, payload)
                if self.clock() >= entry.deadline:
                    self.finish(env_id, entry, "ended", "real_deadline")
                    raise APIError(410, "environment_ended", "Deadline passed; action discarded")
                # Private latent demand is streamed separately and not retained in live state.
                if staged.private_events:
                    with (self.artifact_dir / f"{env_id}.private.jsonl").open('a') as stream:
                        stream.write(''.join(json.dumps(dict(action_id=response['action_id'], **event)) + '\n' for event in staged.private_events))
                    staged.private_events.clear()
                # I/O can itself cross the deadline; never commit business state afterward.
                if self.clock() >= entry.deadline:
                    self.finish(env_id, entry, "ended", "real_deadline")
                    raise APIError(410, "environment_ended", "Deadline passed; action discarded")
                entry.engine = staged
                if staged.state == "ended":
                    self.finish(env_id, entry, "ended", staged.reason)
                elif key:
                    entry.replays[key] = (fingerprint, deepcopy(response))
                return response
            except APIError:
                raise
            except Exception as exc:
                self.finish(env_id, entry, "unavailable", "internal_error")
                raise APIError(500, "internal_error", "Environment became unavailable") from exc

    def delete(self, env_id):
        try:
            entry = self.lookup(env_id)
        except APIError:
            return
        with entry.lock:
            if entry.deleted:
                return
            if entry.state == "running":
                if self.clock() >= entry.deadline:
                    self.finish(env_id, entry, "ended", "real_deadline")
                else:
                    entry.private_metrics = dict(stockouts=dict(entry.engine.stockouts))
                    summary = entry.engine.summary(complete=False)
                    summary.update(committed_action_count=entry.engine.action_count, termination_reason="deleted_while_running", wall_duration_seconds=self.clock() - entry.created)
                    self.artifact(env_id, entry, summary)
            entry.deleted = True
            entry.engine = None
            entry.replays.clear()
            with self.lock:
                self.entries.pop(env_id, None)

    def sweep(self):
        with self.lock:
            items = list(self.entries.items())
        for env_id, entry in items:
            with entry.lock:
                try:
                    self.check(env_id, entry)
                except APIError:
                    pass
