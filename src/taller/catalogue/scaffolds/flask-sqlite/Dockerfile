FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# The database lives in a mounted volume, never in the image.
RUN useradd --create-home app && mkdir -p /data && chown app /data
USER app
ENV DATABASE=/data/app.db

EXPOSE 8000
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "wsgi:app"]
