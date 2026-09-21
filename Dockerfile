FROM python:3.12-slim-bookworm AS app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY configs ./configs
COPY environments ./environments
COPY start_env.sh ./
COPY scripts ./scripts
RUN mkdir -p /app/runs

FROM app AS environment
CMD ["bash", "start_env.sh", "configs/environment.json"]

FROM app AS dashboard
CMD ["bash", "scripts/view_runs.sh", "--host", "0.0.0.0"]
