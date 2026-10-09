FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt tzdata
COPY src ./src
COPY deployment/cloud_runner.py ./deployment/cloud_runner.py
ENV AGENT_ROOT=/data AGENT_LIVE_ENABLED=false
CMD ["python", "deployment/cloud_runner.py"]
