# Build-Kontext ist der Projekt-Hauptordner (siehe docker-compose.yml: context: ..)
FROM python:3.12-slim

WORKDIR /app

COPY webapp/requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt

# Kern-Module aus dem Hauptordner (alle, damit keins vergessen wird)
COPY *.py ./
# Web-App
COPY webapp/ ./webapp/
# Backup-Skript mitliefern – so laesst es sich per
# docker cp ev-tracker:/app/backup.sh . auf den Host holen
COPY backup.sh ./backup.sh

# Datenbank liegt im Volume /data
ENV EV_TRACKER_DB=/data/ev_tracker.db
VOLUME /data

EXPOSE 8000
CMD ["uvicorn", "webapp.app:app", "--host", "0.0.0.0", "--port", "8000"]
