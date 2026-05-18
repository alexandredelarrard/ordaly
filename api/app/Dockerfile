FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

WORKDIR /app
COPY . /app

RUN apt-get update &&\
    apt-get install -y --no-install-recommends \
        gcc \
        poppler-utils \
        ghostscript \
        qpdf \
        libglib2.0-0 \
        libgl1 \
    && rm -rf /var/lib/apt/lists/*

# Install requirements
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt \
    && python -c "import camelot; import cv2; print('camelot', camelot.__version__, 'cv2 OK')"

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
