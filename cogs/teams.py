import discord
from discord import app_commands
from discord.ext import commands
from database.database import get_db
from database.models import Player, Team, TeamMember, TeamInvite, TeamWar, TeamWarMatch, Match
from datetime import datetime, timedelta
from sqlalchemy import and_, or_, func
from utils.elo import get_rank_from_elo
from utils.i18n import get_player_translator, get_translator
import logging

logger = logging.getLogger(__name__)

class TeamsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    async def safe_send(self, interaction: discord.Interaction, content=None, embed=None, view=None, ephemeral=False):
        """Envía un mensaje de forma segura, verificando si la interacción ya fue respondida"""
        
        # preparar parametros
        kwargs = {'ephemeral': ephemeral}
        if view is not None:
            kwargs['view'] = view
        
        if not interaction.response.is_done():
            if embed:
                await interaction.response.send_message(embed=embed, **kwargs)
            else:
                await interaction.response.send_message(content=content, **kwargs)
        else:
            if embed:
                await interaction.followup.send(embed=embed, **kwargs)
            else:
                await interaction.followup.send(content=content, **kwargs)
    
    def get_team_member(self, db, player_id, team_id):
        """Obtiene el TeamMember de un jugador en un equipo"""
        return db.query(TeamMember).filter(
            and_(
                TeamMember.player_id == player_id,
                TeamMember.team_id == team_id
            )
        ).first()
    
    def get_player_team(self, db, player_id):
        """Obtiene el equipo actual de un jugador"""
        membership = db.query(TeamMember).filter(
            TeamMember.player_id == player_id
        ).first()
        return membership.team if membership else None
    @app_commands.command(name="team-create", description="Crea un equipo profesional")
    @app_commands.describe(
        name="Nombre exacto del equipo",
        tag="Prefijo/Tag del equipo (ej: INAZ)",
        logo="Logo del equipo en formato PNG (obligatorio)"
    )
    async def team_create(
        self,
        interaction: discord.Interaction,
        name: str,
        tag: str,
        logo: discord.Attachment
    ):
        """Crea un equipo de forma profesional con nombre, prefijo y logo"""

        # enviar la respuesta inmediatamente
        await interaction.response.defer(ephemeral=True)
        
        try:
            with get_db() as db:
                player = db.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
                if not player:
                    player = Player(
                        discord_id=str(interaction.user.id),
                        username=interaction.user.name
                    )
                    try:
                        db.add(player)
                        db.commit()
                        db.refresh(player)
                    except Exception:
                        # si falla (ya existe), obtener el jugador existente
                        db.rollback()
                        player = db.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
                        if player:
                            # actualizar user si cambio
                            player.username = interaction.user.name
                            db.commit()
                            db.refresh(player)
                
                t = get_player_translator(player) if player else get_translator('es')
                
                # verificar que no este en otro equipo
                existing_team = self.get_player_team(db, player.id)
                if existing_team:
                    await interaction.followup.send(
                        t.t('team.errors.already_in_team', name=existing_team.name),
                        ephemeral=True
                    )
                    return
                
                # validar tag
                if len(tag) > 4:
                    await self.safe_send(interaction,
                        t.t('team.errors.tag_too_long'),
                        ephemeral=True)
                    return
                
                # validar logo
                if not logo.content_type or not logo.content_type.startswith('image/'):
                    await self.safe_send(interaction,t.t('team.errors.tag_too_long'),ephemeral=True)
                    return
                
                # verificar que sea png
                is_png = False
                if logo.content_type == 'image/png':
                    is_png = True
                elif logo.filename and logo.filename.lower().endswith('.png'):
                    is_png = True
                
                if not is_png:
                    await self.safe_send(interaction,
                        t.t('team.errors.tag_too_long'),
                        ephemeral=True)
                    return
                
                logo_url = logo.url
                
                # verificar que el nombre no exista
                existing_name = db.query(Team).filter(
                    func.lower(Team.name) == name.lower()
                ).first()
                if existing_name:
                    await interaction.followup.send(
                        t.t('team.errors.name_exists', name=existing_name.name),
                        ephemeral=True
                    )
                    return
                
                # verificar que el tag no exista antes de crear
                # filtrar solo tags que no sean null
                existing_tag = db.query(Team).filter(
                    and_(
                        Team.tag.isnot(None),
                        func.lower(Team.tag) == tag.lower()
                    )
                ).first()
                if existing_tag:
                    await interaction.followup.send(
                        t.t('team.errors.tag_exists', name=existing_tag.name, tag=existing_tag.tag),
                        ephemeral=True
                    )
                    return
                
                # crear equipo
                team = Team(name=name, tag=tag, logo_url=logo_url)
                db.add(team)
                try:
                    db.commit()
                    db.refresh(team)
                except Exception as e:
                    db.rollback()
                    error_msg = str(e)

                    # si hay un error de unique constraint, significa que se creo entre la verificacion y ahora
                    if 'UNIQUE constraint failed' in error_msg or 'duplicate key value' in error_msg.lower() or 'unique constraint' in error_msg.lower():
                        # verificar otra vez si existe
                        existing_name_check = db.query(Team).filter(
                            func.lower(Team.name) == name.lower()
                        ).first()
                        existing_tag_check = db.query(Team).filter(
                            and_(
                                Team.tag.isnot(None),
                                func.lower(Team.tag) == tag.lower()
                            )
                        ).first()
                        
                        if existing_name_check and existing_name_check.name.lower() == name.lower():
                            await interaction.followup.send(
                                t.t('team.errors.name_exists', name=existing_name_check.name),
                                ephemeral=True
                            )
                            return
                        elif existing_tag_check:
                            await interaction.followup.send(
                                t.t('team.errors.tag_exists', name=existing_tag_check.name, tag=existing_tag_check.tag),
                                ephemeral=True
                            )
                            return
                        else:
                            await interaction.followup.send(
                                t.t('team.errors.tag_exists_simple', tag=tag),
                                ephemeral=True
                            )
                            return
                    else:
                        raise
                
                # agregar creador como lider
                membership = TeamMember(
                    team_id=team.id,
                    player_id=player.id,
                    role='leader'
                )
                db.add(membership)
                db.commit()
                db.refresh(team)
                # actualizar elo del equipo
                team.update_team_elo()
                db.commit()
                
                # Crear embed profesional
                embed = discord.Embed(
                    title=t.t('team.create.title'),
                    description=t.t('team.create.description', name=team.name),
                    color=discord.Color.green()
                )
                embed.add_field(name=t.t('team.create.prefix'), value=f"`{tag}`", inline=True)
                embed.add_field(name=t.t('team.create.your_role'), value=t.t('team.create.leader'), inline=True)
                embed.set_image(url=logo_url)
                embed.add_field(name=t.t('team.create.logo'), value=t.t('team.create.logo_configured'), inline=True)
                embed.set_footer(text=t.t('team.create.footer'))
                await interaction.followup.send(embed=embed, ephemeral=False)
        
        except Exception as e:
            print(f"❌ Error creando equipo: {e}")
            import traceback
            traceback.print_exc()
            await interaction.followup.send(
                f"❌ Ocurrió un error: {str(e)}",
                ephemeral=True
            )
    
    @app_commands.command(name="team-update-logo", description="Actualiza el logo de tu equipo (solo líderes)")
    @app_commands.describe(logo="Nuevo logo del equipo en formato PNG")
    async def team_update_logo(
        self,
        interaction: discord.Interaction,
        logo: discord.Attachment
    ):
        """Actualiza el logo del equipo (solo para líderes)"""
        await interaction.response.defer(ephemeral=True)
        
        try:
            with get_db() as db:
                player = db.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
                if not player:
                    player = Player(
                        discord_id=str(interaction.user.id),
                        username=interaction.user.name
                    )
                    try:
                        db.add(player)
                        db.commit()
                        db.refresh(player)
                    except Exception:
                        db.rollback()
                        player = db.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
                        if player:
                            player.username = interaction.user.name
                            db.commit()
                            db.refresh(player)
                
                t = get_player_translator(player) if player else get_translator('es')
                
                # Verificar que esté en un equipo
                team = self.get_player_team(db, player.id)
                if not team:
                    await interaction.followup.send(t.t('team.errors.not_in_team'), ephemeral=True)
                    return
                
                # Verificar que sea líder o co-líder
                membership = self.get_team_member(db, player.id, team.id)
                if not membership or membership.role not in ['leader', 'co-leader']:
                    await interaction.followup.send(
                        t.t('team.errors.only_leader_disband') if hasattr(t.t, 'team.errors.only_leader_disband') 
                        else "❌ Solo los líderes y co-líderes pueden actualizar el logo del equipo",
                        ephemeral=True
                    )
                    return
                
                # calidar que sea una imagen png
                is_png = False
                if logo.content_type == 'image/png':
                    is_png = True
                elif logo.filename and logo.filename.lower().endswith('.png'):
                    is_png = True
                
                if not is_png:
                    await interaction.followup.send(
                        "❌ El logo debe ser una imagen en formato PNG",
                        ephemeral=True
                    )
                    return
                
                # actualizar el logo
                team.logo_url = logo.url
                db.commit()
                
                # confirmar actualizacion
                embed = discord.Embed(
                    title="✅ Logo actualizado",
                    description=f"El logo de **{team.name}** ha sido actualizado exitosamente.",
                    color=discord.Color.green()
                )
                embed.set_image(url=logo.url)
                await interaction.followup.send(embed=embed, ephemeral=False)
        
        except Exception as e:
            print(f"❌ Error actualizando logo: {e}")
            import traceback
            traceback.print_exc()
            await interaction.followup.send(
                f"❌ Ocurrió un error: {str(e)}",
                ephemeral=True
            )
    
    @app_commands.command(name="team", description="Comandos de gestión de equipos")
    @app_commands.describe(
        action="Acción a realizar",
        member="Miembro (para invitar/expulsar/cambiar rol)",
        role="Rol a asignar (leader, co-leader, staff, member)",
        logo="Nuevo logo del equipo (solo para update-logo, formato PNG)"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="info", value="info"),
        app_commands.Choice(name="members", value="members"),
        app_commands.Choice(name="invite", value="invite"),
        app_commands.Choice(name="leave", value="leave"),
        app_commands.Choice(name="kick", value="kick"),
        app_commands.Choice(name="set-role", value="set-role"),
        app_commands.Choice(name="update-logo", value="update-logo"),
        app_commands.Choice(name="disband", value="disband"),
    ])
    @app_commands.choices(role=[
        app_commands.Choice(name="Líder", value="leader"),
        app_commands.Choice(name="Co-Líder", value="co-leader"),
        app_commands.Choice(name="Staff", value="staff"),
        app_commands.Choice(name="Miembro", value="member"),
    ])
    async def team(
        self,
        interaction: discord.Interaction,
        action: str,
        member: discord.Member = None,
        role: str = None,
        logo: discord.Attachment = None
    ):
        # responder inmediatamente para evitar timeout
        actions_that_defer = ['invite']
        if action not in actions_that_defer and not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        
        try:
            with get_db() as db:
                player = db.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
                if not player:
                    player = Player(
                        discord_id=str(interaction.user.id),
                        username=interaction.user.name
                    )
                    try:
                        db.add(player)
                        db.commit()
                        db.refresh(player)
                    except Exception:
                        # si falla (ya existe), obtener el jugador existente
                        db.rollback()
                        player = db.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
                        if player:
                            # actualizar user si ha cambiado
                            player.username = interaction.user.name
                            db.commit()
                            db.refresh(player)
                
                t = get_player_translator(player) if player else get_translator('es')
                
                ### INFO ###
                if action == "info":
                    team = self.get_player_team(db, player.id)
                    if not team:
                        await interaction.followup.send(t.t('team.errors.not_in_team'), ephemeral=True)
                        return
                    
                    # actualizar elo del equipo antes de mostrarlo
                    team.update_team_elo()
                    db.commit()  # guardar el elo actualizado
                    
                    membership = self.get_team_member(db, player.id, team.id)
                    leader = team.get_leader()
                    
                    embed = discord.Embed(
                        title=t.t('team.info.title', name=team.name),
                        color=discord.Color.blue()
                    )
                    if team.logo_url:
                        embed.set_thumbnail(url=team.logo_url)
                    if team.tag:
                        embed.add_field(name=t.t('team.info.prefix'), value=f"`{team.tag}`", inline=True)
                    
                    # mostrar el elo actualizado
                    embed.add_field(name=t.t('team.info.elo'), value=f"{team.elo:.0f}", inline=True)
                    embed.add_field(name=t.t('team.info.members'), value=f"{team.member_count()}/50", inline=True)
                    embed.add_field(name=t.t('team.info.wins'), value=team.wins, inline=True)
                    embed.add_field(name=t.t('team.info.losses'), value=team.losses, inline=True)
                    embed.add_field(name=t.t('team.info.win_rate'), value=f"{team.win_rate():.1f}%", inline=True)
                    if leader:
                        leader_player = db.query(Player).filter(Player.id == leader.player_id).first()
                        embed.add_field(name=t.t('team.info.leader'), value=f"<@{leader_player.discord_id}>", inline=False)
                    embed.add_field(name=t.t('team.info.your_role'), value=self.get_role_emoji(membership.role) + " " + membership.role.title(), inline=True)
                    embed.set_footer(text=t.t('team.info.created', date=team.created_at.strftime('%d/%m/%Y')))
                    
                    await interaction.followup.send(embed=embed, ephemeral=False)
                
                ### MIEMBROS ###
                elif action == "members":
                    team = self.get_player_team(db, player.id)
                    if not team:
                        await interaction.followup.send(t.t('team.errors.not_in_team'), ephemeral=True)
                        return
                    
                    members = db.query(TeamMember).filter(TeamMember.team_id == team.id).all()
                    embed = discord.Embed(
                        title=t.t('team.members.title', name=team.name),
                        color=discord.Color.blue()
                    )
                    
                    # Ordenar por rol (leader primero, luego co-leader, staff, member)
                    role_order = {'leader': 0, 'co-leader': 1, 'staff': 2, 'member': 3}
                    members_sorted = sorted(members, key=lambda m: role_order.get(m.role, 4))
                    
                    description = ""
                    for member in members_sorted:
                        member_player = db.query(Player).filter(Player.id == member.player_id).first()
                        role_emoji = self.get_role_emoji(member.role)
                        description += f"{role_emoji} <@{member_player.discord_id}> - {member.role.title()}\n"
                    
                    embed.description = description
                    await interaction.followup.send(embed=embed, ephemeral=False)
                
                ### INVITAR ###
                elif action == "invite":
                    # responder inmediatamente
                    if not interaction.response.is_done():
                        await interaction.response.defer(ephemeral=True)
                    
                    t = get_player_translator(player) if player else get_translator('es')
                    
                    if not member:
                        await interaction.followup.send(t.t('team.errors.must_mention', action='invitar'), ephemeral=True)
                        return
                    
                    team = self.get_player_team(db, player.id)
                    if not team:
                        await interaction.followup.send(t.t('team.errors.not_in_team'), ephemeral=True)
                        return
                    
                    membership = self.get_team_member(db, player.id, team.id)
                    if not membership.can_invite():
                        await interaction.followup.send(t.t('team.errors.no_permission_invite'), ephemeral=True)
                        return
                    
                    # verificar que el equipo no este lleno
                    if team.member_count() >= 50:
                        await interaction.followup.send(t.t('team.errors.team_full'), ephemeral=True)
                        return
                    
                    # verificar que el usuario no este ya en el equipo
                    target_player = db.query(Player).filter(Player.discord_id == str(member.id)).first()
                    if not target_player:

                        # crear jugador solo si no existe
                        target_player = Player(
                            discord_id=str(member.id),
                            username=member.name
                        )
                        try:
                            db.add(target_player)
                            db.commit()
                            db.refresh(target_player)
                        except Exception:

                            # si falla (ya existe), obtener el jugador existente
                            db.rollback()
                            target_player = db.query(Player).filter(Player.discord_id == str(member.id)).first()
                            if target_player:

                                # actualizar el user si ha cambiado
                                target_player.username = member.name
                                db.commit()
                                db.refresh(target_player)
                    
                    existing_member = self.get_team_member(db, target_player.id, team.id)
                    if existing_member:
                        await interaction.followup.send(t.t('team.errors.already_member', member=member.mention), ephemeral=True)
                        return
                    
                    # verificar que no tenga otra invitacion pendiente
                    existing_invite = db.query(TeamInvite).filter(
                        and_(
                            TeamInvite.player_id == target_player.id,
                            TeamInvite.team_id == team.id,
                            TeamInvite.status == 'pending'
                        )
                    ).first()
                    if existing_invite:
                        await interaction.followup.send(t.t('team.errors.invite_pending', member=member.mention), ephemeral=True)
                        return
                    
                    # crear invitacion primero para obtener el id
                    invite = TeamInvite(
                        team_id=team.id,
                        player_id=target_player.id,
                        invited_by=player.id,
                        expires_at=datetime.utcnow() + timedelta(days=7)
                    )
                    db.add(invite)
                    db.commit()
                    db.refresh(invite)  # obtener el id de la invitacion
                    
                    # intentar enviar el dm al usuario invitado
                    try:
                        # obtener traductor del jugador invitado
                        target_t = get_player_translator(target_player) if target_player else get_translator('es')
                        notify_embed = discord.Embed(
                            title=target_t.t('team.invite.notification_title'),
                            description=target_t.t('team.invite.notification_description', inviter=interaction.user.mention, name=team.name),
                            color=discord.Color.blue()
                        )
                        notify_embed.add_field(name=target_t.t('team.invite.team'), value=team.name, inline=True)
                        if team.tag:
                            notify_embed.add_field(name=target_t.t('team.invite.tag'), value=team.tag, inline=True)
                        notify_embed.set_footer(text=target_t.t('team.invite.footer'))
                        
                        view = TeamInviteView(invite.id, team.id, target_player.id)
                        await member.send(embed=notify_embed, view=view)
                        
                        # si el dm se envio correctamente, confirmar al que invita
                        embed = discord.Embed(
                            title=t.t('team.invite.title'),
                            description=t.t('team.invite.description', member=member.mention, name=team.name),
                            color=discord.Color.green()
                        )
                        await interaction.followup.send(embed=embed, ephemeral=False)
                    except discord.Forbidden:
                        # si el usuario tiene dm desactivados o bloqueo al bot eliminar la invitacion creada
                        db.delete(invite)
                        db.commit()
                        await interaction.followup.send(
                            f"❌ No se puede enviar un mensaje privado a {member.mention}. El usuario debe tener los mensajes directos activados para recibir invitaciones.",
                            ephemeral=True
                        )
                        return
                    except Exception as e:

                        # otro error al enviar el dm, eliminar la invitacion
                        db.delete(invite)
                        db.commit()
                        await interaction.followup.send(
                            f"❌ Error al enviar la invitación a {member.mention}: {str(e)}. La invitación no se ha creado.",
                            ephemeral=True
                        )
                        return
            
                ### SALIR ###
                elif action == "leave":
                    team = self.get_player_team(db, player.id)
                    if not team:
                        await self.safe_send(interaction, t.t('team.errors.not_in_team'), ephemeral=True)
                        return
                    
                    membership = self.get_team_member(db, player.id, team.id)
                    if membership.role == 'leader':
                        await self.safe_send(interaction, t.t('team.errors.leader_cannot_leave'), ephemeral=True)
                        return
                    
                    team_name = team.name
                    team_tag = team.tag
                    db.delete(membership)
                    db.commit()
                    db.refresh(team)

                    # actualizar elo del equipo despues de que un miembro salga
                    team.update_team_elo()
                    db.commit()
                    
                    embed = discord.Embed(
                        title=t.t('team.leave.title'),
                        description=t.t('team.leave.description', name=team_name),
                        color=discord.Color.orange()
                    )
                    if not interaction.response.is_done():
                        await interaction.response.send_message(embed=embed)
                    else:
                        await interaction.followup.send(embed=embed, ephemeral=True)
            
                ### EXPULSAR ###
                elif action == "kick":
                    if not member:
                        await self.safe_send(interaction, t.t('team.errors.must_mention', action='expulsar'), ephemeral=True)
                        return
                    
                    team = self.get_player_team(db, player.id)
                    if not team:
                        await self.safe_send(interaction, t.t('team.errors.not_in_team'), ephemeral=True)
                        return
                    
                    membership = self.get_team_member(db, player.id, team.id)
                    if not membership.can_kick():
                        await self.safe_send(interaction, t.t('team.errors.no_permission_kick'), ephemeral=True)
                        return
                    
                    target_player = db.query(Player).filter(Player.discord_id == str(member.id)).first()
                    if not target_player:
                        await self.safe_send(interaction, t.t('team.errors.no_profile'), ephemeral=True)
                        return
                    
                    target_membership = self.get_team_member(db, target_player.id, team.id)
                    if not target_membership:
                        await self.safe_send(interaction, t.t('team.errors.not_in_your_team', member=member.mention), ephemeral=True)
                        return
                    
                    if target_membership.role == 'leader':
                        await self.safe_send(interaction, t.t('team.errors.cannot_kick_leader'), ephemeral=True)
                        return
                    
                    # no permitir expulsar a alguien de mayor o igual rango
                    role_hierarchy = {'leader': 4, 'co-leader': 3, 'staff': 2, 'member': 1}
                    if role_hierarchy.get(target_membership.role, 0) >= role_hierarchy.get(membership.role, 0):
                        await self.safe_send(interaction, t.t('team.errors.cannot_kick_same_rank'), ephemeral=True)
                        return
                    
                    team_name = team.name
                    team_tag = team.tag
                    db.delete(target_membership)
                    db.commit()
                    db.refresh(team)

                    # actualizar del equipo despues de expulsar un miembro
                    team.update_team_elo()
                    db.commit()
                    
                    embed = discord.Embed(
                        title=t.t('team.kick.title'),
                        description=t.t('team.kick.description', member=member.mention, name=team_name),
                        color=discord.Color.red()
                    )
                    if not interaction.response.is_done():
                        await interaction.response.send_message(embed=embed)
                    else:
                        await interaction.followup.send(embed=embed, ephemeral=True)
            
                ### ESTABLECER ROL ###
                elif action == "set-role":
                    if not member or not role:
                        await self.safe_send(interaction, t.t('team.errors.must_mention_role'), ephemeral=True)
                        return
                    
                    team = self.get_player_team(db, player.id)
                    if not team:
                        await self.safe_send(interaction, t.t('team.errors.not_in_team'), ephemeral=True)
                        return
                    
                    membership = self.get_team_member(db, player.id, team.id)
                    if not membership.can_manage_roles():
                        await self.safe_send(interaction, t.t('team.errors.no_permission_roles'), ephemeral=True)
                        return
                    
                    target_player = db.query(Player).filter(Player.discord_id == str(member.id)).first()
                    if not target_player:
                        await self.safe_send(interaction, t.t('team.errors.no_profile'), ephemeral=True)
                        return
                    
                    target_membership = self.get_team_member(db, target_player.id, team.id)
                    if not target_membership:
                        await self.safe_send(interaction, t.t('team.errors.not_in_your_team', member=member.mention), ephemeral=True)
                        return
                    
                    # logica para transferir liderazgo
                    if role == 'leader':
                        
                        # solo el lider actual puede transferir el liderazgo
                        if membership.role != 'leader':
                            await self.safe_send(interaction, t.t('team.errors.only_leader_transfer'), ephemeral=True)
                            return
                        
                        current_leader = team.get_leader()
                        if current_leader and current_leader.player_id != target_player.id:
                            
                            # transferir liderazgo, quitarle el rol de líder al actual y darselo al nuevo
                            current_leader.role = 'member'
                            target_membership.role = 'leader'
                            db.commit()
                            
                            embed = discord.Embed(
                                title=t.t('team.set_role.transfer_title'),
                                description=t.t('team.set_role.transfer_description', name=team.name, member=member.mention),
                                color=discord.Color.gold()
                            )
                            await self.safe_send(interaction, embed=embed)
                            return
                        else:
                            # ya es el lider, no hay nada que hacer
                            await self.safe_send(interaction, t.t('team.errors.already_leader'), ephemeral=True)
                            return
                    
                    # no permitir cambiar el rol del lider actual (excepto para transferir liderazgo)
                    if target_membership.role == 'leader' and role != 'leader':
                        await self.safe_send(interaction, t.t('team.errors.cannot_change_leader'), ephemeral=True)
                        return
                    
                    # solo el lider puede asignar colider
                    if role == 'co-leader' and membership.role != 'leader':
                        await self.safe_send(interaction, t.t('team.errors.only_leader_coleader'), ephemeral=True)
                        return
                    
                    old_role = target_membership.role
                    target_membership.role = role
                    db.commit()
                    
                    embed = discord.Embed(
                        title=t.t('team.set_role.title'),
                        description=t.t('team.set_role.description', member=member.mention, old_role=old_role.title(), role=role.title()),
                        color=discord.Color.green()
                    )
                    await self.safe_send(interaction, embed=embed)
            
                ### ACTUALIZAR LOGO ###
                elif action == "update-logo":
                    team = self.get_player_team(db, player.id)
                    if not team:
                        await self.safe_send(interaction, t.t('team.errors.not_in_team'), ephemeral=True)
                        return
                    
                    # verificar que sea lider o colider
                    membership = self.get_team_member(db, player.id, team.id)
                    if not membership or membership.role not in ['leader', 'co-leader']:
                        await self.safe_send(interaction, 
                            "❌ Solo los líderes y co-líderes pueden actualizar el logo del equipo",
                            ephemeral=True
                        )
                        return
                    
                    # verificar que se haya adjuntado una imagen
                    if not logo:
                        await self.safe_send(interaction,
                            "❌ Debes adjuntar una imagen para actualizar el logo. Por favor, adjunta una imagen PNG.",
                            ephemeral=True
                        )
                        return
                    
                    # validar que sea una imagen png
                    is_png = False
                    if logo.content_type == 'image/png':
                        is_png = True
                    elif logo.filename and logo.filename.lower().endswith('.png'):
                        is_png = True
                    
                    if not is_png:
                        await self.safe_send(interaction,
                            "❌ El logo debe ser una imagen en formato PNG",
                            ephemeral=True
                        )
                        return
                    
                    # actualizar el logo
                    team.logo_url = logo.url
                    db.commit()
                    
                    # confirmar actualizacion
                    embed = discord.Embed(
                        title="✅ Logo actualizado",
                        description=f"El logo de **{team.name}** ha sido actualizado exitosamente.",
                        color=discord.Color.green()
                    )
                    embed.set_image(url=logo.url)
                    await self.safe_send(interaction, embed=embed, ephemeral=False)
            
                ### DISOLVER EQUIPO ###
                elif action == "disband":
                    team = self.get_player_team(db, player.id)
                    if not team:
                        await self.safe_send(interaction, t.t('team.errors.not_in_team'), ephemeral=True)
                        return
                    
                    membership = self.get_team_member(db, player.id, team.id)
                    if not membership or not membership.can_disband():
                        await self.safe_send(interaction, t.t('team.errors.only_leader_disband'), ephemeral=True)
                        return
                    
                    # primera confirmacion
                    embed = discord.Embed(
                        title=t.t('team.disband.confirm_title'),
                        description=t.t('team.disband.confirm_description', name=team.name, tag=team.tag),
                        color=discord.Color.orange()
                    )
                    embed.set_footer(text=t.t('team.disband.confirm_footer'))
                    
                    view = DisbandConfirmView(team.id, player.id, self)
                    await self.safe_send(interaction, embed=embed, view=view, ephemeral=True)
                else:
                    t = get_player_translator(player) if player else get_translator('es')
                    await interaction.response.send_message(t.t('errors.generic', error='Acción no reconocida'), ephemeral=True)
        except Exception as e:
            print(f"❌ Error en comando team: {e}")
            import traceback
            traceback.print_exc()
            with get_db() as db:
                player = db.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
                t = get_player_translator(player) if player else get_translator('es')
            
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    t.t('errors.generic', error=str(e)),
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    t.t('errors.generic', error=str(e)),
                    ephemeral=True
                )
    
    def get_role_emoji(self, role):
        """Retorna el emoji correspondiente al rol"""
        emojis = {
            'leader': '👑',
            'co-leader': '⭐',
            'staff': '🛡️',
            'member': '👤'
        }
        return emojis.get(role, '👤')

class DisbandConfirmView(discord.ui.View):
    """Vista para confirmar la disolución de un equipo (doble confirmación)"""
    def __init__(self, team_id: int, leader_id: int, cog):
        super().__init__(timeout=60)  # 60 segundos para confirmar
        self.team_id = team_id
        self.leader_id = leader_id
        self.cog = cog
    
    @discord.ui.button(label="Sí, Disolver", style=discord.ButtonStyle.danger)
    async def confirm_disband(self, interaction: discord.Interaction, button: discord.ui.Button):
        
        # verificar que sea el lider
        with get_db() as db:
            player = db.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
            t = get_player_translator(player) if player else get_translator('es')
            
            if not player or player.id != self.leader_id:
                await interaction.response.send_message(t.t('team.errors.only_leader_disband'), ephemeral=True)
                return
            
            team = db.query(Team).filter(Team.id == self.team_id).first()
            if not team:
                await interaction.response.send_message(t.t('team.disband.errors.not_exists'), ephemeral=True)
                self.stop()
                return
            
            # segunda confirmacion
            embed = discord.Embed(
                title=t.t('team.disband.final_title'),
                description=t.t('team.disband.final_description', name=team.name, tag=team.tag),
                color=discord.Color.red()
            )
            embed.set_footer(text=t.t('team.disband.final_footer'))
            
            # cambiar a vista de confirmacion final
            final_view = DisbandFinalView(self.team_id, self.leader_id, self.cog)
            await interaction.response.edit_message(embed=embed, view=final_view)
    
    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel_disband(self, interaction: discord.Interaction, button: discord.ui.Button):
        with get_db() as db:
            player = db.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
            t = get_player_translator(player) if player else get_translator('es')
        
        await interaction.response.edit_message(
            content=t.t('team.disband.cancelled'),
            embed=None,
            view=None
        )
        self.stop()

class DisbandFinalView(discord.ui.View):
    """Vista para la confirmación final de disolución"""
    def __init__(self, team_id: int, leader_id: int, cog):
        super().__init__(timeout=30)  # 30 segundos para la confirmacion final
        self.team_id = team_id
        self.leader_id = leader_id
        self.cog = cog
    
    @discord.ui.button(label="Confirmar Disolución", style=discord.ButtonStyle.danger)
    async def final_confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        # verificar que sea el lider
        with get_db() as db:
            player = db.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
            t = get_player_translator(player) if player else get_translator('es')
            
            if not player or player.id != self.leader_id:
                await interaction.response.send_message(t.t('team.errors.only_leader_disband'), ephemeral=True)
                return
            
            team = db.query(Team).filter(Team.id == self.team_id).first()
            if not team:
                await interaction.response.send_message(t.t('team.disband.errors.not_exists'), ephemeral=True)
                self.stop()
                return
            
            team_id = team.id
            team_name = team.name
            team_tag = team.tag
            
            # eliminar TODOS los datos relacionados con el equipo
            # eliminar invitaciones pendientes del equipo
            db.query(TeamInvite).filter(TeamInvite.team_id == team_id).delete(synchronize_session=False)
            
            # eliminar guerras relacionadas
            wars = db.query(TeamWar).filter(
                or_(TeamWar.team1_id == team_id, TeamWar.team2_id == team_id)
            ).all()
            for war in wars:
                # eliminar partidas de la guerra
                db.query(TeamWarMatch).filter(TeamWarMatch.war_id == war.id).delete(synchronize_session=False)
                # eliminar la guerra
                db.delete(war)
            
            # eliminar referencias del equipo en partidas (poner a None)
            db.query(Match).filter(Match.team1_id == team_id).update({'team1_id': None}, synchronize_session=False)
            db.query(Match).filter(Match.team2_id == team_id).update({'team2_id': None}, synchronize_session=False)
            
            # eliminar todos los miembros del equipo
            db.query(TeamMember).filter(TeamMember.team_id == team_id).delete(synchronize_session=False)
            
            # eliminar el equipo
            db.delete(team)
            db.commit()
            
            embed = discord.Embed(
                title=t.t('team.disband.completed_title'),
                description=t.t('team.disband.completed_description', name=team_name, tag=team_tag),
                color=discord.Color.red()
            )
            await interaction.response.edit_message(embed=embed, view=None)
            self.stop()
    
    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel_final(self, interaction: discord.Interaction, button: discord.ui.Button):
        with get_db() as db:
            player = db.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
            t = get_player_translator(player) if player else get_translator('es')
        
        await interaction.response.edit_message(
            content=t.t('team.disband.cancelled'),
            embed=None,
            view=None
        )
        self.stop()

class TeamInviteView(discord.ui.View):
    def __init__(self, invite_id: int, team_id: int, player_id: int):
        super().__init__(timeout=604800) # 7 dias
        self.invite_id = invite_id
        self.team_id = team_id
        self.player_id = player_id
    
    @discord.ui.button(label="Aceptar", style=discord.ButtonStyle.success)
    async def accept_invite(self, interaction: discord.Interaction, button: discord.ui.Button):
        with get_db() as db:
            player = db.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
            if not player:
                # crear jugador si no existe
                player = Player(
                    discord_id=str(interaction.user.id),
                    username=interaction.user.name
                )
                try:
                    db.add(player)
                    db.commit()
                    db.refresh(player)
                except Exception:
                    db.rollback()
                    player = db.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
                    if player:
                        player.username = interaction.user.name
                        db.commit()
                        db.refresh(player)
            
            t = get_player_translator(player) if player else get_translator('es')
            
            if not player or player.id != self.player_id:
                if not interaction.response.is_done():
                    await interaction.response.send_message(t.t('team.invite.errors.not_for_you'), ephemeral=True)
                else:
                    await interaction.followup.send(t.t('team.invite.errors.not_for_you'), ephemeral=True)
                return
            
            invite = db.query(TeamInvite).filter(TeamInvite.id == self.invite_id).first()
            if not invite or invite.status != 'pending':
                if not interaction.response.is_done():
                    await interaction.response.send_message(t.t('team.invite.errors.invalid'), ephemeral=True)
                else:
                    await interaction.followup.send(t.t('team.invite.errors.invalid'), ephemeral=True)
                return
            
            if invite.expires_at and invite.expires_at < datetime.utcnow():
                invite.status = 'expired'
                db.commit()
                if not interaction.response.is_done():
                    await interaction.response.send_message(t.t('team.invite.errors.expired'), ephemeral=True)
                else:
                    await interaction.followup.send(t.t('team.invite.errors.expired'), ephemeral=True)
                return
            
            team = db.query(Team).filter(Team.id == self.team_id).first()
            if team.member_count() >= 50:
                invite.status = 'declined'
                db.commit()
                if not interaction.response.is_done():
                    await interaction.response.send_message(t.t('team.invite.errors.team_full'), ephemeral=True)
                else:
                    await interaction.followup.send(t.t('team.invite.errors.team_full'), ephemeral=True)
                return
            
            # verificar que no este en otro equipo
            existing_membership = db.query(TeamMember).filter(TeamMember.player_id == player.id).first()
            if existing_membership:
                if not interaction.response.is_done():
                    await interaction.response.send_message(t.t('team.invite.errors.already_in_team'), ephemeral=True)
                else:
                    await interaction.followup.send(t.t('team.invite.errors.already_in_team'), ephemeral=True)
                return
            
            invite.status = 'accepted'
            membership = TeamMember(
                team_id=team.id,
                player_id=player.id,
                role='member'
            )
            db.add(membership)
            db.commit()
            db.refresh(team)
            
            # actualizar elo del equipo despues de que un jugador se una
            team.update_team_elo()
            db.commit()
            
            # borrar el mensaje original antes de responder
            try:
                if interaction.message:
                    await interaction.message.delete()
            except:
                pass
            
            # Responder a la interacción
            embed = discord.Embed(
                title=t.t('team.invite.accepted.title'),
                description=t.t('team.invite.accepted.description', name=team.name),
                color=discord.Color.green()
            )
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=embed)
            else:
                await interaction.followup.send(embed=embed, ephemeral=True)
            
            self.stop()
    
    @discord.ui.button(label="Rechazar", style=discord.ButtonStyle.danger)
    async def decline_invite(self, interaction: discord.Interaction, button: discord.ui.Button):
        with get_db() as db:
            player = db.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
            t = get_player_translator(player) if player else get_translator('es')
            
            if not player or player.id != self.player_id:
                await interaction.response.send_message(t.t('team.invite.errors.not_for_you'), ephemeral=True)
                return
            
            invite = db.query(TeamInvite).filter(TeamInvite.id == self.invite_id).first()
            if invite:
                invite.status = 'declined'
                db.commit()
            
            # borrar el mensaje original antes de responder
            try:
                if interaction.message:
                    await interaction.message.delete()
            except:
                pass
            
            await interaction.response.send_message(t.t('team.invite.rejected.message'), ephemeral=True)
            self.stop()

async def setup(bot):
    await bot.add_cog(TeamsCog(bot))

