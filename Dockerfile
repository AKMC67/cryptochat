FROM python:3.12-slim
WORKDIR /app
COPY server.py ./
COPY static ./static
ENV HOST=0.0.0.0
EXPOSE 8765
CMD ["python3", "server.py"]
