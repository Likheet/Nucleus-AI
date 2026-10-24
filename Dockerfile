FROM python:3.12-slim

# Hugging Face Spaces runs containers as user 1000
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PORT=7860
WORKDIR $HOME/app

# Copy requirements first (Docker caching)
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY --chown=user . .

# Bake the embedding model into the image so startup doesn't download it
RUN python -m backend.embedder

# The prebuilt index (INDEX_URL) is downloaded into ./data on startup.
# Spaces expects port 7860; Render sets PORT itself.
EXPOSE 7860

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import os, httpx; httpx.get('http://localhost:%s/api/health' % os.getenv('PORT', '7860')).raise_for_status()" || exit 1

# Start the server
CMD ["sh", "-c", "uvicorn backend.server:app --host 0.0.0.0 --port ${PORT}"]
