FROM node:22-bookworm-slim AS web-build
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build && npm run build:report

FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 ASTOCK_WEB_STATIC_DIR=/app/web/dist ASTOCK_SERVER_DATA_DIR=/app/server-data ASTOCK_DASHBOARD_HOST=0.0.0.0
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .
COPY --from=web-build /build/web/dist ./web/dist
COPY --from=web-build /build/web/report-dist ./web/report-dist
EXPOSE 18080
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:18080/healthz', timeout=3)"
CMD ["python", "-m", "astock.cli", "dashboard", "--port", "18080"]
