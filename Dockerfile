FROM python:3.10-slim

# Linux အတွင်း Google Chrome (Chromium) နှင့် Driver အမှန်ကို သွင်းခြင်း
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud Port အလိုက် အလိုအလျောက် မောင်းနှင်ခိုင်းခြင်း
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]