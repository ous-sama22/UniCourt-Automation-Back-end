# Dockerfile
FROM mcr.microsoft.com/playwright/python:v1.42.0-focal


WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browser drivers
RUN playwright install --with-deps chromium 


# Copy the rest of the application
COPY . .

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

EXPOSE 8000 

CMD ["python", "app/main.py"]