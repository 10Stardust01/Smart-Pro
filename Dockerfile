# SMART-PRO Django runtime. Credentials and academic data remain outside the image.
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    DJANGO_SETTINGS_MODULE=smartpro.settings
RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements-lock.txt ./requirements-lock.txt
COPY backend/requirements.txt backend/requirements-render.txt ./backend/
RUN python -m pip install --no-cache-dir -r backend/requirements-render.txt
COPY . .
RUN useradd --system --home-dir /app --no-create-home smartpro
USER smartpro
EXPOSE 10000
CMD ["sh", "-c", "THREADS=${SMARTPRO_GUNICORN_THREADS:-4}; case \"$THREADS\" in 4|6|8) ;; *) echo \"Invalid bounded SMARTPRO_GUNICORN_THREADS\" >&2; exit 1 ;; esac; exec gunicorn smartpro.wsgi:application --bind 0.0.0.0:$PORT --workers 1 --threads \"$THREADS\" --timeout 90 --access-logfile - --error-logfile -"]
