FROM python:3.12-slim
WORKDIR /srv
COPY vendor_api/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY vendor_api /srv
EXPOSE 8001
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8001}"]
