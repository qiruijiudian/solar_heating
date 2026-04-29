FROM python:3.11-slim

LABEL maintainer="Solar Heating Team"
LABEL description="Solar Thermal Storage Design Study Application"
LABEL version="1.0"

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV SOLAR_PORT=8003
ENV SOLAR_HOST=0.0.0.0

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p "01 input files" "02 reports" \
    && chmod -R 755 /app

EXPOSE 8003

HEALTHCHECK --interval=180s --timeout=60s --start-period=300s --retries=2 \
    CMD curl -f --connect-timeout 10 --max-time 30 http://localhost:8003/ || exit 1

CMD ["python", "start_server.py", "--host", "0.0.0.0", "--port", "8003"]

