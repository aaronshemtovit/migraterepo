# Use a lightweight Python base image
FROM python:3.12-slim

# Install git (needed by GitPython for certain operations)
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

# Copy your script + requirements file
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the migration script, .env file and repos
COPY migrate.py .
COPY .env .
COPY repos_to_migrate.txt .

# Optionally set environment variables here or at runtime
# ENV GITLAB_TOKEN=??? 
# ENV GITHUB_TOKEN=???

# By default, just show usage. You can override the CMD at runtime.
CMD ["python", "migrate.py", "--help"]
