FROM python:3.12-slim AS build

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
RUN pip install --no-cache-dir uv==0.9.29
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim AS runtime

ARG BUILD_SHA=unknown
ENV BUILD_SHA=${BUILD_SHA} \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000
WORKDIR /app
RUN useradd --create-home --uid 10001 scienceagent
COPY --from=build /app/.venv /app/.venv
COPY --chmod=755 entrypoint.sh /app/entrypoint.sh
USER scienceagent
EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
