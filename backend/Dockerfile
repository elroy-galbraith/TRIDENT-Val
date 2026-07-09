FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app /srv/app
COPY model /srv/model
COPY scripts /srv/scripts
COPY data /srv/data
ENV PYTHONPATH=/srv:/srv/scripts
EXPOSE 8000
CMD ["sh", "-c", "python scripts/wait_and_seed.py && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
