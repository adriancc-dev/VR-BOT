import discord
from typing import Optional
from database.models import Player, Match
from utils.elo import get_rank_from_elo, get_rank_emoji
from utils.i18n import get_player_translator, get_translator, translate_rank
from config import is_elo_bonus_event_active, ELO_BONUS_WIN_MULTIPLIER, ELO_BONUS_LOSS_MULTIPLIER

def create_matchmaking_embed(player: Player, match_type: str, is_anonymous: bool, hint: Optional[str] = None, role_mention: str = "") -> discord.Embed:
    """Crea un embed atractivo para una solicitud de matchmaking (siempre anónima)"""
    t = get_player_translator(player)
    
    # Construir descripción con mención del rol si está disponible
    if role_mention:
        description = t.t('matchmaking.description', role_mention=role_mention)
    else:
        description = t.t('matchmaking.description_no_role')
    
    embed = discord.Embed(
        title=t.t('matchmaking.title'),
        description=description,
        color=discord.Color.blue()
    )
    
    embed.add_field(name=t.t('matchmaking.mode'), value=t.t('matchmaking.mode_value'), inline=True)
    
    # mostrar algo creativo en lugar de la pista de elo
    creative_hints = [
        "⚡ ¡Listo para la acción!",
        "🔥 ¡Que comience el partido!",
        "⚽ ¡Hora de jugar!",
        "🎯 ¡Busco un buen rival!",
        "💪 ¡Preparado para competir!",
        "🏆 ¡En busca de victoria!",
        "⚔️ ¡Desafiando a cualquiera!",
        "🌟 ¡Listo para brillar!",
        "🚀 ¡Vamos a jugar!",
        "🎮 ¡Partida en busca!",
        "💥 ¡Energía al máximo!",
        "🎪 ¡El espectáculo comienza!",
        "🔥 ¡Fuego en la cancha!",
        "⚡ ¡Carga completa!",
        "🏃 ¡A toda velocidad!",
    ]

    import random
    creative_hint = random.choice(creative_hints)
    embed.add_field(name=t.t('matchmaking.hint'), value=creative_hint, inline=False)
    
    embed.set_footer(text=t.t('matchmaking.footer'))
    embed.timestamp = discord.utils.utcnow()
    
    return embed

def create_score_report_embed(reporter: discord.Member, opponent: discord.Member, score1: int, score2: int, player: Optional[Player] = None) -> discord.Embed:
    """Crea un embed para reportar el resultado de una partida (similar a primera imagen)"""
    t = get_player_translator(player) if player else get_translator('es')
    
    embed = discord.Embed(
        title=t.t('match.score_report.title'),
        description=t.t('match.score_report.description'),
        color=discord.Color.blue()
    )
    
    # marcador destacado
    score_display = f"{reporter.mention} **{score1}** VS **{score2}** {opponent.mention}"
    embed.add_field(
        name="",
        value=score_display,
        inline=False
    )
    
    # pregunta de confirmacion
    embed.add_field(
        name="",
        value=t.t('match.score_report.confirm_question', opponent=opponent.mention),
        inline=False
    )
    
    embed.set_footer(text=t.t('match.score_report.footer'))
    embed.timestamp = discord.utils.utcnow()
    
    return embed

def create_match_result_embed(match: Match, player1: Player, player2: Player, user1: Optional[discord.User] = None, user2: Optional[discord.User] = None, is_draw: bool = False, confirmed_by_user: Optional[discord.User] = None, stadium_image_url: Optional[str] = None, use_elo_1v1: bool = True, language: Optional[str] = None, player1_rank_before: Optional[str] = None, player2_rank_before: Optional[str] = None, player1_rank_after: Optional[str] = None, player2_rank_after: Optional[str] = None, player1_rank_up: bool = False, player2_rank_up: bool = False, player1_won: Optional[bool] = None, winner_streak: int = 0, winner_streak_bonus: float = 0.0, elo_bonus_active: bool = False, elo_bonus_win_mult: float = 2.0, elo_bonus_loss_mult: float = 1.5) -> discord.Embed:
    """Crea un embed para mostrar el resultado confirmado de una partida con temática Inazuma"""
    
    # obtener traductor (usar player1 como referencia si no se especifica idioma)
    if language:
        t = get_translator(language)
    else:
        t = get_player_translator(player1)
    
    # obtener nombres de usuario
    player1_name = user1.display_name if user1 else player1.username
    player2_name = user2.display_name if user2 else player2.username
    
    # obtener menciones si estan disponibles
    player1_mention = user1.mention if user1 else player1_name
    player2_mention = user2.mention if user2 else player2_name
    
    # obtener mencion del confirmador
    confirmed_by_mention = confirmed_by_user.mention if confirmed_by_user else f"<@{match.confirmed_by}>"
    
    # color tematica inazuma
    inazuma_blue = discord.Color.from_rgb(0, 102, 204)  # azul
    inazuma_green = discord.Color.from_rgb(0, 153, 51)  # verde
    
    embed = discord.Embed(
        title=t.t('match.result.title'),
        description=t.t('match.result.description', confirmed_by=confirmed_by_mention),
        color=inazuma_green if not is_draw else discord.Color.orange()
    )
    
    # Imagen de fondo (banner) con marcador superpuesto y fotos de perfil
    # el score ya esta en la imagen, no hace falta mostrarlo en el embed
    if stadium_image_url:
        embed.set_image(url=stadium_image_url)
    
    # estadisticas detalladas en columnas debajo de los nombres
    if not is_draw:
        # elo total, mostramos desglose (partida + racha) para el ganador con racha
        c1 = match.elo_change1 or 0
        c2 = match.elo_change2 or 0
        if player1_won and winner_streak_bonus and winner_streak_bonus > 0 and c1 > 0:
            base1 = c1 - winner_streak_bonus
            elo1_change = f"+{c1:.0f} (+{base1:.0f} {t.t('match.result.elo_from_match')}, +{winner_streak_bonus:.0f} {t.t('match.result.elo_from_streak')})"
        else:
            elo1_change = f"+{c1:.0f}" if c1 > 0 else f"{c1:.0f}"
        if not player1_won and winner_streak_bonus and winner_streak_bonus > 0 and c2 > 0:
            base2 = c2 - winner_streak_bonus
            elo2_change = f"+{c2:.0f} (+{base2:.0f} {t.t('match.result.elo_from_match')}, +{winner_streak_bonus:.0f} {t.t('match.result.elo_from_streak')})"
        else:
            elo2_change = f"+{c2:.0f}" if c2 > 0 else f"{c2:.0f}"
        
        # obtener elo actualizado despues de la actualizacion
        if use_elo_1v1:
            player1_elo = player1.elo_1v1 if player1.elo_1v1 is not None else 0
            player2_elo = player2.elo_1v1 if player2.elo_1v1 is not None else 0
        else:
            player1_elo = player1.elo
            player2_elo = player2.elo
        
        # mostrar avatares de ambos jugadores
        if user1 and user1.avatar:
            embed.set_author(name=player1_name, icon_url=user1.avatar.url)
        else:
            embed.set_author(name=player1_name)
        
        # usar el logo de victory road como thumbnail (esquina superior derecha), url del logo oficial
        inazuma_logo_url = "https://i.imgur.com/lQ5CJ10.png"
        embed.set_thumbnail(url=inazuma_logo_url)
        
        # obtener rangos base y traducirlos
        player1_rank_base = player1_rank_after if player1_rank_after else get_rank_from_elo(player1_elo)
        player2_rank_base = player2_rank_after if player2_rank_after else get_rank_from_elo(player2_elo)
        
        # traducir rangos segun el idioma
        current_lang = language if language else (player1.language if player1 else 'es')
        player1_rank_text = translate_rank(player1_rank_base, current_lang)
        player2_rank_text = translate_rank(player2_rank_base, current_lang)
        
        # obtener emojis usando el rango base
        rank1_emoji = get_rank_emoji(player1_rank_base)
        rank2_emoji = get_rank_emoji(player2_rank_base)
        
        # formatear elo: actual + ganado
        player1_elo_display = f"{player1_elo:.0f} ({elo1_change})"
        player2_elo_display = f"{player2_elo:.0f} ({elo2_change})"
        
        # construir texto de estadisticas para jugador 1
        player1_stats_lines = [
            f"**{t.t('match.result.elo_label')}:** {player1_elo_display}",
            f"**{t.t('match.result.rank')}:** {rank1_emoji} {player1_rank_text}"
        ]
        
        # añadir mensaje de nuevo rango si subio
        if player1_rank_up and player1_rank_after:
            player1_rank_after_translated = translate_rank(player1_rank_after, current_lang)
            player1_stats_lines.append(f"\n**{t.t('match.result.new_rank_reached')}:** {rank1_emoji} {player1_rank_after_translated}")
        
        player1_stats_lines.append(f"\n**{t.t('match.result.xp')}:** +{match.xp_gained1}")
        
        # añadir racha y bonus de racha si es el ganador
        if player1_won and winner_streak > 0 and winner_streak_bonus > 0:
            player1_stats_lines.append(f"\n**{t.t('match.result.streak')}:** 🔥 {winner_streak} (+{winner_streak_bonus:.0f} ELO)")
        
        # construir texto de estadisticas para jugador 2
        player2_stats_lines = [
            f"**{t.t('match.result.elo_label')}:** {player2_elo_display}",
            f"**{t.t('match.result.rank')}:** {rank2_emoji} {player2_rank_text}"
        ]
        
        # añadir mensaje de nuevo rango si subio
        if player2_rank_up and player2_rank_after:
            player2_rank_after_translated = translate_rank(player2_rank_after, current_lang)
            player2_stats_lines.append(f"\n**{t.t('match.result.new_rank_reached')}:** {rank2_emoji} {player2_rank_after_translated}")
        
        player2_stats_lines.append(f"\n**{t.t('match.result.xp')}:** +{match.xp_gained2}")
        
        # añadir racha y bonus de racha si es el ganador
        if not player1_won and winner_streak > 0 and winner_streak_bonus > 0:
            player2_stats_lines.append(f"\n**{t.t('match.result.streak')}:** 🔥 {winner_streak} (+{winner_streak_bonus:.0f} ELO)")
        
        player1_stats = "\n".join(player1_stats_lines)
        player2_stats = "\n".join(player2_stats_lines)
        
        # determinar quien gano para el titulo de la columna e incluir el nombre del jugador
        if player1_won is not None:
            if player1_won:
                player1_title = f"🏆 {t.t('match.result.winner')}: {player1_name}"
                player2_title = f"❌ {t.t('match.result.loser')}: {player2_name}"
            else:
                player1_title = f"❌ {t.t('match.result.loser')}: {player1_name}"
                player2_title = f"🏆 {t.t('match.result.winner')}: {player2_name}"
        else:
            # si es empate usar nombres normales
            player1_title = f"👤 {player1_name}"
            player2_title = f"👤 {player2_name}"
        
        # agregar campos con estadisticas en columnas
        embed.add_field(
            name=player1_title,
            value=player1_stats,
            inline=True
        )
        embed.add_field(
            name=player2_title,
            value=player2_stats,
            inline=True
        )
    else:
        # empate: mostrar estadisticas con +0
        if user1 and user1.avatar:
            embed.set_author(name=player1_name, icon_url=user1.avatar.url)
        else:
            embed.set_author(name=player1_name)
        
        # usar el logo de victory road en la esquina superior derecha
        inazuma_logo_url = "https://i.imgur.com/lQ5CJ10.png"
        embed.set_thumbnail(url=inazuma_logo_url)
        
        # obtener elo actualizado
        if use_elo_1v1:
            player1_elo = player1.elo_1v1 if player1.elo_1v1 is not None else 0
            player2_elo = player2.elo_1v1 if player2.elo_1v1 is not None else 0
        else:
            player1_elo = player1.elo
            player2_elo = player2.elo
        
        # obtener rangos y traducirlos
        player1_rank_base = player1_rank_after if player1_rank_after else get_rank_from_elo(player1_elo)
        player2_rank_base = player2_rank_after if player2_rank_after else get_rank_from_elo(player2_elo)
        
        # traducir rangos segun el idioma
        current_lang = language if language else (player1.language if player1 else 'es')
        player1_rank_text = translate_rank(player1_rank_base, current_lang)
        player2_rank_text = translate_rank(player2_rank_base, current_lang)
        
        # obtener emojis usando el rango
        rank1_emoji = get_rank_emoji(player1_rank_base)
        rank2_emoji = get_rank_emoji(player2_rank_base)
        
        # formatear elo, en empate ambos suman 1-5 elo segun la diferencia
        draw_elo = match.elo_change1 or match.elo_change2 or 0
        draw_elo_str = f"+{draw_elo:.0f}" if draw_elo > 0 else "+0"
        player1_elo_display = f"{player1_elo:.0f} ({draw_elo_str})"
        player2_elo_display = f"{player2_elo:.0f} ({draw_elo_str})"
        
        # construir texto de estadisticas para jugador 1
        player1_stats_lines = [
            f"**{t.t('match.result.elo_label')}:** {player1_elo_display}",
            f"**{t.t('match.result.rank')}:** {rank1_emoji} {player1_rank_text}",
            f"\n**{t.t('match.result.xp')}:** +0"
        ]
        
        # construir texto de estadisticas para jugador 2
        player2_stats_lines = [
            f"**{t.t('match.result.elo_label')}:** {player2_elo_display}",
            f"**{t.t('match.result.rank')}:** {rank2_emoji} {player2_rank_text}",
            f"\n**{t.t('match.result.xp')}:** +0"
        ]
        
        player1_stats = "\n".join(player1_stats_lines)
        player2_stats = "\n".join(player2_stats_lines)
        
        # titulos para empate y obtener idioma del traductor
        current_lang = language if language else (player1.language if player1 else 'es')
        draw_text = "Empate" if current_lang == 'es' else ("Draw" if current_lang == 'en' else ("Égalité" if current_lang == 'fr' else "Pareggio"))
        player1_title = f"🤝 {draw_text}: {player1_name}"
        player2_title = f"🤝 {draw_text}: {player2_name}"
        
        # agregar campos con estadisticas
        embed.add_field(
            name=player1_title,
            value=player1_stats,
            inline=True # para mostrar columnas izquierda y derecha
        )
        embed.add_field(
            name=player2_title,
            value=player2_stats,
            inline=True # para mostrar columnas izquierda y derecha
        )
    
    embed.set_footer(text=t.t('match.result.footer'), icon_url="https://i.imgur.com/placeholder.png")
    embed.timestamp = match.confirmed_at
    return embed

def create_profile_embed(player: Player, user: Optional[discord.User] = None, team=None, avg_goals_scored: float = 0.0, avg_goals_conceded: float = 0.0) -> discord.Embed:
    """Crea un embed profesional para el perfil de un jugador"""
    t = get_player_translator(player)
    
    # titulo con mencion del usuario
    if user:
        # usar display name o el user
        user_name = user.display_name or user.name
        title = t.t('profile.title', name=user_name)
        # agregar la mencion en la descripcion para que funcione como mencion clickeable
        description = t.t('profile.description', user=user.mention)
    else:
        title = t.t('profile.title', name=player.username)
        description = None
    
    embed = discord.Embed(
        title=title,
        description=description,
        color=discord.Color.gold()
    )
    
    # avatar de discord como thumbnail en la esquina superior derecha
    if user and user.avatar:
        embed.set_thumbnail(url=user.avatar.url)
    
    # obtener elo y rango 1v1
    elo_1v1 = player.elo_1v1 if player.elo_1v1 is not None else 0
    rank_1v1 = get_rank_from_elo(elo_1v1)
    emoji_1v1 = get_rank_emoji(rank_1v1)

    ### LAYOUT PERFIL ###
    # primera fila: rango, nivel, estadisticas (3 columnas)
    embed.add_field(
        name=t.t('profile.rank'),
        value=f"{emoji_1v1} {rank_1v1}\n{elo_1v1:.0f} ELO",
        inline=True
    )
    embed.add_field(
        name=t.t('profile.level'),
        value=f"Lv. {player.level}\n{player.xp} XP",
        inline=True
    )
    # calcular win rate
    win_rate = player.win_rate()
    
    embed.add_field(
        name=t.t('profile.stats'),
        value=f"✅ {player.wins}W | ❌ {player.losses}L | 🤝 {player.draws}E\n{win_rate:.1f}% WR",
        inline=True
    )
    
    # segunda fila: promedios de goles, rachas y prestigio (3 columnas)
    embed.add_field(
        name=t.t('profile.avg_goals'),
        value=f"{t.t('profile.scored')}: {avg_goals_scored:.2f}\n{t.t('profile.conceded')}: {avg_goals_conceded:.2f}",
        inline=True
    )
    embed.add_field(
        name=t.t('profile.streaks'),
        value=f"{t.t('profile.current')}: {player.win_streak}\n{t.t('profile.best')}: {player.best_win_streak}",
        inline=True
    )
    # calcular y mostrar prestigio
    prestige_value = player.prestige()
    embed.add_field(
        name=t.t('profile.prestige'),
        value=f"{prestige_value:.2f}",
        inline=True
    )
    
    # equipo al final del embed
    if team:
        team_display = team.name
        if team.tag:
            team_display = f"{team.name} `{team.tag}`"
        
        # logo del equipo en el footer junto al nombre (logo antes del nombre)
        if team.logo_url:
            # mostrar el logo con el nombre del equipo en el footer
            footer_text = f"🏆 {team_display}"
            embed.set_footer(text=footer_text, icon_url=team.logo_url)
        else:
            # si no hay logo, mostrar solo el nombre del equipo
            footer_text = f"🏆 {team_display}"
            embed.set_footer(text=footer_text)
    
    return embed

