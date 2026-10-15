FROM python:3.11-slim
ARG INSTALL_EVAL=0
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt requirements-eval.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
 && if [ "$INSTALL_EVAL" = "1" ]; then pip install --no-cache-dir -r requirements-eval.txt; fi
# Run as an unprivileged user. /cache (fastembed models) and /tmp/prom (metrics) must be
# writable by it; Chainlit also writes .chainlit/ into the working directory.
RUN useradd --create-home --uid 10001 app \
 && mkdir -p /cache /tmp/prom \
 && chown -R app:app /cache /tmp/prom /app
COPY --chown=app:app . .
# App title for the chat UI (the generated .chainlit/ folder itself is not in the image).
RUN mkdir -p /app/.chainlit && cp ui/chainlit.toml /app/.chainlit/config.toml \
 && chown -R app:app /app/.chainlit
RUN sed -i "s/\r$//" scripts/entrypoint.sh && chmod +x scripts/entrypoint.sh
USER app
ENTRYPOINT ["/app/scripts/entrypoint.sh"]
