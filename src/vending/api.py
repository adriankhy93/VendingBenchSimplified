import asyncio
from contextlib import asynccontextmanager
import json
import os
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import Field, ValidationError
from starlette.concurrency import run_in_threadpool
from .config import Scenario, StrictModel
from .registry import APIError, Registry
from .models import ACTIONS, Created, Status, ActionResponse

class Create(StrictModel):
    environment_name: str | None = None
    environment_sha256: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')
    scenario_id: str | None = None
    seed: int | None = Field(default=None, ge=0, le=2**63 - 1)
    runtime_seconds: int | None = Field(default=None, gt=0)
    max_days: int | None = Field(default=None, gt=0)

async def body(request):
    raw = await request.body()
    if not raw:
        return {}
    try:
        return json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeDecodeError) as exc:
        raise APIError(400, "invalid_json", "Body must be valid finite JSON") from exc

class BodyLimit:
    def __init__(self, app, limit=65536):
        self.app, self.limit = app, limit
    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            size += len(message.get('body', b''))
            if size > self.limit:
                response = JSONResponse({"error": {"code": "body_too_large", "message": "Body exceeds 65536 bytes"}}, status_code=413)
                return await response(scope, receive, send)
            chunks.append(message)
            if not message.get('more_body', False):
                break
        async def replay():
            return chunks.pop(0) if chunks else await receive()
        await self.app(scope, replay, send)

def create_app(registry=None):
    if registry is None:
        path = os.getenv('VENDING_SCENARIO')
        scenario = Scenario.model_validate_json(open(path).read()) if path else Scenario()
        registry = Registry(scenario, artifact_dir=os.getenv('VENDING_ARTIFACT_DIR', 'runs/service'),
                            environments_dir=os.getenv('VENDING_ENVIRONMENTS_DIR', 'environments'))

    @asynccontextmanager
    async def lifespan(app):
        async def sweep():
            while True:
                await asyncio.sleep(1)
                await run_in_threadpool(registry.sweep)
        task = asyncio.create_task(sweep())
        yield
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    app = FastAPI(title="Simplified Vending Bench", lifespan=lifespan)
    app.state.registry = registry
    app.add_middleware(BodyLimit)

    @app.exception_handler(APIError)
    async def error(request, exc):
        return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status)

    @app.post('/env', status_code=201, response_model=Created)
    async def create(request: Request):
        data = await body(request)
        try:
            model = Create.model_validate(data)
            options = model.model_dump(exclude_unset=True)
            if any(value is None for key, value in options.items() if key != 'max_days'):
                raise ValueError('null evaluator option')
            env_id = await run_in_threadpool(registry.create, options)
        except (ValidationError, ValueError) as exc:
            raise APIError(422, 'invalid_configuration', 'Invalid evaluator configuration') from exc
        return {"env_id": env_id}

    @app.get('/env/{env_id}/status', response_model=Status)
    def status(env_id: str):
        return registry.status(env_id)

    @app.get('/env/{env_id}/result')
    def result(env_id: str):
        return registry.result(env_id)

    @app.delete('/env/{env_id}', status_code=204)
    def delete(env_id: str):
        registry.delete(env_id)
        return Response(status_code=204)

    @app.post('/env/{env_id}/{action}', response_model=ActionResponse, response_model_exclude_unset=True)
    async def action(env_id: str, action: str, request: Request):
        # Resolve lifecycle before parsing to keep terminal/unknown-action precedence.
        def preflight():
            entry = registry.lookup(env_id)
            with entry.lock:
                registry.check(env_id, entry)
                if action not in ACTIONS or entry.state != 'running':
                    registry.action(env_id, action, {}, request.headers.get('Idempotency-Key'))
        await run_in_threadpool(preflight)
        try:
            payload = await body(request)
        except APIError:
            registry.invalid(env_id)
            raise
        return await run_in_threadpool(registry.action, env_id, action, payload, request.headers.get('Idempotency-Key'))
    return app

app = create_app()
