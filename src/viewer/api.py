"""Standalone local dashboard; intentionally has no simulation mutation routes."""
import argparse
from importlib.resources import files
from pathlib import Path
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, Response, JSONResponse
from .store import RunStore, RunNotFound


def create_app(runs_dir='runs', service_dir=None):
    app = FastAPI(title='Vending run viewer')
    store = RunStore(runs_dir, service_dir)
    app.state.store = store
    assets = files('viewer').joinpath('static')

    @app.exception_handler(RunNotFound)
    async def missing(request, exc):
        return JSONResponse({'error':'Run not found'}, status_code=404)

    @app.get('/', response_class=HTMLResponse)
    def home():
        return assets.joinpath('index.html').read_text()

    @app.get('/assets/{name}')
    def asset(name: str):
        types = {'app.js':'text/javascript', 'style.css':'text/css'}
        if name not in types:
            return Response(status_code=404)
        return Response(assets.joinpath(name).read_text(), media_type=types[name])

    @app.get('/api/runs')
    def runs(q: str = '', classification: str = '', offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
        return store.list_runs(q, classification, offset, limit)

    @app.get('/api/runs/{run_id}')
    def detail(run_id: str):
        return store.detail(run_id)

    @app.get('/api/runs/{run_id}/actions')
    def actions(run_id: str, action: str = '', offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
        return store.actions(run_id, action, offset, limit)

    @app.middleware('http')
    async def headers(request, call_next):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; object-src 'none'; frame-ancestors 'none'"
        return response
    return app


def main():
    import uvicorn
    parser = argparse.ArgumentParser(description='View recorded vending runs in your browser')
    parser.add_argument('--runs-dir', default='runs')
    parser.add_argument('--service-dir', help='Trusted pre-deletion summaries; defaults to RUNS_DIR/service')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()
    print(f'Run viewer: http://{args.host}:{args.port}  |  {Path(args.runs_dir).resolve()}', flush=True)
    uvicorn.run(create_app(args.runs_dir, args.service_dir), host=args.host, port=args.port)

if __name__ == '__main__':
    main()
