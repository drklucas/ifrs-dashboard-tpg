FROM mcr.microsoft.com/playwright/python:v1.58.0-noble

WORKDIR /app

COPY scraper/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY scraper/ ./scraper/
COPY templates/ ./templates/

RUN mkdir -p data output

CMD ["python", "scraper/main.py"]
