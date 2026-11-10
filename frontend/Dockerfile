# Production Dockerfile for ApexHome & Electro Frontend on Google Cloud Run
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    GOOGLE_GENAI_USE_VERTEXAI=true \
    GOOGLE_CLOUD_LOCATION=global \
    VERTEX_AI_LOCATION=global \
    PORT=8080

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements across project and install
COPY frontend/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy all application components
COPY . /app

EXPOSE 8080

CMD exec gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 120 frontend.app:app
