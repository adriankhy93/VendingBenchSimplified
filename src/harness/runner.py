"""Run one HTTP episode and always preserve artifacts and attempt cleanup."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time
import uuid
import re
from datetime import datetime, timezone
from pydantic import Field
from vending.config import StrictModel
from vending.environments import load_environment
from vending.models import ACTIONS
from .agents import Idle, Baseline
from .client import Client, ServiceError
from .context import Context
from .watchdog import decide, EnvironmentStopped
from .usage import TokenLedger
from .traces import TraceWriter, TracedAdapter
from .vllm_provider import VLLMSettings
from .tool_descriptions import TOOL_DESCRIPTIONS

class RunConfig(StrictModel):
    service_url: str = 'http://127.0.0.1:8000'
    environment_name: str | None = None
    environments_dir: str = 'environments'
    scenario_id: str = 'benchmark-v1'
    seed: int = Field(default=0, ge=0)
    agent: str = 'idle'
    run_name: str | None = Field(default=None, min_length=1, max_length=80)
    provider: str | None = None
    model: str | None = None
    vllm: VLLMSettings = Field(default_factory=VLLMSettings)
    runtime_seconds: int = Field(default=7200, gt=0)
    max_days: int | None = Field(default=None, gt=0)
    token_budget: int = Field(default=100000, gt=0)
    max_calls: int = Field(default=1000, gt=0)
    max_output_tokens: int = Field(default=1024, gt=0)
    watchdog_grace_seconds: int = Field(default=60, gt=0)
    request_timeout: int = Field(default=30, gt=0)
    model_timeout: int = Field(default=60, gt=0)
    max_invalid: int = Field(default=5, gt=0)
    recent_pairs: int = Field(default=20, gt=0)
    memory_limit: int = Field(default=8000, gt=0)
    prompt_path: str = 'prompts/agent.md'
    instruction_paths: tuple[str, ...] = ()
    memory_template_path: str | None = None
    tool_allowlist: tuple[str, ...] = tuple(ACTIONS)
    enable_memory: bool = False
    loop_repeat_limit: int = Field(default=3, ge=1)
    harness_path: str = 'harness.md'
    artifact_dir: str = 'runs'


def tools_for(config):
    if not config.tool_allowlist or any(name not in ACTIONS for name in config.tool_allowlist):
        raise ValueError('tool allowlist must contain known vending actions')
    result = [dict(name=name, description=TOOL_DESCRIPTIONS[name] + ' Money is in integer cents.',
                   input_schema=ACTIONS[name].model_json_schema()) for name in config.tool_allowlist]
    if config.enable_memory:
        result.append(dict(name='write_memory', description='Replace local Markdown notebook; no simulated time cost.',
                           input_schema={'type':'object', 'properties':{'content':{'type':'string', 'maxLength':config.memory_limit}},
                                         'required':['content'], 'additionalProperties':False}))
        for name, description, properties, required in (
            ('list_memory', 'List your saved Markdown notes. Read relevant files before planning.', {}, []),
            ('read_memory', 'Read one run-local Markdown note by filename.', {'name': {'type':'string'}}, ['name']),
            ('write_memory_file', 'Create or replace one Markdown note, e.g. products.md, strategy.md or lessons.md. Read existing notes before updating. No simulated time cost.', {'name': {'type':'string'}, 'content': {'type':'string', 'maxLength':config.memory_limit}}, ['name','content']),
        ):
            result.append(dict(name=name, description=description, input_schema=dict(type='object', properties=properties, required=required, additionalProperties=False)))
    return result


def run(config: RunConfig, adapter=None, client=None, clock=time.monotonic):
    saved, definition_hash = None, None
    if config.environment_name:
        saved, definition_hash = load_environment(config.environments_dir, config.environment_name)
        config = RunConfig.model_validate(config.model_dump() | dict(seed=saved.seed,
                   scenario_id=saved.scenario.scenario_id, runtime_seconds=saved.scenario.runtime_seconds,
                   max_days=saved.scenario.max_days))
    if config.agent not in ('idle', 'listed', 'negotiating', 'model'):
        raise ValueError('unknown agent')
    if config.agent == 'model' and adapter is None:
        raise ValueError('model agent requires an adapter')
    schemas = tools_for(config)
    paths = [config.harness_path, config.prompt_path, *config.instruction_paths]
    contents = {path: Path(path).read_text() for path in paths}
    if config.memory_template_path:
        contents[config.memory_template_path] = Path(config.memory_template_path).read_text()
    created_at = datetime.now(timezone.utc)
    label = config.run_name or f'{config.model or config.agent}--{config.environment_name or config.scenario_id}'
    slug = re.sub(r'[^a-z0-9_-]+', '-', label.lower()).strip('-_')[:80] or 'run'
    run_id = f'{created_at:%Y-%m-%d_%H-%M-%S}--{slug}--{uuid.uuid4().hex[:8]}'
    directory = Path(config.artifact_dir) / run_id
    directory.mkdir(parents=True)
    effective = config.model_dump(mode='json') | {'file_hashes': {p: hashlib.sha256(t.encode()).hexdigest() for p, t in contents.items()}, 'run_id':run_id, 'created_at':created_at.isoformat(), 'token_tracking_version':1}
    if saved:
        effective['environment_definition'] = saved.model_dump(mode='json')
        effective['environment_sha256'] = definition_hash
    (directory / 'config.json').write_text(json.dumps(effective, indent=2))
    context = Context('\n\n'.join(contents[p] for p in paths), directory / 'memory.md', config.recent_pairs, config.memory_limit)
    if config.memory_template_path:
        context.write_memory(contents[config.memory_template_path])
    client_owned = client is None
    client = client or Client(config.service_url, config.request_timeout, clock=clock)
    policy = Idle() if config.agent == 'idle' else Baseline(config.agent == 'negotiating')
    started = clock()
    deadline = started + config.runtime_seconds + config.watchdog_grace_seconds
    env_id, latest, terminal = None, None, None
    calls = input_tokens = output_tokens = invalid = 0
    cost, has_cost = 0., False
    reason, errors = 'error', []
    action_latencies = []
    token_ledger = TokenLedger()
    trace = TraceWriter(directory / 'llm_traces.jsonl') if config.agent == 'model' else None
    action_log = (directory / 'actions.jsonl').open('w')
    usage_log = (directory / 'usage.jsonl').open('w')

    def record(action, payload, response):
        action_log.write(json.dumps(dict(action=action, payload=payload, response=response, **token_ledger.action(response))) + '\n')
        action_log.flush()
        context.append(action, payload, response)

    def record_usage(input_count, output_count, **metadata):
        usage_log.write(json.dumps(token_ledger.provider(calls, input_count, output_count, **metadata)) + '\n')
        usage_log.flush()

    try:
        options = dict(scenario_id=config.scenario_id, seed=config.seed, runtime_seconds=config.runtime_seconds, max_days=config.max_days)
        if saved:
            options = dict(environment_name=saved.name, environment_sha256=definition_hash)
        env_id = client.create(options, deadline)
        latest = client.action(env_id, 'observe', {}, deadline)
        record('observe', {}, latest)
        while True:
            if latest.get('state') in ('ended', 'unavailable'):
                reason = latest['state']
                break
            if clock() >= deadline:
                reason = 'runner_deadline'
                break
            if calls >= config.max_calls:
                reason = 'max_calls'
                break
            if invalid >= config.max_invalid:
                reason = 'repeated_invalid_actions'
                break
            if config.agent == 'model':
                state = client.status(env_id, deadline)['state']
                if state != 'running':
                    reason = state
                    break
                messages = context.messages(dict(tokens=config.token_budget-input_tokens-output_tokens,
                                                 calls=config.max_calls-calls, seconds=max(0, deadline-clock())))
                # UTF-8 byte count is a conservative reservation for text tokenizers.
                reserve = len(json.dumps([messages, schemas], ensure_ascii=False).encode()) + 1024
                if input_tokens + output_tokens + reserve + config.max_output_tokens > config.token_budget:
                    reason = 'token_budget'
                    break
                calls += 1
                try:
                    decision = decide(TracedAdapter(adapter, trace, calls), messages, schemas, config.max_output_tokens,
                                      min(config.model_timeout, max(.001, deadline-clock())),
                                      lambda: client.status(env_id, deadline)['state'], clock)
                except EnvironmentStopped as exc:
                    trace.write(calls, 'watchdog_stop', reason=exc.state)
                    input_tokens += reserve
                    output_tokens += config.max_output_tokens
                    record_usage(reserve, config.max_output_tokens, estimated=True, error='environment_stopped')
                    reason = exc.state
                    break
                except TimeoutError:
                    trace.write(calls, 'watchdog_stop', reason='timeout')
                    # A timed-out provider may have consumed unreported tokens.
                    input_tokens += reserve
                    output_tokens += config.max_output_tokens
                    record_usage(reserve, config.max_output_tokens, estimated=True, error='provider_timeout')
                    invalid += 1
                    record('provider_error', {}, {'error':{'code':'provider_timeout'}})
                    continue
                if decision.input_tokens < 0 or decision.output_tokens < 0:
                    raise ValueError('negative provider usage')
                input_tokens += decision.input_tokens
                output_tokens += decision.output_tokens
                if decision.cost_usd is not None:
                    has_cost = True
                    cost += decision.cost_usd
                record_usage(decision.input_tokens, decision.output_tokens, cost_usd=decision.cost_usd)
                state = client.status(env_id, deadline)['state']
                if state != 'running':
                    reason = state
                    break
                if input_tokens + output_tokens >= config.token_budget:
                    reason = 'token_budget'
                    break
                pending = decision.calls
                if not pending:
                    invalid += 1
                    record('invalid_provider_response', {}, {'error':{'code':'empty_response'}})
                    continue
            else:
                calls += 1
                action, payload = policy.choose(deepcopy(latest))
                pending = [dict(name=action, payload=payload)]
            for call in pending:
                if invalid >= config.max_invalid:
                    break
                try:
                    if not isinstance(call, dict) or set(call) != {'name', 'payload'}:
                        raise ValueError('expected name and payload')
                    action, payload = call['name'], call['payload']
                    if action in ('list_memory', 'read_memory', 'write_memory_file') and config.enable_memory:
                        result = context.memory_action(action, payload)
                        record(action, payload, {'result': result})
                        continue
                    if action == 'write_memory' and config.enable_memory:
                        if not isinstance(payload, dict) or set(payload) != {'content'}:
                            raise ValueError('memory requires content only')
                        context.write_memory(payload['content'])
                        record(action, payload, {'result':{'outcome':'written'}})
                        invalid = 0
                        continue
                    if action not in config.tool_allowlist:
                        raise ValueError('action is not allowed')
                    ACTIONS[action].model_validate(payload)
                    if config.agent == 'model' and context.blocked(action, payload, config.loop_repeat_limit):
                        invalid += 1
                        record(action, payload, {'error': {'code': 'loop_blocked', 'message': 'Repeated unsuccessful call blocked locally. Change parameters or resolve the prerequisite before retrying.'}})
                        continue
                except (ValueError, TypeError, KeyError):
                    invalid += 1
                    record('invalid_provider_response', {}, {'error':{'code':'invalid_action', 'message':'Select an allowed action with its exact schema.'}})
                    continue
                try:
                    action_started = clock()
                    latest = client.action(env_id, action, payload, deadline)
                    action_latencies.append(clock() - action_started)
                except ServiceError as exc:
                    record(action, payload, {'error':exc.error})
                    if exc.status in (409, 410, 500):
                        state = client.status(env_id, deadline)['state']
                        if state != 'running':
                            latest = {'state':state}
                            break
                    if exc.status == 404 and exc.error.get('code') == 'unknown_environment':
                        raise
                    if exc.status not in (400, 404, 409, 422):
                        raise
                    invalid += 1
                    continue
                except Exception:
                    record(action, payload, {'error':{'code':'action_response_unavailable'}})
                    raise
                invalid = 0
                record(action, payload, latest)
                if latest.get('state') != 'running':
                    break
    except KeyboardInterrupt:
        reason = 'interrupted'
    except TimeoutError:
        reason = 'runner_deadline'
    except Exception as exc:
        # Do not serialize exception strings or provider response bodies (credentials).
        errors.append(type(exc).__name__)
        reason = 'error'
    finally:
        if token_ledger.pending:
            record('provider_no_action', {}, {'error':{'code':reason}})
        if env_id:
            cleanup_deadline = max(deadline, clock() + config.request_timeout)
            try:
                state = client.status(env_id, cleanup_deadline)['state']
                if state != 'running':
                    terminal = client.result(env_id, cleanup_deadline)
                    reason = state
            except Exception as exc:
                errors.append('result:' + type(exc).__name__)
            try:
                client.delete(env_id, cleanup_deadline)
            except Exception as exc:
                errors.append('cleanup:' + type(exc).__name__)
        action_log.close()
        usage_log.close()
        if client_owned:
            client.close()
        complete = bool(terminal and terminal.get('complete'))
        summary = dict(env_id=env_id, run_id=run_id, reason=reason, complete=complete,
                       classification='completed' if complete else ('failed' if reason in ('error','unavailable') else 'budget_truncated'),
                       terminal=terminal, last_public_snapshot=latest, errors=errors,
                       usage=dict(calls=calls, input_tokens=input_tokens, output_tokens=output_tokens,
                                  total_tokens=input_tokens+output_tokens, tokens_by_day=token_ledger.by_day(),
                                  cost_usd=cost if has_cost else None, wall_seconds=clock()-started,
                                  action_latency_mean_seconds=sum(action_latencies)/len(action_latencies) if action_latencies else None,
                                  action_latency_max_seconds=max(action_latencies, default=None)),
                       evaluator=dict(seed=config.seed, scenario_id=config.scenario_id,
                                      environment_name=config.environment_name, environment_sha256=definition_hash),
                       truncated_accounting_artifact=f'{env_id}.json' if not terminal and env_id else None)
        (directory / 'summary.json').write_text(json.dumps(summary, indent=2))
    return directory, summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', help='RunConfig JSON file')
    parser.add_argument('--agent', choices=['idle','listed','negotiating','model'])
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('--model')
    parser.add_argument('--run-name', help='Readable experiment label for the run folder and viewer')
    parser.add_argument('--provider', choices=['anthropic','vllm'])
    parser.add_argument('--model-base-url', help='vLLM endpoint including /v1')
    parser.add_argument('--environment', help='Saved environment name, without .json')
    parser.add_argument('--environments-dir')
    parser.add_argument('--local', action='store_true', help='Start and stop a private local HTTP service')
    args = parser.parse_args()
    config = RunConfig.model_validate_json(Path(args.config).read_text()) if args.config else RunConfig()
    overrides = {}
    if args.run_name:
        overrides['run_name'] = args.run_name
    if args.environment:
        overrides['environment_name'] = args.environment
    if args.environments_dir:
        overrides['environments_dir'] = args.environments_dir
    if args.agent:
        overrides['agent'] = args.agent
    if args.smoke and (args.environment or config.environment_name):
        parser.error('--smoke cannot override a saved environment; generate a smoke definition instead')
    if args.smoke:
        overrides.update(scenario_id='smoke-v1', max_days=14, runtime_seconds=120)
    if args.provider:
        overrides['provider'] = args.provider
    if args.model:
        overrides.update(model=args.model, provider=args.provider or config.provider or 'anthropic')
    if args.model_base_url:
        overrides['vllm'] = VLLMSettings.model_validate(config.vllm.model_dump() | dict(base_url=args.model_base_url))
    config = RunConfig.model_validate(config.model_dump() | overrides)
    adapter = None
    if config.agent == 'model':
        if not config.model:
            parser.error('model agent requires an explicit model')
        if config.provider == 'anthropic':
            from .provider import AnthropicAdapter
            adapter = AnthropicAdapter(config.model)
        elif config.provider == 'vllm':
            from .vllm_provider import VLLMAdapter
            adapter = VLLMAdapter(config.model, config.vllm)
        else:
            parser.error('model agent requires provider anthropic or vllm')
    try:
        if args.local:
            from .local_service import local_service
            with local_service(config.environments_dir, config.artifact_dir) as url:
                local_config = RunConfig.model_validate(config.model_dump() | dict(service_url=url))
                directory, summary = run(local_config, adapter=adapter)
        else:
            directory, summary = run(config, adapter=adapter)
    finally:
        if adapter is not None and hasattr(adapter, 'close'):
            adapter.close()
    print(json.dumps({'directory':str(directory), 'reason':summary['reason'], 'complete':summary['complete']}))
    if summary['classification'] == 'failed':
        raise SystemExit(1)

if __name__ == '__main__':
    main()
