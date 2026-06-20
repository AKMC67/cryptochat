# syntax=docker/dockerfile:1
FROM python:3.12-slim
WORKDIR /app
COPY server.py ./
COPY static ./static
# No dependencies to install — server.py is pure standard library.
# Hosts that inject a PORT env var (Render, Railway, Fly, etc.) work automatically.
ENV HOST=0.0.0.0
EXPOSE 8765
CMD ["python3", "server.py"]
