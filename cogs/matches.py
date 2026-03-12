import discord
from discord import app_commands
from discord.ext import commands
from database.database import get_db
from database.models import Player, Match, Team, TeamMember
from utils.embeds import create_match_result_embed, create_score_report_embed
from utils.elo import calculate_elo, get_rank_from_elo
from utils.rank_roles import update_member_rank_roles
from utils.i18n import get_player_translator, get_translator
from config import (
    XP_WIN,
    XP_LOSS,
    XP_BONUS_MULTIPLIER,
    STADIUM_IMAGE_URL,
    STADIUM_IMAGE_URL_FALLBACK,
    ADMIN_IDS,
    is_elo_bonus_event_active,
    ELO_BONUS_WIN_MULTIPLIER,
    ELO_BONUS_LOSS_MULTIPLIER,
)
from datetime import datetime
from sqlalchemy import and_, or_
import random

class MatchesCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="score", description="Reporta el resultado de una partida")
    @app_commands.describe(
        myscore="Tu puntuación",
        opponentscore="Puntuación del oponente",
        opponent="Usuario oponente",
        game="Tipo de partida (opcional)"
    )
    async def score(
        self,
        interaction: discord.Interaction,
        myscore: int,
        opponentscore: int,
        opponent: discord.Member,
        game: str = None
    ):
        # verificar primero que el oponente no sea el mismo usuario (validacion rapida sin base de datos)
        if interaction.user.id == opponent.id:
            await interaction.response.send_message(
                "❌ No puedes reportar un score contra ti mismo.",
                ephemeral=True
            )
            return
        
        # responder inmediatamente para evitar timeout
        await interaction.response.defer(ephemeral=False)
        
        try:
            with get_db() as db:

                # obtener jugador reporter primero para obtener su idioma
                reporter = db.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
                t = get_player_translator(reporter) if reporter else get_translator('es')
                
                # obtener jugador oponente
                opponent_player = db.query(Player).filter(Player.discord_id == str(opponent.id)).first()
                
                if not reporter:
                    reporter = Player(
                        discord_id=str(interaction.user.id),
                        username=interaction.user.name
                    )
                    db.add(reporter)
                    db.commit()
                    db.refresh(reporter)
                
                if not opponent_player:
                    opponent_player = Player(
                        discord_id=str(opponent.id),
                        username=opponent.name
                    )
                    db.add(opponent_player)
                    db.commit()
                    db.refresh(opponent_player)
                
                # buscar partida pendiente o crear nueva
                match = db.query(Match).filter(
                    and_(
                        or_(
                            and_(Match.player1_id == reporter.id, Match.player2_id == opponent_player.id),
                            and_(Match.player1_id == opponent_player.id, Match.player2_id == reporter.id)
                        ),
                        Match.status.in_(['pending', 'reported'])
                    )
                ).first()
                
                if not match:

                    # crear nueva partida
                    match = Match(
                        match_type=game or '1v1',
                        player1_id=reporter.id,
                        player2_id=opponent_player.id,
                        status='reported'
                    )
                    db.add(match)
                else:
                    match.status = 'reported'
                
                # determinar quien es player1 y player2
                if match.player1_id == reporter.id:
                    match.score1 = myscore
                    match.score2 = opponentscore
                else:
                    match.score1 = opponentscore
                    match.score2 = myscore
                
                match.reported_by = reporter.id
                match.reported_at = datetime.utcnow()
                db.commit()
                db.refresh(match)
                
                # crear embed de confirmacion mejorado
                embed = create_score_report_embed(interaction.user, opponent, myscore, opponentscore, reporter)
                
                view = ConfirmMatchView(match.id, reporter.id, opponent_player.id, interaction.user.id, opponent.id)
                
                # enviar mensaje de notificacion y embed en el mismo mensaje
                mensaje_notificacion = f"{interaction.user.mention} ha reportado un score con tu nombre {opponent.mention}."
                
                # usar followup porque ya hicimos defer()
                await interaction.followup.send(content=mensaje_notificacion, embed=embed, view=view, ephemeral=False)
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"❌ Error en comando score: {e}")
            try:
                
                # intentar enviar mensaje de error
                await interaction.followup.send(
                    f"❌ Ocurrió un error al procesar el score. Por favor, intenta de nuevo.\nError: {str(e)}",
                    ephemeral=True
                )
            except:
                
                # si falla el followup, intentar con response
                try:
                    if not interaction.response.is_done():
                        await interaction.response.send_message(
                            f"❌ Ocurrió un error al procesar el score. Por favor, intenta de nuevo.",
                            ephemeral=True
                        )
                except:
                    pass
    
    @app_commands.command(name="host", description="Selecciona aleatoriamente quién será el anfitrión entre dos jugadores")
    @app_commands.describe(
        jugador1="Primer jugador",
        jugador2="Segundo jugador"
    )
    async def host(
        self,
        interaction: discord.Interaction,
        jugador1: discord.Member,
        jugador2: discord.Member
    ):
        """Selecciona aleatoriamente quién será el anfitrión entre dos jugadores"""
        
        # verificar que no sean el mismo jugador
        if jugador1.id == jugador2.id:
            await interaction.response.send_message(
                "❌ No puedes seleccionar el mismo jugador dos veces.",
                ephemeral=True
            )
            return
        
        await interaction.response.defer(ephemeral=False)
        
        with get_db() as db:
            player = db.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
            t = get_player_translator(player) if player else get_translator('es')
        
        # seleccion aleatoria (0 = jugador1, 1 = jugador2)
        random_index = random.randint(0, 1)
        
        if random_index == 0:
            host = jugador1
            other = jugador2
        else:
            host = jugador2
            other = jugador1
        
        # crear embed con el resultado
        embed = discord.Embed(
            title="🎲 Selección de Anfitrión",
            description=f"**{host.display_name}** ha sido seleccionado como anfitrión.",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="👤 Anfitrión",
            value=host.mention,
            inline=True
        )
        embed.add_field(
            name="👤 Invitado",
            value=other.mention,
            inline=True
        )
        embed.set_footer(text="Selección aleatoria")
        
        await interaction.followup.send(embed=embed)

class ConfirmMatchView(discord.ui.View):
    def __init__(self, match_id: int, reporter_id: int, opponent_id: int, reporter_discord_id: int, opponent_discord_id: int):
        super().__init__(timeout=86400)  # 24 horas
        self.match_id = match_id
        self.reporter_id = reporter_id
        self.opponent_id = opponent_id
        self.reporter_discord_id = reporter_discord_id
        self.opponent_discord_id = opponent_discord_id
    
    @discord.ui.button(label="Sí", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm_match(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Responder inmediatamente para evitar timeout
        await interaction.response.defer()
        
        with get_db() as db:
            player = db.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
            if not player:
                t = get_player_translator(player) if player else get_player_translator(Player(language='es'))
                await interaction.followup.send(t.t('match.confirm.errors.no_profile'), ephemeral=True)
                return
            
            t = get_player_translator(player)
            
            # verificar si el usuario es admin (permisos de discord o lista de admins)
            is_admin = (
                interaction.user.guild_permissions.administrator or
                interaction.user.id in ADMIN_IDS
            )
            
            # solo el oponente o un admin puede confirmar el score
            if player.id != self.opponent_id and not is_admin:
                await interaction.followup.send(t.t('match.confirm.errors.only_opponent'), ephemeral=True)
                return
            
            match = db.query(Match).filter(
                and_(
                    Match.id == self.match_id,
                    Match.status == 'reported'
                )
            ).first()
            
            if not match:
                await interaction.followup.send(t.t('match.confirm.errors.already_confirmed'), ephemeral=True)
                return
            
            # confirmar partida
            match.status = 'confirmed'
            match.confirmed_by = player.id
            match.confirmed_at = datetime.utcnow()
            
            # si fue confirmado por un admin (no el oponente), se permite la confirmación
            
            player1 = db.query(Player).filter(Player.id == match.player1_id).first()
            player2 = db.query(Player).filter(Player.id == match.player2_id).first()
            
            # refrescar para tener racha de victorias actualizado desde la base de datos (necesario para el bonus de racha)
            db.refresh(player1)
            db.refresh(player2)
            
            # determinar que tipo de ELO usar (por defecto 1v1)
            use_elo_1v1 = True
            
            # obtener elo ANTES de cualquier cambio (necesario para rangos y para empates)
            if use_elo_1v1:
                player1_elo_before = player1.elo_1v1 if player1.elo_1v1 is not None else 0
                player2_elo_before = player2.elo_1v1 if player2.elo_1v1 is not None else 0
            else:
                player1_elo_before = player1.elo
                player2_elo_before = player2.elo
            
            # guardar rangos ANTES de actualizar elo para detectar si subieron (para todos los casos)
            player1_rank_before = get_rank_from_elo(player1_elo_before)
            player2_rank_before = get_rank_from_elo(player2_elo_before)
            
            # verificar si es empate
            is_draw = match.score1 == match.score2
            
            if is_draw:
                
                # empate: ambos suman 1-5 de elo segun la diferencia
                # no se resetea la racha de victorias en empate
                player1_elo = player1_elo_before
                player2_elo = player2_elo_before
                elo_diff = abs(player1_elo - player2_elo)
                # 0 diff -> +1, ~100 -> +2, ~200 -> +3, ~300 -> +4, 400+ -> +5
                draw_elo = min(5, max(1, 1 + int(elo_diff / 100)))
                match.elo_change1 = draw_elo
                match.elo_change2 = draw_elo
                match.xp_gained1 = 0
                match.xp_gained2 = 0
                
                # aplicar el elo del empate a ambos jugadores
                if use_elo_1v1:
                    if player1.elo_1v1 is None:
                        player1.elo_1v1 = 0
                    if player2.elo_1v1 is None:
                        player2.elo_1v1 = 0
                    player1.elo_1v1 += draw_elo
                    player2.elo_1v1 += draw_elo
                    player1.elo += draw_elo
                    player2.elo += draw_elo
                else:
                    player1.elo += draw_elo
                    player2.elo += draw_elo
                
                # actualizar empates (no se resetea la racha)
                player1.draws += 1
                player2.draws += 1
                
                # actualizar elo de equipos si los jugadores estan en equipos
                if use_elo_1v1:
                    for p in [player1, player2]:
                        for membership in p.team_memberships:
                            if membership.team:
                                membership.team.update_team_elo()
            else:
                # no es empate: calcular ELO y XP
                # usar ELO que ya obtuvimos antes
                player1_elo = player1_elo_before
                player2_elo = player2_elo_before
                
                player1_won = match.score1 > match.score2
                
                # obtener rachas ANTES de calcular el elo (para el bonus de racha)
                player1_streak_before = player1.win_streak or 0
                player2_streak_before = player2.win_streak or 0
                
                # calcular elo:
                elo_change1, elo_change2, streak_bonus1, streak_bonus2 = calculate_elo(
                    player1_elo, player2_elo, player1_won,
                    player1_streak_before, player2_streak_before
                )
                
                # EVENTO x2: aplicar bonificacion de elo si el evento esta activo (solo para /score)
                if is_elo_bonus_event_active():
                    # evento activo: aplicar multiplicadores
                    # elo ganado x2, elo perdido x1.5
                    if elo_change1 > 0:
                        elo_change1 *= ELO_BONUS_WIN_MULTIPLIER
                    else:
                        elo_change1 *= ELO_BONUS_LOSS_MULTIPLIER
                    
                    if elo_change2 > 0:
                        elo_change2 *= ELO_BONUS_WIN_MULTIPLIER
                    else:
                        elo_change2 *= ELO_BONUS_LOSS_MULTIPLIER
                
                # guardar en el match el cambio total (base + bonus de racha) para mostrar en embed
                match.elo_change1 = elo_change1
                match.elo_change2 = elo_change2
                
                # actualizar el elo del jugador: sumar el cambio total
                if use_elo_1v1:
                    # inicializar elo_1v1 si no existe
                    if player1.elo_1v1 is None:
                        player1.elo_1v1 = 0
                    if player2.elo_1v1 is None:
                        player2.elo_1v1 = 0
                    player1.elo_1v1 += elo_change1  # elo_change1 ya incluye el bono de racha
                    player2.elo_1v1 += elo_change2  # elo_change2 ya incluye el bono la racha
                    # asegurar que el elo nunca sea negativo (minimo 0)
                    if player1.elo_1v1 < 0:
                        player1.elo_1v1 = 0
                    if player2.elo_1v1 < 0:
                        player2.elo_1v1 = 0
                    # tambien actualizar elo general
                    player1.elo += elo_change1
                    player2.elo += elo_change2
                    # asegurar que el elo general tampoco sea negativo
                    if player1.elo < 0:
                        player1.elo = 0
                    if player2.elo < 0:
                        player2.elo = 0
                    
                    # actualizar elo de equipos si los jugadores estan en equipos
                    # elo del equipo es la suma del elo 1v1 de todos los miembros
                    for player in [player1, player2]:
                        for membership in player.team_memberships:
                            if membership.team:
                                membership.team.update_team_elo()
                else:
                    player1.elo += elo_change1
                    player2.elo += elo_change2
                    # asegurar que el elo nunca sea negatiivo
                    if player1.elo < 0:
                        player1.elo = 0
                    if player2.elo < 0:
                        player2.elo = 0
                
                # calcular
                if player1_won:
                    xp1 = XP_WIN
                    xp2 = XP_LOSS
                    if player2_elo > player1_elo:
                        xp1 = int(xp1 * XP_BONUS_MULTIPLIER)
                else:
                    xp1 = XP_LOSS
                    xp2 = XP_WIN
                    if player1_elo > player2_elo:
                        xp2 = int(xp2 * XP_BONUS_MULTIPLIER)
                
                match.xp_gained1 = xp1
                match.xp_gained2 = xp2
                
                player1.xp += xp1
                player2.xp += xp2
                
                # guardar bonus de racha para mostrar en el embed (guardar en el match como atributo temporal)
                if player1_won:
                    player1.wins += 1
                    player2.losses += 1
                    player1.win_streak += 1
                    if player1.win_streak > player1.best_win_streak:
                        player1.best_win_streak = player1.win_streak
                    player2.win_streak = 0
                    # guardar racha y bonus del ganador como atributos temporales
                    match._winner_streak = player1.win_streak
                    match._winner_streak_bonus = streak_bonus1
                else:
                    player2.wins += 1
                    player1.losses += 1
                    player2.win_streak += 1
                    if player2.win_streak > player2.best_win_streak:
                        player2.best_win_streak = player2.win_streak
                    player1.win_streak = 0
                    # guardar racha y bonus del ganador como atributos temporales
                    match._winner_streak = player2.win_streak
                    match._winner_streak_bonus = streak_bonus2
            
            # hacer commit y refresh para todos los casos (victoria, derrota, empate)
            db.commit()
            db.refresh(match)
            db.refresh(player1)
            db.refresh(player2)
            
            # obtener usuarios de discord para el embed
            try:
                user1 = await interaction.client.fetch_user(int(player1.discord_id))
            except:
                user1 = None
            try:
                user2 = await interaction.client.fetch_user(int(player2.discord_id))
            except:
                user2 = None
            
            # obtener usuario que confirmo
            confirmed_by_user = interaction.user
            
            # url de imagen desde configuracion (con fallback opcional)
            stadium_image_url = STADIUM_IMAGE_URL
            
            # obtener idioma del jugador que confirmo para el embed
            player_language = getattr(player, 'language', None) or 'es'
            
            # generar imagen del estadio con marcador superpuesto
            image_file = None
            if not stadium_image_url:
                print("⚠️ STADIUM_IMAGE_URL no está configurado. No se generará imagen personalizada.")
            else:
                # probar con principal y fallback (si esta configurado)
                image_urls_to_try = []
                seen = set()
                for url_candidate in [STADIUM_IMAGE_URL, STADIUM_IMAGE_URL_FALLBACK]:
                    if url_candidate and url_candidate not in seen:
                        image_urls_to_try.append(url_candidate)
                        seen.add(url_candidate)

                try:
                    from utils.image_generator import generate_stadium_image_with_score
                    # obtener urls de avatares y nombres
                    player1_avatar_url = user1.avatar.url if user1 and user1.avatar else None
                    player2_avatar_url = user2.avatar.url if user2 and user2.avatar else None
                    player1_name = user1.display_name if user1 else player1.username
                    player2_name = user2.display_name if user2 else player2.username
                    
                    # obtener estadisticas para la imagen
                    elo_change1 = match.elo_change1 if hasattr(match, 'elo_change1') else 0
                    elo_change2 = match.elo_change2 if hasattr(match, 'elo_change2') else 0
                    xp_gained1 = match.xp_gained1 if hasattr(match, 'xp_gained1') else 0
                    xp_gained2 = match.xp_gained2 if hasattr(match, 'xp_gained2') else 0
                    player1_elo = player1.elo_1v1 if player1.elo_1v1 is not None else player1.elo
                    player2_elo = player2.elo_1v1 if player2.elo_1v1 is not None else player2.elo

                    import asyncio
                    loop = asyncio.get_event_loop()
                    image_bytes = None

                    for candidate_url in image_urls_to_try:
                        try:
                            image_bytes = await asyncio.wait_for(
                                loop.run_in_executor(
                                    None,
                                    generate_stadium_image_with_score,
                                    candidate_url,
                                    match.score1,
                                    match.score2,
                                    player1_avatar_url,
                                    player2_avatar_url,
                                    player1_name,
                                    player2_name,
                                    elo_change1,
                                    elo_change2,
                                    xp_gained1,
                                    xp_gained2,
                                    player1_elo,
                                    player2_elo
                                ),
                                timeout=10.0  # timeout de 10 segundos
                            )
                            stadium_image_url = candidate_url
                        except asyncio.TimeoutError:
                            print("⚠️ Timeout al generar imagen (más de 10 segundos)")
                            image_bytes = None
                            continue
                        except Exception as e:
                            print(f"❌ Error al generar imagen con marcador usando {candidate_url}: {e}")
                            import traceback
                            traceback.print_exc()
                            image_bytes = None
                            continue

                        if image_bytes:
                            break

                    if image_bytes:
                        image_file = discord.File(image_bytes, filename="match_result.png")
                        stadium_image_url = "attachment://match_result.png"
                    else:
                        stadium_image_url = None
                except Exception as e:
                    print(f"❌ Error al generar imagen con marcador: {e}")
                    import traceback
                    traceback.print_exc()
                    stadium_image_url = None
            
            # obtener rangos despues de actualizar el elo
            if use_elo_1v1:
                player1_elo_after = player1.elo_1v1 if player1.elo_1v1 is not None else 0
                player2_elo_after = player2.elo_1v1 if player2.elo_1v1 is not None else 0
            else:
                player1_elo_after = player1.elo
                player2_elo_after = player2.elo
            
            player1_rank_after = get_rank_from_elo(player1_elo_after)
            player2_rank_after = get_rank_from_elo(player2_elo_after)
            
            # REVISAR: actualizar roles de discord segun rango (si el servidor tiene roles configurados)
            if interaction.guild:
                try:
                    member1 = interaction.guild.get_member(int(player1.discord_id))
                    if member1:
                        await update_member_rank_roles(member1, player1_rank_after, interaction.guild)
                    member2 = interaction.guild.get_member(int(player2.discord_id))
                    if member2:
                        await update_member_rank_roles(member2, player2_rank_after, interaction.guild)
                except Exception as e:
                    print(f"⚠️ Error actualizando roles de rango: {e}")
            
            # ACTUALIZAR:detectar si subieron de rango (solo si no es empate, porque en empate no cambia el elo)
            if is_draw:
                player1_rank_up = False
                player2_rank_up = False
            else:
                player1_rank_up = player1_rank_before != player1_rank_after
                player2_rank_up = player2_rank_before != player2_rank_after
            
            # determinar quien gano (solo si no es empate)
            player1_won_result = None if is_draw else (match.score1 > match.score2)
            
            # obtener racha y bonus del ganador desde atributos temporales del match
            winner_streak = getattr(match, '_winner_streak', 0)
            winner_streak_bonus = getattr(match, '_winner_streak_bonus', 0.0)
            
            # verificar si el evento de bonificacion de elo esta activo
            elo_bonus_active = is_elo_bonus_event_active()
            
            embed = create_match_result_embed(
                match, player1, player2, user1, user2, is_draw, confirmed_by_user, 
                stadium_image_url, use_elo_1v1, language=player_language,
                player1_rank_before=player1_rank_before, player2_rank_before=player2_rank_before,
                player1_rank_after=player1_rank_after, player2_rank_after=player2_rank_after,
                player1_rank_up=player1_rank_up, player2_rank_up=player2_rank_up,
                player1_won=player1_won_result,
                winner_streak=winner_streak, winner_streak_bonus=winner_streak_bonus,
                elo_bonus_active=elo_bonus_active,
                elo_bonus_win_mult=ELO_BONUS_WIN_MULTIPLIER,
                elo_bonus_loss_mult=ELO_BONUS_LOSS_MULTIPLIER
            )
            
            # borrar el mensaje original antes de enviar el nuevo
            try:
                if interaction.message:
                    await interaction.message.delete()
            except:
                pass
            
            # enviar mensaje con imagen adjunta si se genero
            # usar followup porque ya hicimos defer()
            if image_file:
                await interaction.followup.send(embed=embed, file=image_file)
            else:
                await interaction.followup.send(embed=embed)
            self.stop()
    
    @discord.ui.button(label="No", style=discord.ButtonStyle.danger, emoji="❌")
    async def dispute_match(self, interaction: discord.Interaction, button: discord.ui.Button):
        with get_db() as db:
            player = db.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
            if not player:
                t = get_player_translator(Player(language='es'))
            else:
                t = get_player_translator(player)
            
            if not player or player.id != self.opponent_id:
                await interaction.response.send_message(t.t('match.confirm.errors.only_opponent_dispute'), ephemeral=True)
                return
            
            match = db.query(Match).filter(Match.id == self.match_id).first()
            match.status = 'disputed'
            db.commit()
            
            # borrar el mensaje original antes de responder
            try:
                if interaction.message:
                    await interaction.message.delete()
            except:
                pass
            
            await interaction.response.send_message(t.t('match.confirm.errors.disputed'), ephemeral=True)
            self.stop()

async def setup(bot):
    await bot.add_cog(MatchesCog(bot))

