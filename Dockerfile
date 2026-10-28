# One image for everything: the API (default) and the wiki refresh job
# (same image, different command, see docker-compose.yml and infra/).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

# install packages first so Docker can reuse this layer when only my code changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ajworth ./ajworth

# don't run as root inside the container
RUN useradd --create-home app && mkdir -p /app/data && chown app /app/data   # fetch.py writes its JSON cache here
USER app

EXPOSE 8000
CMD ["uvicorn", "ajworth.api:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
