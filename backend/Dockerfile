FROM python:3.12-slim

# Outils de conversion : Tesseract (OCR fr/en), Ghostscript (PDF/A), LibreOffice (bureautique -> PDF/A)
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-fra tesseract-ocr-eng ghostscript \
        libreoffice-writer-nogui libreoffice-calc-nogui libreoffice-impress-nogui \
        fonts-dejavu unpaper pngquant curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY sql ./sql
COPY scripts ./scripts

RUN useradd -r -u 1001 siged && mkdir -p /data && chown -R siged /app /data
USER siged
ENV PYTHONUNBUFFERED=1 HOME=/tmp
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD curl -fs http://localhost:8000/health || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", "--proxy-headers", "--forwarded-allow-ips", "*"]
