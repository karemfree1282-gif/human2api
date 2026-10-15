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
# Keep the local API loopback-only. On Linux use --network host for local access.
CMD ["python3", "-m", "human2api", "start", "--no-browser", "--host", "127.0.0.1", "--port", "8000"]
