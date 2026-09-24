FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /code

COPY pyproject.toml ./
COPY app ./app

RUN pip install .

# Run as an unprivileged user. Installed above as root (pip needs to write
# to site-packages); everything after this line runs without root rights.
RUN useradd --create-home --shell /usr/sbin/nologin appuser
USER appuser

# Documentation only; the platform decides the real port via $PORT.
EXPOSE 8000

# Shell form so ${PORT} is expanded; `exec` replaces the shell with uvicorn so
# uvicorn is PID 1 and receives SIGTERM directly, allowing a graceful shutdown.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]