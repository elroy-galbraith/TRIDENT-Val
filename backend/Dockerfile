FROM python:3.12-slim
# libgomp1: LightGBM's OpenMP runtime. The rest: WeasyPrint's text-shaping stack (Pango +
# Fontconfig via cffi, see app/reports.py) — named at the pango/fontconfig level only so apt
# resolves glib/harfbuzz transitively, since their own package names vary across Debian
# releases. WeasyPrint itself needs no cairo/GDK-Pixbuf (v53+ renders via a pure-Python
# backend); fonts-liberation gives it a metric-compatible sans/serif/mono family to render with.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 libpango-1.0-0 libpangoft2-1.0-0 libfontconfig1 fonts-liberation \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend /srv/backend
COPY model /srv/model
COPY scripts /srv/scripts
COPY data /srv/data
ENV PYTHONPATH=/srv/backend:/srv/scripts
# Baked once at build time, not at container startup: this profiles the static Ames CSV
# directly (no DB needed) and adding it to wait_and_seed.py would tax every container boot
# for output that doesn't change between deploys of the same data (see ADR 0019).
RUN python scripts/generate_profile_report.py
EXPOSE 8000
CMD ["sh", "-c", "python scripts/wait_and_seed.py && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
