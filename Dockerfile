FROM python:3.12-slim

WORKDIR /app

# Install deps first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code and config
COPY src/ ./src/
COPY config/ ./config/

# Run the bot
CMD ["python", "src/main.py"]