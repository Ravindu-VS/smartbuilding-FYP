FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV WSO2_AM_URL=https://wso2am:8243
ENV REDIS_HOST=redis
ENV POSTGRES_HOST=postgres

# Expose backend port
EXPOSE 8001

# Command to run the application (the live system's backend; run_system.py was removed)
CMD ["python", "raspberry_pi/edge_brain.py"]
