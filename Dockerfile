FROM python:3.13-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv using recommended Docker method
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy dependency files first for better caching
COPY pyproject.toml .
COPY uv.lock .
COPY README.md .

# Install dependencies using uv
RUN uv sync --frozen

# Copy application code
COPY framework/ framework/
COPY scripts/ scripts/
COPY main.py .

# Create necessary directories
RUN mkdir -p logs data output trading_state

# Set Python path
ENV PYTHONPATH=/app

# Run the trading bot with uv
CMD ["uv", "run", "python", "main.py"]