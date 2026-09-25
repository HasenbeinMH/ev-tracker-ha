# Dockerfile fuer das Home-Assistant-Add-on (config.yaml im selben Ordner).
# Fuer den eigenstaendigen Docker-Betrieb (Portainer o.ae.) weiterhin
# webapp/Dockerfile + docker-compose.yml verwenden – die beiden Wege sind
# bewusst getrennt, damit sich Ingress-Port und Datenverzeichnis nicht
# gegenseitig beeinflussen.
FROM python:3.12-slim

WORKDIR /app

COPY webapp/requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt

# Kern-Module aus dem Hauptordner (alle, damit keins vergessen wird)
COPY *.py ./
# Web-App
COPY webapp/ ./webapp/
# Galerie der Fahrzeugbilder (Einstellungen → Fahrzeugbild); final/ ist Arbeitsordner
COPY fahrzeugbilder/ ./fahrzeugbilder/

# Datenverzeichnis: vom Supervisor per config.yaml "map: [data:rw]" bereitgestellt
ENV EV_TRACKER_DB=/data/ev_tracker.db

# Muss zum ingress_port in config.yaml passen
EXPOSE 8099
CMD ["uvicorn", "webapp.app:app", "--host", "0.0.0.0", "--port", "8099"]
