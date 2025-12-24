FROM python:3.12-slim

# Évite les bugs d’encodage
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Dépendances système
RUN apt update && apt install -y \
    ffmpeg \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# yt-dlp
RUN pip install --no-cache-dir yt-dlp

# Dossier app
WORKDIR /app

# Dépendances Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code
COPY YTMM_bot_v3.4_fixed.py .

# Lancement
CMD ["python", "YTMM_bot_v3.4_fixed.py"]
