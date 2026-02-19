FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (eccodes for GRIB2 parsing)
RUN apt-get update && apt-get install -y \
    gcc \
    libeccodes-dev \
    libeccodes-tools \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

ENV PYTHONPATH=/app

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
