# Dockerfile para Inazuma VR Bot
FROM python:3.11-slim

# Establecer directorio de trabajo
WORKDIR /app

# Instalar dependencias del sistema necesarias (incluyendo fuentes para generación de imágenes)
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    postgresql-client \
    libpq-dev \
    libjpeg-dev \
    zlib1g-dev \
    fonts-dejavu \
    fonts-dejavu-core \
    fonts-dejavu-extra \
    fonts-liberation \
    fonts-liberation2 \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements primero para cachear dependencias
COPY requirements.txt .

# Usar espejo de PyPI (el builder de Fly a veces no alcanza pypi.org)
ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ENV PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn
ENV PIP_RETRIES=10
ENV PIP_TIMEOUT=120
# Instalar en dos pasos: primero discord.py, luego el resto
RUN pip install --no-cache-dir --upgrade pip && \
    for i in 1 2 3 4 5; do pip install --no-cache-dir "discord.py>=2.3.0" && break || sleep 20; done
RUN for i in 1 2 3 4 5; do pip install --no-cache-dir -r requirements.txt && break || sleep 20; done

# Copiar el resto del código
COPY . .

# Crear directorio para datos (por si acaso se usa SQLite como fallback)
RUN mkdir -p data backups

# Establecer variables de entorno por defecto
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Exponer puerto (aunque Discord bot no necesita puerto, Fly.io lo requiere)
EXPOSE 8080

# Health check simple (opcional, para Fly.io)
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python3 -c "import sys; sys.exit(0)" || exit 1

# Comando para ejecutar el bot
CMD ["python3", "bot.py"]


