FROM python:3.12-slim-bookworm

# Install uv (from official binary), nodejs, npm, git, and docker
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    docker.io \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js and npm via NodeSource 
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Confirm npm and node versions (optional debugging info)
RUN node -v && npm -v

# Copy your mcpo source code
COPY . /app
WORKDIR /app

# Create virtual environment explicitly in known location
ENV VIRTUAL_ENV=/app/.venv
RUN uv venv "$VIRTUAL_ENV"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Install mcpo (assuming pyproject.toml is properly configured)
RUN uv pip install . && rm -rf ~/.cache

# Verify mcpo installed correctly
RUN which mcpo

# Add config.json to the container
COPY config.json /app/config.json

# Expose ports for all services in config.json
EXPOSE 8000  # Add additional ports as required

# Entrypoint set for easy container invocation
ENTRYPOINT ["mcpo", "--config", "/app/config.json"]