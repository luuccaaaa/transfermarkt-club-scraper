FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Copy requirements and install dependencies
COPY api/workflow_app/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire project (needed for scripts access)
COPY . .

# Set the Python path to include the workflow_app directory
ENV PYTHONPATH="/app/api/workflow_app:/app"

CMD ["uvicorn", "api.workflow_app.main:app", "--host", "0.0.0.0", "--port", "8080"]
