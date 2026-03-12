# INAZUMA VR BOT

Bot de Discord para comunidades competitivas, con matchmaking anonimo, sistema de ELO, gestion de equipos y torneos.

Este repositorio esta pensado como version portfolio para mostrar arquitectura, buenas practicas y despliegue.

## Funcionalidades principales

- Matchmaking anonimo (`/matchmaking`, `/cancel-matchmaking`)
- Reporte y validacion de resultados (`/score`, `/host`)
- Ranking ELO por jugadores y equipos (`/leaderboard`, `/profile`, `/ranks`)
- Sistema de equipos (creacion, gestion, logo)
- Torneos con flujo de creacion, reporte y cierre
- Soporte multiidioma (`/language`)
- Comandos de administracion para sincronizacion y mantenimiento

## Stack tecnico

- Python 3.11+
- `discord.py` (slash commands)
- SQLAlchemy + SQLite/PostgreSQL
- Docker + Fly.io (opcional)

## Estructura del proyecto

- `bot.py`: punto de entrada del bot
- `config.py`: carga y parseo de variables de entorno
- `cogs/`: comandos slash por dominio funcional
- `database/`: modelos e inicializacion de base de datos
- `utils/`: logica reutilizable (ELO, embeds, i18n, etc.)
- `locales/`: traducciones del bot

## Instalacion local

1. Crear y activar entorno virtual
2. Instalar dependencias
3. Configurar variables
4. Ejecutar el bot

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python bot.py
```

## Variables de entorno

Usa `.env.example` como base. Variables obligatorias:

- `DISCORD_TOKEN`
- `DATABASE_URL` (por defecto sqlite local)

Variables opcionales:

- `ALLOWED_GUILD_IDS`, `DISCORD_GUILD_ID`
- `ADMIN_IDS`
- Integraciones de torneos (`CHALLONGE_*`)
- Configuracion visual/webhook (`STADIUM_IMAGE_URL`, `MATCHMAKING_WEBHOOK_URL`)

## Despliegue (opcional)

Incluye `Dockerfile` y `fly.toml` para despliegue en Fly.io.

## Seguridad y uso de este repositorio

- Nunca subas `.env` ni backups con secretos.
- Este repositorio no incluye claves, tokens ni credenciales reales.
- Si eres reclutador/a y quieres revisar la version completa de produccion, puedo compartir acceso privado durante el proceso.

## Estado del proyecto

Proyecto funcional y en mejora continua. Enfocado en automatizar la gestion competitiva dentro de Discord para comunidades de gaming.
