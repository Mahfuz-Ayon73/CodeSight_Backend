FROM python:3.11-slim

WORKDIR /app

# Install system dependencies needed for scikit-learn / hdbscan compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the sentence-transformers model at build time
# This avoids a cold-start timeout on the first analysis request
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Copy application code
COPY . .

# HF Spaces runs as a non-root user
RUN useradd -m appuser && chown -R appuser /app
USER appuser

EXPOSE 7860

# HF Spaces injects PORT=7860; our main.py already reads it
CMD ["python", "main.py"]
