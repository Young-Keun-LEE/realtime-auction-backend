FROM python:3.11-slim

## Set working directory
WORKDIR /code

## Install required system packages (for PostgreSQL connection)
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

## Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

## Copy entire project
COPY . .

## Run command (execute main.py in app folder)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]