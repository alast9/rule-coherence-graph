# Hosted RCG MCP server (streamable HTTP). See docs/hosted-mcp.md.
FROM python:3.11-slim

WORKDIR /app

# Copy project sources and metadata needed to build the wheel.
COPY pyproject.toml README.md ./
COPY src ./src

# Install runtime extras only (no dev tooling) to keep the image lean.
RUN pip install --no-cache-dir '.[mcp,embeddings]'

# Serve over streamable HTTP by default; the stdio default is for local clients.
ENV RCG_MCP_TRANSPORT=streamable-http \
    PORT=8080

EXPOSE 8080

CMD ["rcg-mcp"]
