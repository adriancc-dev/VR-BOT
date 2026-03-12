from config import INITIAL_ELO, K_FACTOR, RANK_EMOJIS
from utils.i18n import translate_rank

def get_k_factor(elo: float) -> float:
    """
    Calcula el K-Factor variable según el rango (similar a LoL/Valorant).
    Rangos más bajos ganan/pierden más puntos, rangos más altos menos.
    
    Args:
        elo: ELO del jugador
    
    Returns:
        K-Factor ajustado según el rango
    """
    # principiante a hierro: k factor alto (40)
    if elo < 400:
        return 40
    # bronce a plata: k factor medio alto (35)
    elif elo < 1000:
        return 35
    # oro a platino: k factor medio (32)
    elif elo < 1900:
        return 32
    # esmeralda a diamante: k factor medio bajo (28)
    elif elo < 3400:
        return 28
    # promesa y predator: k factor bajo (24)
    elif elo < 4500:
        return 24
    # leyenda: k factor muy bajo (20)
    else:
        return 20

def get_min_win(elo: float) -> float:
    """
    Calcula el mínimo ELO que puedes ganar según tu rango.
    En rangos altos, el mínimo es menor para evitar inflación.
    
    Args:
        elo: ELO del jugador
    
    Returns:
        Mínimo ELO que puedes ganar
    """
    if elo < 1000:
        return 10  # rangos bajos
    elif elo < 2500:
        return 8   # rangos medios
    else:
        return 5   # rangos altos

def get_min_loss(elo: float) -> float:
    """
    Calcula el mínimo ELO que puedes perder según tu rango.
    En rangos altos, el mínimo es menor (pierdes menos).
    
    Args:
        elo: ELO del jugador
    
    Returns:
        Mínimo ELO que puedes perder (negativo)
    """
    if elo < 1000:
        return -8   # rangos bajos
    elif elo < 2500:
        return -6   # rangos medios
    else:
        return -4   # rangos altos

def get_streak_bonus(win_streak: int) -> float:
    """
    Calcula el bonus de ELO basado en la racha de victorias consecutivas.
    
    Tabla de bonus:
    - 0-2 victorias: +0
    - 3-4 victorias: +2
    - 5-7 victorias: +4
    - 8-9 victorias: +6
    - 10+ victorias: +8 (máximo)
    
    Args:
        win_streak: Racha actual de victorias consecutivas
    
    Returns:
        float: Bonus de ELO (0-8)
    """
    if win_streak < 3:
        return 0.0
    elif win_streak <= 4:
        return 2.0
    elif win_streak <= 7:
        return 4.0
    elif win_streak <= 9:
        return 6.0
    else:
        return 8.0

def calculate_elo(player1_elo: float, player2_elo: float, player1_won: bool, player1_streak: int = 0, player2_streak: int = 0) -> tuple:
    """
    Calcula el cambio de ELO para ambos jugadores usando un sistema similar a LoL.
    
    Características (tipo LoL):
    - K-Factor variable según el rango (más alto en rangos bajos, más bajo en altos)
    - Considera la diferencia de ELO (ganar contra alguien más fuerte da más puntos)
    - Rompe la simetría: ganas más ELO del que pierdes (controlado por rango)
    - Protección contra derrotas: pierdes menos si tu oponente es más fuerte
    - Límites (clamps) ajustados para mayor dinamismo
    - Bonus por racha de victorias (solo al ganador)
    - Control de inflación: menos inflación en rangos altos
    - Los empates no afectan el ELO (deben manejarse antes de llamar esta función)
    
    Args:
        player1_elo: ELO del jugador 1
        player2_elo: ELO del jugador 2
        player1_won: True si el jugador 1 ganó, False si perdió
        player1_streak: Racha actual de victorias del jugador 1 (antes de esta victoria)
        player2_streak: Racha actual de victorias del jugador 2 (antes de esta victoria)
    
    Returns:
        tuple: (elo_change_player1, elo_change_player2, streak_bonus_player1, streak_bonus_player2)
               elo_change1/elo_change2 YA INCLUYEN el bonus de racha (base + streak).
               Debe sumarse este total al ELO del jugador; los bonus de racha son 0 para el perdedor.
    """
    # calcular k factor promedio de ambos jugadores
    k1 = get_k_factor(player1_elo)
    k2 = get_k_factor(player2_elo)
    avg_k = (k1 + k2) / 2
    
    # calcular probabilidad esperada de victoria
    # usar 450 como divisor para ajustar el peso de la diferencia de elo
    expected_score1 = 1 / (1 + 10 ** ((player2_elo - player1_elo) / 450))
    expected_score2 = 1 - expected_score1
    
    # resultado actual (1.0 = victoria, 0.0 = derrota)
    actual_score1 = 1.0 if player1_won else 0.0
    actual_score2 = 1.0 - actual_score1
    
    # calcular cambio base de elo
    base_change1 = avg_k * (actual_score1 - expected_score1)
    base_change2 = avg_k * (actual_score2 - expected_score2)
    
    # romper simetria con control de inflacion, en rangos altos, menos inflacion para mantener estabilidad
    max_elo = max(player1_elo, player2_elo)
    
    if max_elo > 3000:
        # rangos altos
        WIN_MULT = 1.05
        LOSS_MULT = 0.95
    else:
        # rangos bajos/medios
        WIN_MULT = 1.10
        LOSS_MULT = 0.90
    
    if player1_won:
        # jugador 1 gana: aplicar multiplicador de victoria
        elo_change1 = base_change1 * WIN_MULT
        # jugador 2 pierde: aplicar multiplicador de derrota
        elo_change2 = base_change2 * LOSS_MULT
        
        # proteccion si pierdes contra alguien mas fuerte
        if player2_elo > player1_elo:
            # jugador 2 perdio contra alguien mas fuerte
            elo_change2 *= 0.75
    else:
        # jugador 2 gana: aplicar multiplicador de victoria
        elo_change2 = base_change2 * WIN_MULT
        # jugador 1 pierde: aplicar multiplicador de derrota
        elo_change1 = base_change1 * LOSS_MULT
        
        # proteccion si pierdes contra alguien mas fuerte
        if player1_elo > player2_elo:
            # jugador 1 perdio contra alguien mas fuerte
            elo_change1 *= 0.75
    
    # bonus por racha
    streak_bonus1 = 0.0
    streak_bonus2 = 0.0
    
    # lmites de elo sin bonus de racha
    MAX_WIN = 40
    MIN_WIN = 15
    MAX_LOSS = -35
    MIN_LOSS = -12
    
    # aplicar clamps al cambio base
    if elo_change1 > 0:
        elo_change1 = min(max(elo_change1, MIN_WIN), MAX_WIN)
    else:
        elo_change1 = max(min(elo_change1, MIN_LOSS), MAX_LOSS)
    
    if elo_change2 > 0:
        elo_change2 = min(max(elo_change2, MIN_WIN), MAX_WIN)
    else:
        elo_change2 = max(min(elo_change2, MIN_LOSS), MAX_LOSS)
    
    # sumar bonus de racha al elo ganado (el ganador recibe base + bonus)
    if player1_won:
        streak_bonus1 = get_streak_bonus(player1_streak)
        elo_change1 += streak_bonus1  # total = base + racha
    else:
        streak_bonus2 = get_streak_bonus(player2_streak)
        elo_change2 += streak_bonus2  # total = base + racha
    
    return (elo_change1, elo_change2, streak_bonus1, streak_bonus2)

def calculate_team_war_elo(player1_elo: float, player2_elo: float, player1_won: bool, war_type: str = "amistoso") -> tuple:
    """
    Calcula el cambio de ELO específico para guerras de equipo.
    Sistema diferente al ELO individual 1v1, diseñado para partidas de equipo.
    
    Características del sistema de guerra de equipo:
    - K-Factor fijo más alto (más recompensa/riesgo)
    - Multiplicadores según tipo de guerra integrados
    - Sistema más simple y directo
    - Mayor variabilidad en cambios de ELO
    
    Args:
        player1_elo: ELO del jugador 1
        player2_elo: ELO del jugador 2
        player1_won: True si el jugador 1 ganó, False si perdió
        war_type: "amistoso" o "competicion"
    
    Returns:
        tuple: (elo_change_player1, elo_change_player2)
    """
    
    # k factor fijo mas alto para guerras de equipo

    TEAM_WAR_K_FACTOR = 35  # fijo para todas las guerras de equipo
    
    # calcular probabilidad esperada de victoria
    expected_score1 = 1 / (1 + 10 ** ((player2_elo - player1_elo) / 400))
    expected_score2 = 1 - expected_score1
    
    # resultado actual (1.0 = victoria, 0.0 = derrota)
    actual_score1 = 1.0 if player1_won else 0.0
    actual_score2 = 1.0 - actual_score1
    
    # calcular cambio base de ELO
    base_change1 = TEAM_WAR_K_FACTOR * (actual_score1 - expected_score1)
    base_change2 = TEAM_WAR_K_FACTOR * (actual_score2 - expected_score2)
    
    # multiplicadores segun tipo de guerra
    if war_type == "competicion":
        
        # modo competicion se gana 150% mas
        multiplier = 1.5
    else:
        # modo amistoso se gana solo el 50%
        multiplier = 0.5
    
    elo_change1 = base_change1 * multiplier
    elo_change2 = base_change2 * multiplier
    
    # limites para guerras de equipo
    MAX_WIN = 50 if war_type == "competicion" else 25  # + elo en competicion
    MIN_WIN = 5  # minimo siempre de 5
    
    MAX_LOSS = -40 if war_type == "competicion" else -20  # - elo en competicion
    MIN_LOSS = -5  # minimo siempre de -5
    
    if elo_change1 > 0:
        elo_change1 = min(max(elo_change1, MIN_WIN), MAX_WIN)
    else:
        elo_change1 = max(min(elo_change1, MIN_LOSS), MAX_LOSS)
    
    if elo_change2 > 0:
        elo_change2 = min(max(elo_change2, MIN_WIN), MAX_WIN)
    else:
        elo_change2 = max(min(elo_change2, MIN_LOSS), MAX_LOSS)
    
    return (elo_change1, elo_change2)

def get_rank_from_elo(elo: float) -> str:
    """
    Convierte ELO a rango con divisiones.
    Rangos: Principiante, Hierro III/I, Bronce III/I, Plata III/I, Oro III/I,
    Platino III/I, Esmeralda III/I, Diamante III/I, Promesa, Predator, Leyenda
    Distribución: 0-5000 puntos
    """
    
    if elo < 100:
        return "Principiante"

    elif elo < 200:
        return "Hierro III"
    elif elo < 300:
        return "Hierro II"
    elif elo < 400:
        return "Hierro I"

    elif elo < 500:
        return "Bronce III"
    elif elo < 600:
        return "Bronce II"
    elif elo < 700:
        return "Bronce I"
 
    elif elo < 800:
        return "Plata III"
    elif elo < 900:
        return "Plata II"
    elif elo < 1000:
        return "Plata I"

    elif elo < 1150:
        return "Oro III"
    elif elo < 1300:
        return "Oro II"
    elif elo < 1450:
        return "Oro I"

    elif elo < 1600:
        return "Platino III"
    elif elo < 1750:
        return "Platino II"
    elif elo < 1900:
        return "Platino I"

    elif elo < 2100:
        return "Esmeralda III"
    elif elo < 2300:
        return "Esmeralda II"
    elif elo < 2500:
        return "Esmeralda I"

    elif elo < 2800:
        return "Diamante III"
    elif elo < 3100:
        return "Diamante II"
    elif elo < 3400:
        return "Diamante I"

    elif elo < 3900:
        return "Promesa"

    elif elo < 4500:
        return "Predator"

    else:
        return "Leyenda"

def get_league_from_rank(rank: str) -> str:
    """
    Extrae la liga base de un rango (sin la división).
    Ejemplo: "Plata III" -> "Plata", "Diamante I" -> "Diamante", "Promesa" -> "Promesa"
    
    Args:
        rank: Rango completo (ej: "Plata III", "Diamante I", "Promesa")
    
    Returns:
        str: Liga base (Principiante, Hierro, Bronce, Plata, Oro, Platino, Esmeralda, Diamante, Promesa, Predator, Leyenda)
    """
    
    # rangos sin divisiones
    if rank in ["Principiante", "Promesa", "Predator", "Leyenda"]:
        return rank
    
    # rangos con divisiones, extraer la liga base

    parts = rank.split()
    if len(parts) >= 1:
        return parts[0]  # retornar la primera parte, la liga
    return rank  # fallback: retornar el rango completo si no se puede parsear

def get_league_difference(rank1: str, rank2: str) -> int:
    """
    Calcula la diferencia de ligas entre dos rangos.
    Retorna el número de ligas de diferencia (0 = misma liga, 1 = 1 liga de diferencia, etc.)
    
    Args:
        rank1: Rango del primer jugador
        rank2: Rango del segundo jugador
    
    Returns:
        int: Diferencia de ligas (número absoluto)
    """
    # orden de las ligas de menor a mayor
    league_order = [
        "Principiante",
        "Hierro",
        "Bronce",
        "Plata",
        "Oro",
        "Platino",
        "Esmeralda",
        "Diamante",
        "Promesa",
        "Predator",
        "Leyenda"
    ]
    
    league1 = get_league_from_rank(rank1)
    league2 = get_league_from_rank(rank2)
    
    try:
        index1 = league_order.index(league1)
        index2 = league_order.index(league2)
        return abs(index1 - index2)
    except ValueError:
        
        # si alguna liga no esta en la lista, retornar diferencia maxima
        return 999

def get_rank_emoji(rank: str) -> str:
    """
    Retorna el emoji correspondiente al rango.
    Usa emojis personalizados si están configurados, sino usa los predeterminados.
    Busca primero emojis específicos por división (ej: hierro_i, hierro_ii, hierro_iii),
    luego emojis generales por rango (ej: hierro), y finalmente usa los predeterminados.
    
    Args:
        rank: Nombre del rango (ej: "Principiante", "Hierro III", "Oro I", etc.)
    
    Returns:
        Emoji personalizado (formato <:nombre:ID>) o emoji Unicode predeterminado
    """
    
    # emojis predeterminados como fallback
    default_emojis = {
        "Principiante": "🌱",
        "Hierro": "⚙️",
        "Bronce": "🥉",
        "Plata": "🥈",
        "Oro": "🥇",
        "Platino": "💎",
        "Esmeralda": "💚",
        "Diamante": "💠",
        "Promesa": "⭐",
        "Predator": "🦁",
        "Leyenda": "👑",
    }
    
    # normalizar el nombre del rango para buscar en el diccionario
    rank_lower = rank.lower()
    
    # determinar la clave especifica del rango con division
    rank_key = None
    
    # rangos sin divisiones
    if "principiante" in rank_lower:
        rank_key = 'principiante'
    elif "promesa" in rank_lower:
        rank_key = 'promesa'
    elif "predator" in rank_lower:
        rank_key = 'predator'
    elif "leyenda" in rank_lower:
        rank_key = 'leyenda'
    # rangos con divisiones
    elif "hierro" in rank_lower:
        if "iii" in rank_lower:
            rank_key = 'hierro_iii'
        elif "ii" in rank_lower:
            rank_key = 'hierro_ii'
        elif "i" in rank_lower:
            rank_key = 'hierro_i'
        else:
            rank_key = 'hierro'  # fallback general
    elif "bronce" in rank_lower:
        if "iii" in rank_lower:
            rank_key = 'bronce_iii'
        elif "ii" in rank_lower:
            rank_key = 'bronce_ii'
        elif "i" in rank_lower:
            rank_key = 'bronce_i'
        else:
            rank_key = 'bronce'  # fallback general
    elif "plata" in rank_lower:
        if "iii" in rank_lower:
            rank_key = 'plata_iii'
        elif "ii" in rank_lower:
            rank_key = 'plata_ii'
        elif "i" in rank_lower:
            rank_key = 'plata_i'
        else:
            rank_key = 'plata'  # fallback general
    elif "oro" in rank_lower:
        if "iii" in rank_lower:
            rank_key = 'oro_iii'
        elif "ii" in rank_lower:
            rank_key = 'oro_ii'
        elif "i" in rank_lower:
            rank_key = 'oro_i'
        else:
            rank_key = 'oro'  # fallback general
    elif "platino" in rank_lower:
        if "iii" in rank_lower:
            rank_key = 'platino_iii'
        elif "ii" in rank_lower:
            rank_key = 'platino_ii'
        elif "i" in rank_lower:
            rank_key = 'platino_i'
        else:
            rank_key = 'platino'  # fallback general
    elif "esmeralda" in rank_lower:
        if "iii" in rank_lower:
            rank_key = 'esmeralda_iii'
        elif "ii" in rank_lower:
            rank_key = 'esmeralda_ii'
        elif "i" in rank_lower:
            rank_key = 'esmeralda_i'
        else:
            rank_key = 'esmeralda'  # fallback general
    elif "diamante" in rank_lower:
        if "iii" in rank_lower:
            rank_key = 'diamante_iii'
        elif "ii" in rank_lower:
            rank_key = 'diamante_ii'
        elif "i" in rank_lower:
            rank_key = 'diamante_i'
        else:
            rank_key = 'diamante'  # fallback general
    
    # buscar emoji personalizado, primero la division y luego el rango
    if rank_key:
        # intentar con la clave especifica primero
        custom_emoji = RANK_EMOJIS.get(rank_key)
        if custom_emoji:
            # verificar que el formato sea correcto
            if custom_emoji.startswith('<:') or custom_emoji.startswith('<a:'):
                return custom_emoji
        
        # si no hay emoji específico, intentar con el rango general (solo para rangos con divisiones)
        if '_' in rank_key:
            general_key = rank_key.split('_')[0]  # extraer solo el nombre del rango
            general_emoji = RANK_EMOJIS.get(general_key)
            if general_emoji:
                if general_emoji.startswith('<:') or general_emoji.startswith('<a:'):
                    return general_emoji
    
    # usar emoji predeterminado
    for default_rank, emoji in default_emojis.items():
        if default_rank.lower() in rank_lower:
            return emoji
    
    # fallback final
    return "🏆"

