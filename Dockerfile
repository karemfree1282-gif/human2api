FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    gir1.2-gtk-3.0 \
    gir1.2-atk-1.0 \
    python3-gi \
    tigervnc-standalone-server \
    xdotool \
    dpkg-dev \
    && rm -rf /var/lib/apt/lists/*

COPY . /app
RUN pip install --no-cache-dir -e ".[browser,vault,signing]"

EXPOSE 8000
CMD ["python3", "scripts/complete.py", "--repair"]
