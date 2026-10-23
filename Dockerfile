FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# The 325 MB database is built here from the 60 MB dataset zip (~30 s), so it is never uploaded.
COPY app app
COPY etl etl
COPY starcoach-dataset-v16-cap300-csv.zip /tmp/dataset.zip
RUN mkdir -p data && python etl/build_db.py /tmp/dataset.zip data/torob.db && rm /tmp/dataset.zip
EXPOSE 8000
# Liara's proxy sets X-Forwarded-For; the chat rate limit keys on the client IP.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
