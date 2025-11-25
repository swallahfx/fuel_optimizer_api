FROM python:3.12-slim-bookworm

# Python optimizations
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install only what's needed to compile psycopg2 + run gunicorn
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first (best practice for caching)
COPY requirements.txt .

# Install Python packages (this layer is cached unless requirements change)
RUN pip install --no-cache-dir -r requirements.txt

# Create non-root user
RUN adduser --disabled-password --gecos '' appuser

# Copy code as non-root user
COPY --chown=appuser:appuser . .

# Switch to non-root user
USER appuser

# Collect static files
RUN python manage.py collectstatic --noinput --clear

EXPOSE 8000

# Gunicorn will now be found because it was installed above
CMD ["gunicorn", "fuel_optimizer.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120"]