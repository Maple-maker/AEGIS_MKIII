FROM python:3.11-slim

# System dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY dashboard_server.py .
COPY sources/ ./sources/
COPY dashboard/ ./dashboard/

# Create data directories (Railway Volume will mount over /app/data)
RUN mkdir -p /app/config /app/data /app/briefs /app/audio

# Default env vars (overridden by Railway environment)
ENV PORT=8080
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["sh", "-c", "gunicorn dashboard_server:app --bind 0.0.0.0:${PORT:-8080} --workers 2 --threads 4 --timeout 120 --access-logfile - --error-logfile -"]
