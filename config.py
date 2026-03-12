import os
from dotenv import load_dotenv

load_dotenv()

# Discord Configuration
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
# Manejar DISCORD_GUILD_ID de forma segura
_guild_id = os.getenv('DISCORD_GUILD_ID', '0')
try:
    DISCORD_GUILD_ID = int(_guild_id) if _guild_id and _guild_id != 'tu_guild_id' else 0
except ValueError:
    DISCORD_GUILD_ID = 0

# Lista de servidores permitidos (lista blanca)
# Si está vacía, el bot funcionará en todos los servidores
# Formato: ALLOWED_GUILD_IDS=123456789,987654321
_allowed_guild_ids_str = os.getenv('ALLOWED_GUILD_IDS', '')
ALLOWED_GUILD_IDS = []
if _allowed_guild_ids_str:
    try:
        ALLOWED_GUILD_IDS = [int(guild_id.strip()) for guild_id in _allowed_guild_ids_str.split(',') if guild_id.strip()]
    except ValueError:
        ALLOWED_GUILD_IDS = []

# Database Configuration
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///data/database.db')

# Game Configuration
GAME_MODES = {
    '1v1': {'name': '1vs1', 'players_per_team': 1},
    '5v5': {'name': '5vs5', 'players_per_team': 5}
}

# Ranking Configuration
INITIAL_ELO = 0  # Todos empiezan desde el rango más bajo (Principiante)
K_FACTOR = 32  # Factor K base (ahora se calcula dinámicamente según rango)
MIN_ELO = 0
MAX_ELO = 5000  # ELO máximo (Leyenda)

# ELO Configuration (similar a LoL/Valorant)
# K-Factor variable según rango:
# - Principiante-Hierro: 40 (alta volatilidad)
# - Bronce-Plata: 35
# - Oro-Platino: 32
# - Esmeralda-Diamante: 28
# - Promesa-Predator: 24
# - Leyenda: 20 (baja volatilidad)

# XP Configuration
XP_WIN = 50
XP_LOSS = 10
XP_BONUS_MULTIPLIER = 1.5  # Para partidas contra oponentes de mayor rango

# Match Result Configuration
# URL de la imagen de estadio/banner para mostrar en los resultados de partidas
# Debe ser una URL pública accesible. Si es None, no se mostrará imagen de fondo.
# Ejemplo: "https://i.imgur.com/estadio-inazuma.png"
STADIUM_IMAGE_URL = os.getenv('STADIUM_IMAGE_URL', None)
# URL de respaldo por si la principal devuelve 404/expira (opcional)
STADIUM_IMAGE_URL_FALLBACK = os.getenv('STADIUM_IMAGE_URL_FALLBACK', None)

# Challonge Configuration
# Challonge Connect (OAuth - Nuevo método)
CHALLONGE_CLIENT_ID = os.getenv('CHALLONGE_CLIENT_ID', '')
CHALLONGE_CLIENT_SECRET = os.getenv('CHALLONGE_CLIENT_SECRET', '')
CHALLONGE_NAME = os.getenv('CHALLONGE_NAME', 'NexoVR')
# API v1 (Legacy - para cuentas antiguas)
CHALLONGE_USERNAME = os.getenv('CHALLONGE_USERNAME', '')
CHALLONGE_API_KEY = os.getenv('CHALLONGE_API_KEY', '')

# Matchmaking Webhook Configuration
# URL de webhook personalizada para mensajes anónimos de matchmaking
# Si se configura, se usará esta webhook en lugar de crear una nueva
# Formato: https://discord.com/api/webhooks/WEBHOOK_ID/WEBHOOK_TOKEN
MATCHMAKING_WEBHOOK_URL = os.getenv('MATCHMAKING_WEBHOOK_URL', None)
# Nombre personalizado para la webhook (solo si se usa webhook personalizada)
MATCHMAKING_WEBHOOK_NAME = os.getenv('MATCHMAKING_WEBHOOK_NAME', 'Anonymous')
# Avatar URL personalizado para la webhook (solo si se usa webhook personalizada)
# Si es None, no se mostrará avatar (completamente anónimo)
MATCHMAKING_WEBHOOK_AVATAR_URL = os.getenv('MATCHMAKING_WEBHOOK_AVATAR_URL', None)

# Admin Configuration
# Lista de IDs de Discord de administradores (separados por comas)
# Estos usuarios pueden aceptar scores aunque no sean suyos
# Ejemplo: ADMIN_IDS=123456789,987654321
_admin_ids_str = os.getenv('ADMIN_IDS', '')
ADMIN_IDS = [int(admin_id.strip()) for admin_id in _admin_ids_str.split(',') if admin_id.strip()] if _admin_ids_str else []

# ELO Bonus Event Configuration
# Configuración para eventos temporales de bonificación de ELO
# Formato de fecha: YYYY-MM-DD HH:MM:SS (UTC) o None para desactivar
# Ejemplo: ELO_BONUS_EVENT_START=2024-01-15 00:00:00
_elo_bonus_start_str = os.getenv('ELO_BONUS_EVENT_START', None)
ELO_BONUS_EVENT_START = None
if _elo_bonus_start_str:
    try:
        from datetime import datetime
        ELO_BONUS_EVENT_START = datetime.strptime(_elo_bonus_start_str, '%Y-%m-%d %H:%M:%S')
    except:
        ELO_BONUS_EVENT_START = None

# Duración del evento en días (por defecto 3 días)
ELO_BONUS_EVENT_DURATION_DAYS = int(os.getenv('ELO_BONUS_EVENT_DURATION_DAYS', '3'))

# Multiplicadores de ELO durante el evento
# ELO ganado se multiplica por este valor (por defecto x2)
ELO_BONUS_WIN_MULTIPLIER = float(os.getenv('ELO_BONUS_WIN_MULTIPLIER', '2.0'))
# ELO perdido se multiplica por este valor (por defecto x1.5)
ELO_BONUS_LOSS_MULTIPLIER = float(os.getenv('ELO_BONUS_LOSS_MULTIPLIER', '1.5'))

def is_elo_bonus_event_active():
    """
    Verifica si el evento de bonificación de ELO está actualmente activo.
    
    Returns:
        bool: True si el evento está activo, False en caso contrario
    """
    if not ELO_BONUS_EVENT_START:
        return False
    
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    event_end = ELO_BONUS_EVENT_START + timedelta(days=ELO_BONUS_EVENT_DURATION_DAYS)
    
    return ELO_BONUS_EVENT_START <= now <= event_end

# Rank Emojis Configuration
# Emojis personalizados para los rangos (formato: <:nombre:ID> o <a:nombre:ID> para animados)
# Si no se configuran, se usarán los emojis predeterminados Unicode
# Para obtener el ID: Activa Modo Desarrollador en Discord > Clic derecho en emoji > Copiar ID
# Puedes configurar emojis específicos por división (ej: hierro_i, hierro_ii, hierro_iii)
# o emojis generales por rango (ej: hierro). El sistema buscará primero la división específica,
# luego el rango general, y finalmente usará el emoji predeterminado.
RANK_EMOJIS = {
    # Rangos sin divisiones
    'principiante': os.getenv('RANK_EMOJI_PRINCIPIANTE', None),
    'promesa': os.getenv('RANK_EMOJI_PROMESA', None),
    'predator': os.getenv('RANK_EMOJI_PREDATOR', None),
    'leyenda': os.getenv('RANK_EMOJI_LEYENDA', None),
    
    # Hierro (divisiones específicas)
    'hierro_iii': os.getenv('RANK_EMOJI_HIERRO_III', None),
    'hierro_ii': os.getenv('RANK_EMOJI_HIERRO_II', None),
    'hierro_i': os.getenv('RANK_EMOJI_HIERRO_I', None),
    'hierro': os.getenv('RANK_EMOJI_HIERRO', None),  # Fallback general
    
    # Bronce (divisiones específicas)
    'bronce_iii': os.getenv('RANK_EMOJI_BRONCE_III', None),
    'bronce_ii': os.getenv('RANK_EMOJI_BRONCE_II', None),
    'bronce_i': os.getenv('RANK_EMOJI_BRONCE_I', None),
    'bronce': os.getenv('RANK_EMOJI_BRONCE', None),  # Fallback general
    
    # Plata (divisiones específicas)
    'plata_iii': os.getenv('RANK_EMOJI_PLATA_III', None),
    'plata_ii': os.getenv('RANK_EMOJI_PLATA_II', None),
    'plata_i': os.getenv('RANK_EMOJI_PLATA_I', None),
    'plata': os.getenv('RANK_EMOJI_PLATA', None),  # Fallback general
    
    # Oro (divisiones específicas)
    'oro_iii': os.getenv('RANK_EMOJI_ORO_III', None),
    'oro_ii': os.getenv('RANK_EMOJI_ORO_II', None),
    'oro_i': os.getenv('RANK_EMOJI_ORO_I', None),
    'oro': os.getenv('RANK_EMOJI_ORO', None),  # Fallback general
    
    # Platino (divisiones específicas)
    'platino_iii': os.getenv('RANK_EMOJI_PLATINO_III', None),
    'platino_ii': os.getenv('RANK_EMOJI_PLATINO_II', None),
    'platino_i': os.getenv('RANK_EMOJI_PLATINO_I', None),
    'platino': os.getenv('RANK_EMOJI_PLATINO', None),  # Fallback general
    
    # Esmeralda (divisiones específicas)
    'esmeralda_iii': os.getenv('RANK_EMOJI_ESMERALDA_III', None),
    'esmeralda_ii': os.getenv('RANK_EMOJI_ESMERALDA_II', None),
    'esmeralda_i': os.getenv('RANK_EMOJI_ESMERALDA_I', None),
    'esmeralda': os.getenv('RANK_EMOJI_ESMERALDA', None),  # Fallback general
    
    # Diamante (divisiones específicas)
    'diamante_iii': os.getenv('RANK_EMOJI_DIAMANTE_III', None),
    'diamante_ii': os.getenv('RANK_EMOJI_DIAMANTE_II', None),
    'diamante_i': os.getenv('RANK_EMOJI_DIAMANTE_I', None),
    'diamante': os.getenv('RANK_EMOJI_DIAMANTE', None),  # Fallback general
}