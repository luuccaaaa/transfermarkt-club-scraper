FROM python:3.9-slim-bullseye

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH="${PYTHONPATH}:/app"

WORKDIR /app

# Copy requirements and install dependencies
COPY api/transfermarkt_api/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY api/transfermarkt_api/ ./

CMD ["python", "app/main.py"]
