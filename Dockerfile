FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# Copy application code
COPY . .

# Set environment variables
ENV PYTHONPATH=/app

# Run the application (Bot + API)
CMD ["python", "run_all.py"]
