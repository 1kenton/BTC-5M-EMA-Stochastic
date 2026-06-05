FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"
# Cache bust
RUN echo "Bust: $(date +%s%N)" > /tmp/bust
COPY pyproject.toml ./
COPY hermes_trading ./hermes_trading
COPY state ./state
RUN /root/.local/bin/uv sync --no-cache
ENV HERMES_TRADING_MODE=paper
CMD ["/root/.local/bin/uv", "run", "python", "-m", "hermes_trading.run"]
