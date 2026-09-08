# HealthChat Web — production image.
# Build from the repository root:  docker build -f webapp/Dockerfile -t healthchat .
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HEALTHCHAT_DATA_DIR=/data

WORKDIR /app

COPY webapp/requirements.txt ./webapp/requirements.txt
RUN pip install --no-cache-dir -r webapp/requirements.txt

# Shared core modules (unchanged from the desktop build) + the web layer.
COPY ai_client.py calorie_calc.py fitbit_handler.py garmin_db.py garmin_handler.py \
     strava_handler.py withings_handler.py xai_client.py ./
COPY webapp ./webapp

RUN mkdir -p /data && useradd --create-home --uid 10001 healthchat && chown -R healthchat /data /app
USER healthchat

VOLUME ["/data"]
EXPOSE 8000

CMD ["uvicorn", "webapp.backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
