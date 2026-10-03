FROM python:3.13-slim
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt constraints.cpu.txt ./
# Oracle runs embeddings on CPU. The default PyPI torch wheel can pull CUDA
# libraries even on ARM servers, so install and constrain the CPU wheel first.
RUN pip install --no-cache-dir 'torch==2.10.0+cpu' --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt -c constraints.cpu.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
