FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PROCUREMENT_DB_PATH=/app/runtime/procurement.db \
    CONTRACTOR_CATALOG_PATH=/app/data/hackathon-dataset-anonymized.csv
WORKDIR /app
COPY requirements.txt requirements-ai.txt ./
ARG INSTALL_AI=0
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ "$INSTALL_AI" = "1" ]; then pip install --no-cache-dir -r requirements-ai.txt; fi
COPY backend ./backend
COPY frontend ./frontend
COPY data/*.json data/*.csv ./data/
RUN useradd --create-home --uid 10001 procureline \
    && mkdir /app/runtime && chown procureline:procureline /app/runtime
USER procureline
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"
CMD ["python", "-m", "uvicorn", "backend.api:app", "--host", "0.0.0.0", "--port", "8000"]
