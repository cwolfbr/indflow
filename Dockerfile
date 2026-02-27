# Usar a imagem oficial do Python com suporte a Playwright
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# Configurar diretório de trabalho
WORKDIR /app

# Copiar requirements.txt e instalar dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Instalar navegadores do Playwright (Chromium apenas para otimizar espaço)
RUN playwright install chromium

# Copiar o restante do código
COPY . .

# Criar diretórios de downloads e garantir permissões
RUN mkdir -p downloads/xlsx downloads/zips downloads/pdfs && \
    chmod -R 777 downloads

# Expor a porta que a aplicação vai rodar
EXPOSE 8000

# Comando para iniciar a aplicação via módulo worker.api
CMD ["python", "-m", "worker.api"]
