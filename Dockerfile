FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.cargo/bin:${PATH}"

# Copy dependency files first for better caching
COPY pyproject.toml .
COPY uv.lock .

# Install dependencies using uv
RUN uv sync --frozen

# Copy application code
COPY framework/ framework/
COPY scripts/ scripts/
COPY main.py .

# Create necessary directories
RUN mkdir -p logs data output

# Set Python path
ENV PYTHONPATH=/app

# Run the trading bot with uv
CMD ["uv", "run", "python", "main.py"]