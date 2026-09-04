FROM mcr.microsoft.com/playwright/python:v1.61.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RPA_HEADLESS=true \
    PORT=8000

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000

# Processo padrao no Railway: a API HTTP, que cria o schema na subida.
# O CLI continua acessivel sobrescrevendo o comando, por exemplo:
#   docker run --rm -v "$PWD/dados:/dados" IMAGEM \
#     copercitrus-price collect /dados/produtos.xlsx --output /dados/precos.xlsx
CMD ["sh", "-c", "exec uvicorn copercitrus_price_collector.web:app --host 0.0.0.0 --port ${PORT:-8000}"]
