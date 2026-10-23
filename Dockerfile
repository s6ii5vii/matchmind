# MatchMind: the dashboard and the API in one container.

# 1. Build the dashboard to static files
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
ENV STATIC_EXPORT=1 NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# 2. The API, serving the dashboard too
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000 MATCHMIND_STATIC=/app/static
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY --from=web /web/out ./static
RUN useradd --create-home matchmind
USER matchmind
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers"]
