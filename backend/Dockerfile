FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Upgrade pip
RUN pip install --upgrade pip wheel

# Copy requirements and constraints
COPY requirements.txt constraints.txt ./

# Install Python dependencies with constraints applied to build isolation
ENV PIP_CONSTRAINT=/app/constraints.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directories
RUN mkdir -p /app/data/videos /app/data/processed_videos /app/data/results

# Expose port
EXPOSE 8000

# Default command - run the API
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
