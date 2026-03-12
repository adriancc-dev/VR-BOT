import discord
from discord import app_commands
from discord.ext import commands
from database.database import get_db
from database.models import Player, MatchmakingRequest, Match, Team, TeamMember
from utils.embeds import create_matchmaking_embed
from utils.i18n import translate_rank
from utils.i18n import get_player_translator, get_translator
from config import MATCHMAKING_WEBHOOK_URL, MATCHMAKING_WEBHOOK_NAME, MATCHMAKING_WEBHOOK_AVATAR_URL
from datetime import datetime, timedelta
from sqlalchemy import and_
import asyncio

class MatchmakingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # diccionario para rastrear mensajes activos
        self.active_messages = {}
    
    @app_commands.command(name="matchmaking", description="Busca una partida 1v1 de forma anónima")
    async def matchmaking(
        self,
        interaction: discord.Interaction
    ):
        # responder ephemeral para que solo el usuario vea "Buscando partida..."
        await interaction.response.defer(ephemeral=True)
        
        # enviar mensaje privado al usuario
        await interaction.followup.send("🔍 Buscando partida...", ephemeral=True)
        
        try:
            # siempre usar 1v1, anonimo, local
            game = '1v1'
            
            with get_db() as db:
                # obtener o crear jugador
                player = db.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
                if not player:
                    player = Player(
                        discord_id=str(interaction.user.id),
                        username=interaction.user.name
                    )
                    db.add(player)
                    db.commit()
                    db.refresh(player)
                
                # cancelar solicitudes anteriores activas
                db.query(MatchmakingRequest).filter(
                    and_(
                        MatchmakingRequest.player_id == player.id,
                        MatchmakingRequest.status == 'active'
                    )
                ).update({'status': 'cancelled'})
                db.commit()
                
                # crear nueva solicitud (siempre anonima, local, sin elo como pista)
                request = MatchmakingRequest(
                    player_id=player.id,
                    match_type=game,
                    is_anonymous=True,  # anonimo
                    is_global=False,    # local al servidor
                    hint=None,         # sin pista de elo
                    expires_at=datetime.utcnow() + timedelta(hours=1)
                )
                db.add(request)
                db.commit()
                db.refresh(request)
                
                # buscar el rol "Matchmaking" para mencionarlo
                role_mention = ""
                matchmaking_role = None
                if interaction.guild:
                    # buscar el rol exacto primero
                    matchmaking_role = discord.utils.get(interaction.guild.roles, name="Matchmaking")
                    if not matchmaking_role:
                        # si no se encuentra el rol, intentar buscar sin case-sensitive
                        for role in interaction.guild.roles:
                            if role.name.lower() == "matchmaking":
                                matchmaking_role = role
                                break
                    
                    if matchmaking_role:
                        role_mention = matchmaking_role.mention
                        
                        # verificar permisos del bot
                        bot_member = interaction.guild.get_member(self.bot.user.id)
                        bot_permissions = interaction.channel.permissions_for(bot_member) if bot_member else None
                        
                        # verificar si el rol es mencionable
                        if not matchmaking_role.mentionable:
                            print(f"⚠️ ADVERTENCIA: El rol '{matchmaking_role.name}' (ID: {matchmaking_role.id}) no es mencionable.")
                            print(f"   Los usuarios con este rol NO recibirán notificaciones.")
                            print(f"   💡 SOLUCIÓN: Ve a Configuración del servidor > Roles > {matchmaking_role.name}")
                            print(f"   > Activa la opción 'Permitir que todos mencionen este rol'")
                        else:
                            # verificar jerarquia de roles
                            bot_role = bot_member.top_role if bot_member else None
                            if bot_role and matchmaking_role.position >= bot_role.position:
                                print(f"⚠️ ADVERTENCIA: El rol '{matchmaking_role.name}' está por encima o al mismo nivel que el rol del bot.")
                                print(f"   Esto puede impedir que las menciones funcionen correctamente.")
                                print(f"   💡 SOLUCIÓN: Mueve el rol del bot por encima del rol Matchmaking en la jerarquía.")
                            
                            # verificar permisos del bot
                            if bot_permissions:
                                if not bot_permissions.mention_everyone and not bot_permissions.administrator:
                                    print(f"⚠️ ADVERTENCIA: El bot puede no tener permisos suficientes para mencionar roles.")
                                    print(f"   💡 Verifica que el bot tenga permisos de 'Mencionar @everyone, @here y todos los roles'")
                    else:
                        print(f"⚠️ No se encontró el rol 'Matchmaking' en el servidor.")
                        print(f"   💡 Asegúrate de que existe un rol llamado 'Matchmaking' (case-insensitive)")
                
                # crear embed (anonimo, con pista creativa y mencion del rol)
                embed = create_matchmaking_embed(player, game, True, None, role_mention)
                
                # crear vista con botones
                view = MatchmakingView(request.id, player.id, game, cog=self, bot=self.bot)
                
                # enviar mensaje con mencion del rol fuera del embed y embed con mencion dentro
                # la mencion fuera del embed es la que realmente menciona a los usuarios
                # IMPORTANTE: el rol debe ser "mencionable" en la configuracion del servidor para que funcione
                content = role_mention if role_mention else None
                
                # configurar allowed_mentions para permitir explicitamente menciones de roles
                allowed_mentions = discord.AllowedMentions(roles=True) if role_mention else None
                
                # enviar el mensaje publico como el bot (no como followup de la interaccion) para que asi
                # sea totalmente anonimo: en movil no salta notificacion del usuario que uso /matchmaking.

                try:
                    message_obj = await interaction.channel.send(
                        content=content,
                        embed=embed,
                        view=view,
                        allowed_mentions=allowed_mentions,
                    )
                    if message_obj:
                        self.active_messages[request.id] = message_obj
                except Exception as e:
                    print(f"❌ Error al enviar mensaje de matchmaking: {e}")
                    import traceback
                    traceback.print_exc()
                    await interaction.followup.send(
                        "❌ Error al enviar mensaje de matchmaking. Por favor, intenta de nuevo.",
                        ephemeral=True
                    )
        except Exception as e:
            print(f"❌ Error en comando matchmaking: {e}")
            import traceback
            traceback.print_exc()
            # enviar mensaje de error
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        f"❌ Ocurrió un error: {str(e)}",
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        f"❌ Ocurrió un error: {str(e)}",
                        ephemeral=True
                    )
            except:
                pass
    # ----------- ELIMINAR ESTE COMANDO ------------
    @app_commands.command(name="cancel-matchmaking", description="Cancela todas tus búsquedas activas")
    async def cancel_matchmaking(self, interaction: discord.Interaction):
        # responder inmediatamente para evitar timeout
        await interaction.response.defer(ephemeral=True)
        
        try:
            with get_db() as db:
                player = db.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
                if not player:
                    t = get_translator('es')
                    await interaction.followup.send(t.t('matchmaking.errors.no_profile'), ephemeral=True)
                    return
                
                t = get_player_translator(player)
                
                # obtener todas las solicitudes activas del jugador
                requests = db.query(MatchmakingRequest).filter(
                    and_(
                        MatchmakingRequest.player_id == player.id,
                        MatchmakingRequest.status == 'active'
                    )
                ).all()
                
                if not requests:
                    await interaction.followup.send(t.t('matchmaking.errors.no_active'), ephemeral=True)
                    return
                
                # cancelar todas las solicitudes 
                cancelled_count = 0
                for request in requests:
                    request.status = 'cancelled'
                    cancelled_count += 1
                    
                    # Intentar eliminar o editar el mensaje
                    if request.id in self.active_messages:
                        try:
                            message = self.active_messages[request.id]
                            # Crear una vista deshabilitada
                            disabled_view = discord.ui.View()
                            for item in message.components:
                                if isinstance(item, discord.ui.Button):
                                    disabled_button = discord.ui.Button(
                                        label=item.label,
                                        style=item.style,
                                        disabled=True
                                    )
                                    disabled_view.add_item(disabled_button)
                            
                            # Editar el mensaje para deshabilitar los botones
                            t = get_player_translator(player)
                            embed = message.embeds[0] if message.embeds else discord.Embed(
                                title=t.t('matchmaking.cancelled.title'),
                                description=t.t('matchmaking.cancelled.description'),
                                color=discord.Color.red()
                            )
                            await message.edit(embed=embed, view=disabled_view)
                            
                            # Remover del diccionario
                            del self.active_messages[request.id]
                        except Exception as e:
                            # Si no se puede editar, intentar eliminar
                            try:
                                await message.delete()
                                del self.active_messages[request.id]
                            except:
                                pass  # Si no se puede eliminar, continuar
                
                db.commit()
                
                t = get_player_translator(player)
                await interaction.followup.send(
                    t.t('matchmaking.errors.cancelled_count', count=cancelled_count),
                    ephemeral=True
                )
        except Exception as e:
            print(f"❌ Error en cancel_matchmaking: {e}")
            import traceback
            traceback.print_exc()
            # Usar followup porque ya hicimos defer()
            await interaction.followup.send(
                f"❌ Ocurrió un error: {str(e)}",
                ephemeral=True
            )

class MatchmakingView(discord.ui.View):
    def __init__(self, request_id: int, requester_id: int, match_type: str, cog=None, bot=None):
        super().__init__(timeout=3600)  # 1 hora
        self.request_id = request_id
        self.requester_id = requester_id
        self.match_type = match_type
        self.cog = cog  # referencia al cog para acceder a active_messages
        self.bot = bot  # referencia al bot para obtener miembros
    
    @discord.ui.button(label="Aceptar", style=discord.ButtonStyle.success)
    async def accept_match(self, interaction: discord.Interaction, button: discord.ui.Button):
        # responder inmediatamente para evitar timeout
        await interaction.response.defer()
        
        try:
            requester_discord_id = None
            with get_db() as db:
                requester = db.query(Player).filter(Player.id == self.requester_id).first()
                if requester:
                    requester_discord_id = int(requester.discord_id)
            
            if interaction.user.id == requester_discord_id:
                with get_db() as db:
                    accepter = db.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
                    t = get_player_translator(accepter) if accepter else get_translator('es')
                await interaction.followup.send(t.t('matchmaking.errors.own_request'), ephemeral=True)
                return
            
            with get_db() as db:
                # obtener jugadores
                requester = db.query(Player).filter(Player.id == self.requester_id).first()
                accepter = db.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
                
                if not accepter:
                    accepter = Player(
                        discord_id=str(interaction.user.id),
                        username=interaction.user.name
                    )
                    db.add(accepter)
                    db.commit()
                    db.refresh(accepter)
                
                # actualizar solicitud
                request = db.query(MatchmakingRequest).filter(MatchmakingRequest.id == self.request_id).first()
                t = get_player_translator(accepter) if accepter else get_translator('es')
                
                if not request or request.status != 'active':
                    await interaction.followup.send(t.t('matchmaking.errors.not_active'), ephemeral=True)
                    return
                
                # sin limite de divisiones, todo el mundo puede aceptar a todo el mundo
                request.status = 'accepted'
                
                # crear partida 1v1
                match = Match(
                    match_type='1v1',
                    player1_id=requester.id,
                    player2_id=accepter.id,
                    status='pending'
                )
                db.add(match)
                db.commit()
                
                # guardar valores necesarios antes de salir del contexto de la sesion
                requester_id = requester.id
                accepter_id = accepter.id
                requester_discord_id = requester.discord_id
                requester_username = requester.username
                accepter_username = accepter.username
            
            # obtener los objetos de usuario de discord para las menciones
            accepter_user = interaction.user  # ya tenemos el usuario que acepto
            
            # intentar obtener el usuario que busco usando el bot
            requester_user = None
            if interaction.guild and self.bot:
                try:
                    requester_user = await interaction.guild.fetch_member(int(requester_discord_id))
                except:
                    # si no se puede obtener, usar el formato de mencion directo
                    requester_user = None
            
            # seleccion aleatoria del anfitrion entre los dos jugadores
            import random
            # usar random.randint para seleccionar 0 o 1, luego elegir el jugador correspondiente

            random_index = random.randint(0, 1)
            
            # obtener el nombre del local basado en quien fue seleccionado
            # usar el indice para determinar quien es el local
            if random_index == 0:
                # el anfitrion es el que busco la partida (requester)
                host_name = requester_user.display_name if requester_user else requester_username
            else:
                # el anfitrion es el que acepto la partida (accepter)
                host_name = accepter_user.display_name if accepter_user else accepter_username
            
            # obtener menciones para el content (fuera del embed)
            requester_mention = requester_user.mention if requester_user else f"<@{requester_discord_id}>"
            accepter_mention = accepter_user.mention
            
            # crear mensaje fuera del embed con las menciones
            content = f"{requester_mention} {t.t('matchmaking.accepted.content', accepter=accepter_mention)}"
            
            # crear embed con la informacion
            embed = discord.Embed(
                title=t.t('matchmaking.accepted.title'),
                color=discord.Color.green()
            )
            embed.add_field(
                name=t.t('matchmaking.accepted.random_selection'),
                value=t.t('matchmaking.accepted.host', host=host_name),
                inline=False
            )
            embed.set_footer(text=t.t('matchmaking.accepted.footer'))
            
            # borrar el mensaje original antes de enviar el nuevo
            try:
                if interaction.message:
                    await interaction.message.delete()
            except:
                pass
            
            # enviar mensaje con menciones fuera del embed y embed con informacion
            allowed_mentions = discord.AllowedMentions(users=True)
            await interaction.followup.send(content=content, embed=embed, allowed_mentions=allowed_mentions)
            self.stop()
            
            # remover el mensaje del diccionario de mensajes activos
            if self.cog and self.request_id in self.cog.active_messages:
                try:
                    del self.cog.active_messages[self.request_id]
                except:
                    pass
        except Exception as e:
            print(f"❌ Error en accept_match: {e}")
            import traceback
            traceback.print_exc()
            try:
                await interaction.followup.send(
                    "❌ Ocurrió un error al aceptar la partida. Por favor, intenta de nuevo.",
                    ephemeral=True
                )
            except:
                pass
    
    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.danger)
    async def cancel_match(self, interaction: discord.Interaction, button: discord.ui.Button):
        requester_discord_id = None
        with get_db() as db:
            requester = db.query(Player).filter(Player.id == self.requester_id).first()
            if requester:
                requester_discord_id = int(requester.discord_id)
        
        if interaction.user.id != requester_discord_id:
            with get_db() as db:
                player = db.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
                t = get_player_translator(player) if player else get_translator('es')
            await interaction.response.send_message(t.t('matchmaking.errors.only_creator'), ephemeral=True)
            return
        
        with get_db() as db:
            request = db.query(MatchmakingRequest).filter(MatchmakingRequest.id == self.request_id).first()
            request.status = 'cancelled'
            db.commit()
        
        # borrar el mensaje original antes de responder
        try:
            if interaction.message:
                await interaction.message.delete()
        except:
            pass
        
        with get_db() as db:
            player = db.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
            t = get_player_translator(player) if player else get_translator('es')
        await interaction.response.send_message(t.t('matchmaking.cancelled.message'), ephemeral=True)
        self.stop()
        
        # remover el mensaje del diccionario si existe
        if self.cog and self.request_id in self.cog.active_messages:
            try:
                del self.cog.active_messages[self.request_id]
            except:
                pass

async def setup(bot):
    await bot.add_cog(MatchmakingCog(bot))

