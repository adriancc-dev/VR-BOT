import discord
from discord import app_commands
from discord.ext import commands
from database.database import get_db
from database.models import Player, Tournament, TournamentParticipant
from config import CHALLONGE_CLIENT_ID, CHALLONGE_CLIENT_SECRET, CHALLONGE_USERNAME, CHALLONGE_API_KEY, ADMIN_IDS
from utils.i18n import get_player_translator, get_translator
from utils.rank_roles import update_member_rank_roles
from sqlalchemy import or_, func
import aiohttp
import asyncio
from datetime import datetime
from typing import Optional
import json
import re
import logging

try:
    from dateutil import parser as date_parser
except ImportError:
    date_parser = None

logger = logging.getLogger(__name__)

class TournamentsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.base_url = "https://api.challonge.com/v2.1"
        self.access_token = None
        self.token_expires_at = None
        
        # verificar credenciales al inicializar
        if not CHALLONGE_CLIENT_ID or not CHALLONGE_CLIENT_SECRET:
            if not CHALLONGE_USERNAME or not CHALLONGE_API_KEY:
                print("⚠️  ADVERTENCIA: No hay credenciales de Challonge configuradas")
                print(f"   CLIENT_ID: {'✅' if CHALLONGE_CLIENT_ID else '❌'}")
                print(f"   CLIENT_SECRET: {'✅' if CHALLONGE_CLIENT_SECRET else '❌'}")
                print(f"   USERNAME: {'✅' if CHALLONGE_USERNAME else '❌'}")
                print(f"   API_KEY: {'✅' if CHALLONGE_API_KEY else '❌'}")
            else:
                print("✅ Usando credenciales API v1 (legacy) para Challonge")
        else:
            print(f"✅ Credenciales Challonge Connect configuradas (Client ID: {CHALLONGE_CLIENT_ID[:10]}...)")
    
    async def finish_tournament(self, tournament: Tournament):
        """Procesa el final del torneo: obtiene top 5, otorga ELO y muestra resultados"""
        try:
            # obtener participantes con final_rank (usar url, no id)
            participants_data = await self.challonge_request('GET', f'tournaments/{tournament.challonge_url}/participants.json')
            if isinstance(participants_data, dict) and 'data' in participants_data:
                participants = participants_data.get('data', [])
            else:
                participants = participants_data.get('participants', [])
            
            # extraer participantes con sus final_rank
            participants_with_rank = []
            for p in participants:
                if isinstance(p, dict) and 'attributes' in p:
                    attrs = p.get('attributes', {})
                    name = attrs.get('name', '')
                    final_rank = attrs.get('final_rank')
                    participant_id = p.get('id')
                else:
                    name = p.get('name', '')
                    final_rank = p.get('final_rank')
                    participant_id = p.get('id')
                
                if final_rank is not None:
                    participants_with_rank.append({
                        'name': name,
                        'final_rank': final_rank,
                        'id': participant_id
                    })
            
            # ordenar por final_rank (1 es el mejor)
            participants_with_rank.sort(key=lambda x: x['final_rank'])
            
            # obtener top 5
            top_5 = participants_with_rank[:5]
            
            if not top_5:
                return None  # no hay participantes con ranking
            
            # elo por posición: top 1: 500, top 2: 400, top 3: 300, top 4: 200, top 5: 100
            elo_rewards = {1: 500, 2: 400, 3: 300, 4: 200, 5: 100}
            
            # otorgar elo a los top 5
            with get_db() as db:
                top_5_players = []
                for participant in top_5:
                    rank = participant['final_rank']
                    participant_name = participant['name']
                    elo_to_add = elo_rewards.get(rank, 0)
                    
                    # buscar jugador por nombre (display name o username)
                    # intentar buscar por discord_id primero si el nombre coincide con algun usuario
                    player = None
                    
                    # buscar en la base de datos por username
                    player = db.query(Player).filter(Player.username == participant_name).first()
                    
                    # si no se encuentra, intentar buscar por discord_id si podemos obtenerlo del servidor
                    if not player and tournament.panel_channel_id:
                        try:
                            channel = self.bot.get_channel(int(tournament.panel_channel_id))
                            if channel and channel.guild:
                                # buscar miembro por display name o username
                                for member in channel.guild.members:
                                    if (member.display_name == participant_name or 
                                        member.name == participant_name):
                                        player = db.query(Player).filter(
                                            Player.discord_id == str(member.id)
                                        ).first()
                                        break
                        except:
                            pass
                    
                    if player:
                        # actualizar elo 1v1
                        old_elo = player.elo_1v1 if player.elo_1v1 is not None else 0
                        player.elo_1v1 = old_elo + elo_to_add
                        db.commit()
                        db.refresh(player)
                        
                        top_5_players.append({
                            'name': participant_name,
                            'rank': rank,
                            'elo_gained': elo_to_add,
                            'new_elo': player.elo_1v1,
                            'player': player
                        })
                    else:
                        # si no se encuentra el jugador, aun lo agregamos al top 5 pero sin elo
                        top_5_players.append({
                            'name': participant_name,
                            'rank': rank,
                            'elo_gained': elo_to_add,
                            'new_elo': None,
                            'player': None
                        })
            
            return top_5_players
            
        except Exception as e:
            print(f"Error al finalizar torneo: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    async def update_bracket_message(self, tournament: Tournament):
        """Actualiza el mensaje del bracket en panel_channel"""
        if not tournament.bracket_message_id or not tournament.panel_channel_id:
            return
        
        try:
            channel = self.bot.get_channel(int(tournament.panel_channel_id))
            if not channel:
                return
            
            message = await channel.fetch_message(int(tournament.bracket_message_id))
            
            # obtener informacion actualizada
            tournament_data = await self.challonge_request('GET', f'tournaments/{tournament.challonge_url}.json')
            if isinstance(tournament_data, dict) and 'data' in tournament_data:
                challonge_tournament = tournament_data.get('data', {}).get('attributes', {})
            else:
                challonge_tournament = tournament_data.get('tournament', tournament_data)
            
            # obtener participantes con paginacion
            participants = []
            page = 1
            per_page = 200
            total_pages = 1
            
            while page <= total_pages:
                participants_data = await self.challonge_request('GET', f'tournaments/{tournament.challonge_url}/participants.json?page={page}&per_page={per_page}')
                
                if isinstance(participants_data, dict) and 'data' in participants_data:
                    page_participants = participants_data.get('data', [])
                    meta = participants_data.get('meta', {})
                    if meta:
                        pagination = meta.get('pagination', {})
                        total_pages = pagination.get('total_pages', 1)
                else:
                    page_participants = participants_data.get('participants', [])
                    total_pages = 1
                
                participants.extend(page_participants)
                page += 1
                if page > total_pages:
                    break
            
            # obtener partidos con paginacion
            matches = []
            page = 1
            total_pages = 1
            
            while page <= total_pages:
                matches_data = await self.challonge_request('GET', f'tournaments/{tournament.challonge_url}/matches.json?page={page}&per_page={per_page}')
                
                if isinstance(matches_data, dict) and 'data' in matches_data:
                    page_matches = matches_data.get('data', [])
                    meta = matches_data.get('meta', {})
                    if meta:
                        pagination = meta.get('pagination', {})
                        total_pages = pagination.get('total_pages', 1)
                else:
                    page_matches = matches_data.get('matches', [])
                    total_pages = 1
                
                matches.extend(page_matches)
                page += 1
                if page > total_pages:
                    break
            
            embed = discord.Embed(
                title=f"📊 Bracket - {tournament.name}",
                description=f"**Juego:** {tournament.game or 'N/A'}\n**Estado:** {challonge_tournament.get('state', 'Pendiente')}",
                color=discord.Color.blue()
            )
            embed.add_field(name="👥 Participantes", value=str(len(participants)), inline=True)
            embed.add_field(name="⚔️ Partidos", value=str(len(matches)), inline=True)
            embed.add_field(
                name="🔗 Ver Bracket Completo",
                value=f"https://challonge.com/{tournament.challonge_url}",
                inline=False
            )
            
            # mostrar partidos en curso
            if matches:
                open_matches = []
                for match in matches:
                    if isinstance(match, dict) and 'attributes' in match:
                        attrs = match.get('attributes', {})
                        state = attrs.get('state', '')
                        if state == 'open':
                            p1 = attrs.get('player1', {})
                            p2 = attrs.get('player2', {})
                            p1_name = p1.get('name', 'TBD') if isinstance(p1, dict) else 'TBD'
                            p2_name = p2.get('name', 'TBD') if isinstance(p2, dict) else 'TBD'
                            scores = attrs.get('scores_csv', '')
                            if scores:
                                open_matches.append(f"⚔️ {p1_name} {scores} {p2_name}")
                            else:
                                open_matches.append(f"⚔️ {p1_name} vs {p2_name}")
                    else:
                        state = match.get('state', '')
                        if state == 'open':
                            p1 = match.get('player1', {})
                            p2 = match.get('player2', {})
                            p1_name = p1.get('name', 'TBD') if isinstance(p1, dict) else 'TBD'
                            p2_name = p2.get('name', 'TBD') if isinstance(p2, dict) else 'TBD'
                            scores = match.get('scores_csv', '')
                            if scores:
                                open_matches.append(f"⚔️ {p1_name} {scores} {p2_name}")
                            else:
                                open_matches.append(f"⚔️ {p1_name} vs {p2_name}")
                
                if open_matches:
                    embed.add_field(
                        name="🔴 Partidos en Curso",
                        value="\n".join(open_matches[:5]),
                        inline=False
                    )
            
            view = TournamentBracketView(tournament.id, self)
            await message.edit(embed=embed, view=view)
            
        except Exception as e:
            print(f"Error al actualizar mensaje del bracket: {e}")
    
    async def get_access_token(self):
        """Obtiene un token de acceso usando OAuth Client Credentials"""
        # si hay token valido, usarlo
        if self.access_token and self.token_expires_at and datetime.utcnow().timestamp() < self.token_expires_at:
            return self.access_token
        
        # intentar usar challonge connect (OAuth) primero
        if CHALLONGE_CLIENT_ID and CHALLONGE_CLIENT_SECRET:
            try:
                async with aiohttp.ClientSession() as session:
                    # OAuth client credentials flow
                    data = {
                        'grant_type': 'client_credentials',
                        'client_id': CHALLONGE_CLIENT_ID,
                        'client_secret': CHALLONGE_CLIENT_SECRET,
                        'scope': 'tournaments:read tournaments:write matches:read matches:write participants:read participants:write'
                    }
                    async with session.post('https://api.challonge.com/oauth/token', data=data) as resp:
                        if resp.status == 200:
                            token_data = await resp.json()
                            self.access_token = token_data.get('access_token')
                            
                            # el token generalmente expira en 1 hora, se guardan 55 minutos para seguridad
                            expires_in = token_data.get('expires_in', 3600)
                            self.token_expires_at = datetime.utcnow().timestamp() + (expires_in - 300)
                            return self.access_token
            except Exception as e:
                print(f"Error obteniendo token OAuth: {e}")
        
        # fallback a api v1 si OAuth no esta disponible
        if CHALLONGE_USERNAME and CHALLONGE_API_KEY:
            
            # para api v1 usamos basic auth directamente
            return None
        
        raise Exception("No hay credenciales de Challonge configuradas")
    
    async def challonge_request(self, method: str, endpoint: str, **kwargs):
        """Hace una petición a la API de Challonge v2.1 o v1 según credenciales"""
        token = await self.get_access_token()
        use_v1 = False
        
        if token:
            
            # usar OAuth token con api v2.1
            url = f"{self.base_url}/{endpoint}"
            headers = {
                'Content-Type': 'application/vnd.api+json',
                'Accept': 'application/json',
                'Authorization': f'Bearer {token}',
                'Authorization-Type': 'v2'
            }
            auth = None
        elif CHALLONGE_USERNAME and CHALLONGE_API_KEY:

            # usar basic auth para api v1
            use_v1 = True
            url = f"https://api.challonge.com/v1/{endpoint}"
            headers = {
                'Accept': 'application/json'
                # no establecer conten type aqui, aiohttp lo hara automaticamente segun el tipo de data
            }
            auth = aiohttp.BasicAuth(CHALLONGE_USERNAME, CHALLONGE_API_KEY)
        else:
            raise Exception("No hay credenciales de Challonge configuradas")
        
        # manejar data para post/put
        if 'data' in kwargs:
            data = kwargs.pop('data')
            if use_v1:

                # api v1: usar form data (application/x-www-form-urlencoded)
                if isinstance(data, dict):
                    
                    # si tiene 'data' dentro, es formato v2.1, convertir a v1
                    if 'data' in data and 'attributes' in data['data']:
                        attrs = data['data']['attributes']
                        
                        # si tiene 'match' array (formato v2.1 nuevo), convertir a scores_csv
                        if 'match' in attrs and isinstance(attrs['match'], list):
                            
                            # convertir formato match array a scores_csv
                            match_array = attrs['match']
                            scores = []
                            for match_item in match_array:
                                if isinstance(match_item, dict):
                                    score = match_item.get('score_set', '0')
                                    scores.append(score)
                            if len(scores) >= 2:
                                scores_csv = f"{scores[0]}-{scores[1]}"
                                v1_data = {'match[scores_csv]': scores_csv}
                                
                                # challonge v1 determina automaticamente el ganador con scores_csv
                            else:
                                
                                # fallback, usar el formato original
                                v1_data = {}
                                for key, value in attrs.items():
                                    if key != 'match':
                                        v1_data[f"match[{key}]"] = value
                        else:
                            # convertir de v2.1 a v1
                            v1_data = {}
                            for key, value in attrs.items():
                                v1_data[f"match[{key}]"] = value
                        logger.info(f"🔄 Convertido formato v2.1 a v1: {v1_data}")
                        
                        # usar FormData para asegurar que se envie como form data
                        form_data = aiohttp.FormData()
                        for k, v in v1_data.items():
                            form_data.add_field(k, str(v))
                        kwargs['data'] = form_data
                    elif 'data' in data:
                        # formato v2.1 sin attributes, extraer directamente
                        v1_data = {}
                        for key, value in data['data'].items():
                            if key != 'type' and key != 'id':
                                v1_data[f"match[{key}]"] = value
                        logger.info(f"🔄 Convertido formato v2.1 (sin attributes) a v1: {v1_data}")
                        form_data = aiohttp.FormData()
                        for k, v in v1_data.items():
                            form_data.add_field(k, str(v))
                        kwargs['data'] = form_data
                    else:
                        # ya esta en formato v1 (con match[key])
                        logger.info(f"✅ Ya está en formato v1: {data}")
                        # asegurar que se envie como form data
                        form_data = aiohttp.FormData()
                        for k, v in data.items():
                            form_data.add_field(k, str(v))
                        kwargs['data'] = form_data
                else:
                    kwargs['data'] = data
            else:
                # API v2.1: usar JSON API format
                if isinstance(data, dict):
                    kwargs['json'] = data
                else:
                    kwargs['data'] = data
        
        async with aiohttp.ClientSession() as session:
            # Log para debugging
            if use_v1 and 'data' in kwargs:
                logger.info(f"📤 Enviando request v1: {method} {url}")
                logger.info(f"📦 Data: {kwargs.get('data')}")
                logger.info(f"📋 Headers: {headers}")
            
            async with session.request(method, url, headers=headers, auth=auth, **kwargs) as resp:
                # DELETE devuelve 204 (No Content) que es éxito
                if resp.status == 200 or resp.status == 201 or resp.status == 204:
                    if resp.status == 204:
                        return {}  # DELETE exitoso, no hay contenido
                    try:
                        result = await resp.json()
                        if use_v1:
                            logger.info(f"✅ Respuesta Challonge v1: {result}")
                        return result
                    except:
                        result = {}
                        if use_v1:
                            logger.info(f"✅ Respuesta Challonge v1 (sin JSON): {result}")
                        return result
                else:
                    error_text = await resp.text()
                    logger.error(f"❌ Error en Challonge API ({resp.status}): {error_text}")
                    try:
                        error_json = await resp.json()
                        # Manejar diferentes formatos de errores de Challonge API v2.1
                        errors = error_json.get('errors', {})
                        error_detail = error_text
                        
                        # Si errors es una lista
                        if isinstance(errors, list) and len(errors) > 0:
                            error_obj = errors[0]
                            if isinstance(error_obj, dict):
                                error_detail = error_obj.get('detail', error_text)
                                if isinstance(error_detail, list):
                                    error_detail = error_detail[0] if error_detail else error_text
                        # Si errors es un diccionario
                        elif isinstance(errors, dict):
                            error_detail = errors.get('detail', error_text)
                            if isinstance(error_detail, list):
                                error_detail = error_detail[0] if error_detail else error_text
                        
                        raise Exception(f"Error de API: {resp.status} - {error_detail}")
                    except Exception as e:
                        # Si ya es nuestra excepción, re-raise
                        if "Error de API" in str(e):
                            raise
                        # Si no, crear nueva excepción con el texto original
                        raise Exception(f"Error de API: {resp.status} - {error_text}")
    
    def get_player(self, db, discord_id: str):
        """Obtiene o crea un jugador"""
        player = db.query(Player).filter(Player.discord_id == str(discord_id)).first()
        if not player:
            user = self.bot.get_user(int(discord_id))
            username = user.name if user else f"User_{discord_id}"
            player = Player(
                discord_id=str(discord_id),
                username=username,
                elo=0,
                elo_1v1=0
            )
            db.add(player)
            db.commit()
            db.refresh(player)
        return player
    
    @app_commands.command(name="create-tournament", description="Crea un torneo con sistema de inscripción mejorado (solo administradores)")
    @app_commands.describe(
        challonge_link="Link del torneo en Challonge (ej: https://challonge.com/torneo-2024 o solo 'torneo-2024')",
        tournament_name="Nombre del torneo",
        game="Tipo de juego (ej: Inazuma Eleven, FIFA, etc.)",
        start_date="Fecha de inicio del torneo (formato: YYYY-MM-DD HH:MM o timestamp)",
        advertise="Si se debe anunciar el torneo (True/False)",
        participant_role="Rol de participantes del torneo",
        organizer_role="Rol de organizadores del torneo",
        inscription_channel="Canal donde se publicará el mensaje de inscripción",
        panel_channel="Canal donde se mostrará el bracket del torneo",
        result_channel="Canal donde se reportarán los resultados (escribe el score aquí y se marcará automáticamente)"
    )
    async def create_tournament_new(
        self,
        interaction: discord.Interaction,
        challonge_link: str,
        tournament_name: str,
        game: str,
        start_date: str,
        advertise: bool = True,
        participant_role: discord.Role = None,
        organizer_role: discord.Role = None,
        inscription_channel: discord.TextChannel = None,
        panel_channel: discord.TextChannel = None,
        result_channel: discord.TextChannel = None
    ):
        """Crea un torneo con sistema de inscripción mejorado"""
        
        # Verificar permisos: administrador de Discord o en la lista de ADMIN_IDS
        is_admin = (
            interaction.user.guild_permissions.administrator or
            interaction.user.id in ADMIN_IDS
        )
        
        if not is_admin:
            await interaction.response.send_message(
                "❌ Solo los administradores pueden usar este comando.",
                ephemeral=True
            )
            return
        
        await interaction.response.defer(ephemeral=True)
        
        with get_db() as db:
            player = self.get_player(db, str(interaction.user.id))
            t = get_player_translator(player) if player else get_translator('es')
            
            try:
                # Extraer URL del link de Challonge
                challonge_url = challonge_link
                if 'challonge.com/' in challonge_link:
                    challonge_url = challonge_link.split('challonge.com/')[-1].split('/')[0].split('?')[0]
                
                # Validar formato de URL
                original_url = challonge_url
                challonge_url = re.sub(r'[^a-zA-Z0-9_]', '_', challonge_url)
                challonge_url = re.sub(r'_+', '_', challonge_url)
                challonge_url = challonge_url.strip('_')
                
                if not challonge_url:
                    await interaction.followup.send(
                        "❌ URL de Challonge inválida.",
                        ephemeral=True
                    )
                    return
                
                # Verificar que el torneo existe en Challonge
                try:
                    tournament_data = await self.challonge_request('GET', f'tournaments/{challonge_url}.json')
                    if isinstance(tournament_data, dict) and 'data' in tournament_data:
                        challonge_tournament = tournament_data.get('data', {}).get('attributes', {})
                        challonge_tournament_id = tournament_data.get('data', {}).get('id')
                    else:
                        challonge_tournament = tournament_data.get('tournament', tournament_data)
                        challonge_tournament_id = challonge_tournament.get('id')
                except Exception as e:
                    await interaction.followup.send(
                        f"❌ No se pudo encontrar el torneo en Challonge con la URL '{challonge_url}'. "
                        f"Error: {str(e)}",
                        ephemeral=True
                    )
                    return
                
                # Parsear fecha de inicio
                start_datetime = None
                try:
                    # Intentar diferentes formatos
                    if date_parser:
                        start_datetime = date_parser.parse(start_date)
                    else:
                        # Formato simple YYYY-MM-DD HH:MM
                        start_datetime = datetime.strptime(start_date, "%Y-%m-%d %H:%M")
                except:
                    try:
                        # Formato simple YYYY-MM-DD HH:MM
                        start_datetime = datetime.strptime(start_date, "%Y-%m-%d %H:%M")
                    except:
                        await interaction.followup.send(
                            "❌ Formato de fecha inválido. Usa: YYYY-MM-DD HH:MM",
                            ephemeral=True
                        )
                        return
                
                # Verificar si el torneo ya existe en la BD
                existing = db.query(Tournament).filter(
                    Tournament.challonge_url == challonge_url
                ).first()
                
                if existing:
                    # Actualizar torneo existente
                    tournament = existing
                else:
                    # Crear nuevo torneo en BD
                    tournament = Tournament(
                        challonge_tournament_id=challonge_tournament_id,
                        challonge_url=challonge_url,
                        name=tournament_name,
                        tournament_type=challonge_tournament.get('tournament_type', 'single elimination'),
                        status=challonge_tournament.get('state', 'pending'),
                        created_by=player.id,
                        game=game,
                        start_date=start_datetime,
                        advertise=advertise,
                        participant_role_id=str(participant_role.id) if participant_role else None,
                        organizer_role_id=str(organizer_role.id) if organizer_role else None,
                        inscription_channel_id=str(inscription_channel.id) if inscription_channel else None,
                        panel_channel_id=str(panel_channel.id) if panel_channel else None,
                        result_channel_id=str(result_channel.id) if result_channel else None
                    )
                    db.add(tournament)
                
                # Actualizar campos
                tournament.game = game
                tournament.start_date = start_datetime
                tournament.advertise = advertise
                tournament.participant_role_id = str(participant_role.id) if participant_role else None
                tournament.organizer_role_id = str(organizer_role.id) if organizer_role else None
                tournament.inscription_channel_id = str(inscription_channel.id) if inscription_channel else None
                tournament.panel_channel_id = str(panel_channel.id) if panel_channel else None
                tournament.result_channel_id = str(result_channel.id) if result_channel else None
                
                db.commit()
                db.refresh(tournament)
                
                # Crear mensaje de inscripción en inscription_channel
                inscription_message = None
                if inscription_channel:
                    try:
                        view = TournamentInscriptionView(tournament.id, self)
                        embed = discord.Embed(
                            title=f"🏆 {tournament_name}",
                            description=f"**Juego:** {game}\n**Fecha de inicio:** {start_datetime.strftime('%Y-%m-%d %H:%M') if start_datetime else 'Por determinar'}\n\n¡Inscríbete al torneo usando los botones de abajo!",
                            color=discord.Color.gold()
                        )
                        embed.add_field(name="🔗 Bracket", value=f"https://challonge.com/{challonge_url}", inline=False)
                        embed.set_footer(text="Haz clic en los botones para inscribirte o cancelar tu inscripción")
                        
                        inscription_message = await inscription_channel.send(embed=embed, view=view)
                        tournament.inscription_message_id = str(inscription_message.id)
                        db.commit()
                    except Exception as e:
                        print(f"Error al enviar mensaje de inscripción: {e}")
                
                # Crear mensaje del bracket en panel_channel
                bracket_message = None
                if panel_channel:
                    try:
                        # Obtener información actualizada del torneo (usar URL, no ID)
                        # Obtener participantes con paginación
                        participants = []
                        page = 1
                        per_page = 200
                        total_pages = 1
                        
                        while page <= total_pages:
                            participants_data = await self.challonge_request('GET', f'tournaments/{challonge_url}/participants.json?page={page}&per_page={per_page}')
                            
                            if isinstance(participants_data, dict) and 'data' in participants_data:
                                page_participants = participants_data.get('data', [])
                                meta = participants_data.get('meta', {})
                                if meta:
                                    pagination = meta.get('pagination', {})
                                    total_pages = pagination.get('total_pages', 1)
                            else:
                                page_participants = participants_data.get('participants', [])
                                total_pages = 1
                            
                            participants.extend(page_participants)
                            page += 1
                            if page > total_pages:
                                break
                        
                        # Obtener partidos con paginación
                        matches = []
                        page = 1
                        total_pages = 1
                        
                        while page <= total_pages:
                            matches_data = await self.challonge_request('GET', f'tournaments/{challonge_url}/matches.json?page={page}&per_page={per_page}')
                            
                            if isinstance(matches_data, dict) and 'data' in matches_data:
                                page_matches = matches_data.get('data', [])
                                meta = matches_data.get('meta', {})
                                if meta:
                                    pagination = meta.get('pagination', {})
                                    total_pages = pagination.get('total_pages', 1)
                            else:
                                page_matches = matches_data.get('matches', [])
                                total_pages = 1
                            
                            matches.extend(page_matches)
                            page += 1
                            if page > total_pages:
                                break
                        
                        embed = discord.Embed(
                            title=f"📊 Bracket - {tournament_name}",
                            description=f"**Juego:** {game}\n**Estado:** {challonge_tournament.get('state', 'Pendiente')}",
                            color=discord.Color.blue()
                        )
                        embed.add_field(name="👥 Participantes", value=str(len(participants)), inline=True)
                        embed.add_field(name="⚔️ Partidos", value=str(len(matches)), inline=True)
                        embed.add_field(
                            name="🔗 Ver Bracket Completo",
                            value=f"https://challonge.com/{challonge_url}",
                            inline=False
                        )
                        
                        # Mostrar partidos en curso si hay
                        if matches:
                            open_matches = []
                            for match in matches:
                                if isinstance(match, dict) and 'attributes' in match:
                                    attrs = match.get('attributes', {})
                                    state = attrs.get('state', '')
                                    if state == 'open':
                                        p1 = attrs.get('player1', {})
                                        p2 = attrs.get('player2', {})
                                        p1_name = p1.get('name', 'TBD') if isinstance(p1, dict) else 'TBD'
                                        p2_name = p2.get('name', 'TBD') if isinstance(p2, dict) else 'TBD'
                                        open_matches.append(f"⚔️ {p1_name} vs {p2_name}")
                                else:
                                    state = match.get('state', '')
                                    if state == 'open':
                                        p1 = match.get('player1', {})
                                        p2 = match.get('player2', {})
                                        p1_name = p1.get('name', 'TBD') if isinstance(p1, dict) else 'TBD'
                                        p2_name = p2.get('name', 'TBD') if isinstance(p2, dict) else 'TBD'
                                        open_matches.append(f"⚔️ {p1_name} vs {p2_name}")
                            
                            if open_matches:
                                embed.add_field(
                                    name="🔴 Partidos en Curso",
                                    value="\n".join(open_matches[:5]),
                                    inline=False
                                )
                        
                        view = TournamentBracketView(tournament.id, self)
                        bracket_message = await panel_channel.send(embed=embed, view=view)
                        tournament.bracket_message_id = str(bracket_message.id)
                        db.commit()
                    except Exception as e:
                        print(f"Error al enviar mensaje del bracket: {e}")
                        import traceback
                        traceback.print_exc()
                
                # Confirmación
                success_embed = discord.Embed(
                    title="✅ Torneo creado exitosamente",
                    description=f"**{tournament_name}** ha sido configurado correctamente.",
                    color=discord.Color.green()
                )
                success_embed.add_field(name="🔗 Challonge", value=f"https://challonge.com/{challonge_url}", inline=False)
                if inscription_channel:
                    success_embed.add_field(name="📝 Inscripciones", value=f"Mensaje enviado a {inscription_channel.mention}", inline=True)
                if panel_channel:
                    success_embed.add_field(name="📊 Panel", value=f"Bracket enviado a {panel_channel.mention}", inline=True)
                
                await interaction.followup.send(embed=success_embed, ephemeral=True)
                
            except Exception as e:
                await interaction.followup.send(
                    f"❌ Error al crear el torneo: {str(e)}",
                    ephemeral=True
                )
                print(f"Error en create-tournament: {e}")
                import traceback
                traceback.print_exc()
    
    async def create_tournament(
        self,
        interaction: discord.Interaction,
        db,
        player: Player,
        name: str,
        url: str,
        tournament_type: str
    ):
        """Crea un nuevo torneo en Challonge"""
        
        t = get_player_translator(player) if player else get_translator('es')
        
        if not name or not url:
            await interaction.followup.send(
                t.t('tournament.errors.no_credentials'),  # Reutilizar mensaje similar
                ephemeral=True
            )
            return
        
        # Validar formato de URL según API v2.1 de Challonge
        # Solo permite: letras, números y guiones bajos (_)
        original_url = url
        # Convertir guiones a guiones bajos y eliminar caracteres no permitidos
        url = re.sub(r'[^a-zA-Z0-9_]', '_', url)
        # Eliminar guiones bajos múltiples consecutivos
        url = re.sub(r'_+', '_', url)
        # Eliminar guiones bajos al inicio y final
        url = url.strip('_')
        
        if not url:
            await interaction.followup.send(
                t.t('tournament.errors.create_error', error='URL vacía después de validación'),
                ephemeral=True
            )
            return
        
        # Si la URL cambió, informar al usuario (pero no bloquear, solo informar)
        url_changed = url != original_url
        
        # Validar que la URL sea única
        existing = db.query(Tournament).filter(Tournament.challonge_url == url).first()
        if existing:
            await interaction.followup.send(
                t.t('tournament.errors.create_error', error=f'Ya existe un torneo con la URL {url}'),
                ephemeral=True
            )
            return
        
        try:
            # Crear torneo en Challonge usando API v2.1 (JSON API format)
            data = {
                'data': {
                    'type': 'Tournaments',
                    'attributes': {
                        'name': name,
                        'url': url,
                        'tournament_type': tournament_type,
                        'registration_options': {
                            'open_signup': True
                        }
                    }
                }
            }
            response = await self.challonge_request('POST', 'tournaments.json', data=data)
            # API v2.1 devuelve formato JSON API
            tournament_data = response.get('data', {}).get('attributes', {})
            tournament_id = response.get('data', {}).get('id')
            if tournament_id:
                tournament_data['id'] = tournament_id
            
            # Guardar en base de datos
            tournament = Tournament(
                challonge_tournament_id=tournament_data['id'],
                challonge_url=url,
                name=name,
                tournament_type=tournament_type,
                status='open_signup',
                created_by=player.id
            )
            db.add(tournament)
            db.commit()
            
            embed = discord.Embed(
                title=t.t('tournament.create.title'),
                description=t.t('tournament.create.description', name=name),
                color=discord.Color.green()
            )
            
            # Si la URL fue ajustada, agregar nota
            if url_changed:
                embed.description += f"\n\n{t.t('tournament.create.url_adjusted', original=original_url, adjusted=url)}"
            
            embed.add_field(name=t.t('tournament.create.url'), value=f"https://challonge.com/{url}", inline=False)
            # Obtener nombre del tipo traducido
            type_names = {
                'single elimination': t.t('tournament.types.single_elimination'),
                'double elimination': t.t('tournament.types.double_elimination'),
                'round robin': t.t('tournament.types.round_robin'),
                'swiss': t.t('tournament.types.swiss')
            }
            embed.add_field(name=t.t('tournament.create.type'), value=type_names.get(tournament_type, tournament_type), inline=True)
            embed.add_field(name="🆔 ID", value=str(tournament_data['id']), inline=True)
            embed.add_field(name=t.t('tournament.create.status'), value="Inscripciones Abiertas", inline=True)
            embed.set_footer(text=t.t('tournament.create.footer'))
            embed.timestamp = datetime.utcnow()
            
            await interaction.followup.send(embed=embed, ephemeral=False)
            
        except Exception as e:
            error_msg = str(e)
            error_lower = error_msg.lower()
            
            # Detectar diferentes formas de decir que la URL está ocupada
            if any(phrase in error_lower for phrase in [
                "has already been taken",
                "ya está ocupado",
                "already taken",
                "is already taken",
                "already exists",
                "ya existe"
            ]):
                # Generar sugerencias de URL alternativas
                import random
                import string
                suggestions = [
                    f"{url}_2",
                    f"{url}_{random.randint(1000, 9999)}",
                    f"{url}_{datetime.now().strftime('%Y%m%d')}"
                ]
                
                embed = discord.Embed(
                    title=t.t('tournament.create.url_taken.title'),
                    description=t.t('tournament.create.url_taken.description', url=url, suggestion1=suggestions[0], suggestion2=suggestions[1], suggestion3=suggestions[2]),
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.followup.send(
                    t.t('tournament.errors.create_error', error=error_msg),
                    ephemeral=True
                )
                print(f"Error detallado al crear torneo: {error_msg}")
                import traceback
                traceback.print_exc()
    
    async def list_tournaments(self, interaction: discord.Interaction, db):
        """Lista todos los torneos creados"""
        
        player = self.get_player(db, str(interaction.user.id))
        t = get_player_translator(player) if player else get_translator('es')
        
        tournaments = db.query(Tournament).order_by(Tournament.created_at.desc()).limit(10).all()
        
        if not tournaments:
            await interaction.followup.send(
                t.t('tournament.list.none'),
                ephemeral=True
            )
            return
        
        embed = discord.Embed(
            title=t.t('tournament.list.title'),
            description="Lista de torneos creados",  # Mantener simple
            color=discord.Color.blue()
        )
        
        for tournament in tournaments:
            status_emoji = {
                'pending': '⏳',
                'open_signup': '📝',
                'underway': '⚔️',
                'awaiting_review': '⏸️',
                'complete': '✅',
                'locked': '🔒'
            }.get(tournament.status, '❓')
            
            status_text = {
                'pending': 'Pendiente',
                'open_signup': 'Inscripciones Abiertas',
                'underway': 'En Curso',
                'awaiting_review': 'En Revisión',
                'complete': 'Completado',
                'locked': 'Bloqueado'
            }.get(tournament.status, 'Desconocido')
            
            creator = db.query(Player).filter(Player.id == tournament.created_by).first()
            creator_name = creator.username if creator else "Desconocido"
            
            embed.add_field(
                name=f"{status_emoji} {tournament.name}",
                value=(
                    f"**ID:** {tournament.challonge_tournament_id}\n"
                    f"**URL:** `{tournament.challonge_url}`\n"
                    f"**Estado:** {status_text}\n"
                    f"**Creado por:** {creator_name}\n"
                    f"**Link:** https://challonge.com/{tournament.challonge_url}"
                ),
                inline=False
            )
        
        embed.set_footer(text=t.t('tournament.list.footer'))
        
        # Crear vista con botones para inscribirse
        view = TournamentListView(tournaments, self)
        await interaction.followup.send(embed=embed, view=view, ephemeral=False)
    
    async def show_participants(self, interaction: discord.Interaction, tournament_id: int):
        """Muestra los participantes de un torneo"""
        
        with get_db() as db:
            player = self.get_player(db, str(interaction.user.id))
            t = get_player_translator(player) if player else get_translator('es')
        
        if not tournament_id:
            await interaction.followup.send(
                t.t('tournament.join.errors.no_id'),
                ephemeral=True
            )
            return
        
        try:
            participants_data = await self.challonge_request('GET', f'tournaments/{tournament_id}/participants.json')
            # API v2.1 devuelve formato JSON API
            if isinstance(participants_data, dict) and 'data' in participants_data:
                participants = [item.get('attributes', {}) for item in participants_data.get('data', [])]
            elif isinstance(participants_data, list):
                participants = participants_data
            else:
                participants = participants_data.get('participants', [])
            
            if not participants:
                await interaction.followup.send(
                    t.t('tournament.join.errors.not_found'),  # Reutilizar mensaje similar
                    ephemeral=True
                )
                return
            
            embed = discord.Embed(
                title=f"👥 Participantes del Torneo #{tournament_id}",
                description=f"Total: {len(participants)} participantes",
                color=discord.Color.blue()
            )
            
            # Dividir participantes en campos (máximo 1024 caracteres por campo)
            participants_list = []
            for i, participant in enumerate(participants, 1):
                name = participant.get('name', 'Sin nombre')
                seed = participant.get('seed', 'N/A')
                final_rank = participant.get('final_rank', None)
                rank_text = f"🏆 #{final_rank}" if final_rank else "⚔️ En competencia"
                participants_list.append(f"{i}. **{name}** (Seed: {seed}) - {rank_text}")
            
            # Dividir en chunks para evitar límite de caracteres
            chunk_size = 10
            for i in range(0, len(participants_list), chunk_size):
                chunk = participants_list[i:i+chunk_size]
                field_name = f"Participantes {i+1}-{min(i+chunk_size, len(participants_list))}"
                embed.add_field(name=field_name, value="\n".join(chunk), inline=False)
            
            await interaction.followup.send(embed=embed, ephemeral=False)
            
        except Exception as e:
            await interaction.followup.send(
                t.t('errors.generic', error=str(e)),
                ephemeral=True
            )
    
    async def show_matches(self, interaction: discord.Interaction, tournament_id: int):
        """Muestra los enfrentamientos de un torneo"""
        
        with get_db() as db:
            player = self.get_player(db, str(interaction.user.id))
            t = get_player_translator(player) if player else get_translator('es')
        
        if not tournament_id:
            await interaction.followup.send(
                t.t('tournament.join.errors.no_id'),
                ephemeral=True
            )
            return
        
        try:
            matches_data = await self.challonge_request('GET', f'tournaments/{tournament_id}/matches.json')
            # API v2.1 devuelve formato JSON API
            if isinstance(matches_data, dict) and 'data' in matches_data:
                matches = [item.get('attributes', {}) for item in matches_data.get('data', [])]
            elif isinstance(matches_data, list):
                matches = matches_data
            else:
                matches = matches_data.get('matches', [])
            
            if not matches:
                await interaction.followup.send(
                    t.t('tournament.join.errors.not_found'),  # Reutilizar mensaje similar
                    ephemeral=True
                )
                return
            
            embed = discord.Embed(
                title=f"⚔️ Enfrentamientos del Torneo #{tournament_id}",
                description=f"Total: {len(matches)} partidos",
                color=discord.Color.red()
            )
            
            # Organizar partidos por estado
            pending = []
            open_matches = []
            complete = []
            
            for match in matches:
                state = match.get('state', 'unknown')
                player1 = match.get('player1', {})
                player2 = match.get('player2', {})
                p1_name = player1.get('name', 'TBD') if player1 else 'TBD'
                p2_name = player2.get('name', 'TBD') if player2 else 'TBD'
                scores = match.get('scores_csv', '')
                winner_id = match.get('winner_id')
                
                match_info = f"**{p1_name}** vs **{p2_name}**"
                if scores:
                    match_info += f" - {scores}"
                if winner_id:
                    winner_name = p1_name if winner_id == player1.get('id') else p2_name
                    match_info += f" 🏆 Ganador: {winner_name}"
                
                if state == 'complete':
                    complete.append(f"✅ {match_info}")
                elif state == 'open':
                    open_matches.append(f"⚔️ {match_info}")
                else:
                    pending.append(f"⏳ {match_info}")
            
            if open_matches:
                embed.add_field(
                    name="🔴 Partidos en Curso",
                    value="\n".join(open_matches[:10]) or "Ninguno",
                    inline=False
                )
            
            if pending:
                embed.add_field(
                    name="⏳ Partidos Pendientes",
                    value="\n".join(pending[:10]) or "Ninguno",
                    inline=False
                )
            
            if complete:
                embed.add_field(
                    name="✅ Partidos Completados",
                    value="\n".join(complete[-10:]) or "Ninguno",
                    inline=False
                )
            
            if not open_matches and not pending and not complete:
                embed.description = "No hay partidos disponibles aún."
            
            await interaction.followup.send(embed=embed, ephemeral=False)
            
        except Exception as e:
            await interaction.followup.send(
                t.t('errors.generic', error=str(e)),
                ephemeral=True
            )
    
    async def start_tournament(self, interaction: discord.Interaction, tournament_id: int):
        """Inicia un torneo en Challonge (solo admins o creador del torneo)"""
        
        with get_db() as db:
            player = self.get_player(db, str(interaction.user.id))
            t = get_player_translator(player) if player else get_translator('es')
        
        if not tournament_id:
            await interaction.followup.send(
                t.t('tournament.start.errors.no_id'),
                ephemeral=True
            )
            return
        
        # Verificar permisos: admin o creador del torneo
        with get_db() as db:
            db_tournament = db.query(Tournament).filter(
                Tournament.challonge_tournament_id == tournament_id
            ).first()
            
            if not db_tournament:
                await interaction.followup.send(
                    t.t('tournament.start.errors.not_found'),
                    ephemeral=True
                )
                return
            
            # Verificar si es admin o creador
            is_admin = interaction.user.guild_permissions.administrator
            player = self.get_player(db, str(interaction.user.id))
            is_creator = db_tournament.created_by == player.id
            
            if not is_admin and not is_creator:
                await interaction.followup.send(
                    t.t('tournament.start.errors.no_permission'),
                    ephemeral=True
                )
                return
        
        try:
            # Verificar que el torneo existe en Challonge antes de intentar iniciarlo
            try:
                await self.challonge_request('GET', f'tournaments/{tournament_id}.json')
            except Exception as e:
                error_msg = str(e)
                if "404" in error_msg or "not found" in error_msg.lower() or "does not exist" in error_msg.lower():
                    await interaction.followup.send(
                        f"❌ El torneo **#{tournament_id}** no existe en Challonge. "
                        "Puede que haya sido eliminado manualmente. "
                        "Usa `/tournament delete {tournament_id}` para eliminarlo de la base de datos.",
                        ephemeral=True
                    )
                    return
                raise
            
            # Iniciar torneo en Challonge (API v2.1)
            tournament_data = await self.challonge_request('POST', f'tournaments/{tournament_id}/start.json')
            # API v2.1 devuelve formato JSON API
            if isinstance(tournament_data, dict) and 'data' in tournament_data:
                tournament = tournament_data.get('data', {}).get('attributes', {})
                tournament['id'] = tournament_data.get('data', {}).get('id')
            else:
                tournament = tournament_data.get('tournament', tournament_data)
            
            # Actualizar en base de datos
            with get_db() as db:
                db_tournament = db.query(Tournament).filter(
                    Tournament.challonge_tournament_id == tournament_id
                ).first()
                if db_tournament:
                    db_tournament.status = 'underway'
                    db_tournament.started_at = datetime.utcnow()
                    db.commit()
            
            embed = discord.Embed(
                title=t.t('tournament.start.title'),
                description=t.t('tournament.start.description', name=tournament.get('name', 'N/A')),
                color=discord.Color.green()
            )
            embed.add_field(
                name=t.t('tournament.start.status'),
                value=t.t('tournament.start.status_value'),
                inline=True
            )
            embed.add_field(
                name=t.t('tournament.start.participants'),
                value=str(tournament.get('participants_count', 0)),
                inline=True
            )
            embed.add_field(
                name=t.t('tournament.start.next_steps'),
                value=t.t('tournament.start.next_steps_value'),
                inline=False
            )
            
            await interaction.followup.send(embed=embed, ephemeral=False)
            
        except Exception as e:
            error_msg = str(e)
            if "must have at least" in error_msg.lower():
                await interaction.followup.send(
                    t.t('tournament.start.errors.not_enough_participants'),
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    t.t('errors.generic', error=error_msg),
                    ephemeral=True
                )
    
    async def show_status(self, interaction: discord.Interaction, tournament_id: int):
        """Muestra el estado detallado de un torneo"""
        
        with get_db() as db:
            player = self.get_player(db, str(interaction.user.id))
            t = get_player_translator(player) if player else get_translator('es')
        
        if not tournament_id:
            await interaction.followup.send(
                t.t('tournament.join.errors.no_id'),
                ephemeral=True
            )
            return
        
        try:
            tournament_data = await self.challonge_request('GET', f'tournaments/{tournament_id}.json')
            # API v2.1 devuelve formato JSON API
            if isinstance(tournament_data, dict) and 'data' in tournament_data:
                tournament = tournament_data.get('data', {}).get('attributes', {})
                tournament['id'] = tournament_data.get('data', {}).get('id')
            else:
                tournament = tournament_data.get('tournament', tournament_data)
            
            participants_data = await self.challonge_request('GET', f'tournaments/{tournament_id}/participants.json')
            if isinstance(participants_data, dict) and 'data' in participants_data:
                participants = [item.get('attributes', {}) for item in participants_data.get('data', [])]
            elif isinstance(participants_data, list):
                participants = participants_data
            else:
                participants = participants_data.get('participants', [])
            
            matches_data = await self.challonge_request('GET', f'tournaments/{tournament_id}/matches.json')
            if isinstance(matches_data, dict) and 'data' in matches_data:
                matches = [item.get('attributes', {}) for item in matches_data.get('data', [])]
            elif isinstance(matches_data, list):
                matches = matches_data
            else:
                matches = matches_data.get('matches', [])
            
            status_emoji = {
                'pending': '⏳',
                'open_signup': '📝',
                'underway': '⚔️',
                'awaiting_review': '⏸️',
                'complete': '✅',
                'locked': '🔒'
            }.get(tournament.get('state', 'unknown'), '❓')
            
            status_text = {
                'pending': 'Pendiente',
                'open_signup': 'Inscripciones Abiertas',
                'underway': 'En Curso',
                'awaiting_review': 'En Revisión',
                'complete': 'Completado',
                'locked': 'Bloqueado'
            }.get(tournament.get('state', 'unknown'), 'Desconocido')
            
            embed = discord.Embed(
                title=f"{status_emoji} {tournament.get('name', 'Torneo')}",
                description=f"Estado: **{status_text}**",
                color=discord.Color.blue()
            )
            
            embed.add_field(
                name="🔗 URL",
                value=f"https://challonge.com/{tournament.get('url', 'N/A')}",
                inline=False
            )
            
            embed.add_field(
                name="👥 Participantes",
                value=str(len(participants)),
                inline=True
            )
            
            embed.add_field(
                name="⚔️ Partidos",
                value=str(len(matches)),
                inline=True
            )
            
            embed.add_field(
                name="📋 Tipo",
                value=tournament.get('tournament_type', 'N/A').replace('_', ' ').title(),
                inline=True
            )
            
            # Estadísticas de partidos
            if matches:
                complete = sum(1 for m in matches if m.get('state') == 'complete')
                open_matches = sum(1 for m in matches if m.get('state') == 'open')
                pending = sum(1 for m in matches if m.get('state') == 'pending')
                
                embed.add_field(
                    name="📊 Partidos",
                    value=(
                        f"✅ Completados: {complete}\n"
                        f"⚔️ En Curso: {open_matches}\n"
                        f"⏳ Pendientes: {pending}"
                    ),
                    inline=False
                )
            
            # Agregar botón de inscribirse si el torneo está abierto a inscripciones
            view = None
            tournament_state = tournament.get('state', 'unknown')
            if tournament_state in ['pending', 'open_signup']:
                view = TournamentJoinButtonView(tournament_id, self)
            
            await interaction.followup.send(embed=embed, view=view, ephemeral=False)
            
        except Exception as e:
            await interaction.followup.send(
                t.t('errors.generic', error=str(e)),
                ephemeral=True
            )
    
    async def show_bracket(self, interaction: discord.Interaction, tournament_id: int):
        """Muestra el link del bracket del torneo"""
        
        with get_db() as db:
            player = self.get_player(db, str(interaction.user.id))
            t = get_player_translator(player) if player else get_translator('es')
        
        if not tournament_id:
            await interaction.followup.send(
                t.t('tournament.join.errors.no_id'),
                ephemeral=True
            )
            return
        
        try:
            tournament_data = await self.challonge_request('GET', f'tournaments/{tournament_id}.json')
            # API v2.1 devuelve formato JSON API
            if isinstance(tournament_data, dict) and 'data' in tournament_data:
                tournament = tournament_data.get('data', {}).get('attributes', {})
                tournament['id'] = tournament_data.get('data', {}).get('id')
            else:
                tournament = tournament_data.get('tournament', tournament_data)
            url = tournament.get('url', '')
            
            embed = discord.Embed(
                title="🏆 Bracket del Torneo",
                description=f"**{tournament.get('name', 'Torneo')}**",
                color=discord.Color.gold()
            )
            embed.add_field(
                name="🔗 Link del Bracket",
                value=f"https://challonge.com/{url}",
                inline=False
            )
            embed.add_field(
                name="💡 Información",
                value=(
                    "Haz clic en el link para ver el bracket completo en Challonge.\n"
                    "Ahí podrás ver todos los enfrentamientos, resultados y el progreso del torneo."
                ),
                inline=False
            )
            
            await interaction.followup.send(embed=embed, ephemeral=False)
            
        except Exception as e:
            await interaction.followup.send(
                t.t('errors.generic', error=str(e)),
                ephemeral=True
            )
    
    async def join_tournament(self, interaction: discord.Interaction, tournament_id: int):
        """Inscribe al usuario actual al torneo"""
        
        with get_db() as db:
            player = self.get_player(db, str(interaction.user.id))
            t = get_player_translator(player) if player else get_translator('es')
        
        if not tournament_id:
            await interaction.followup.send(
                t.t('tournament.join.errors.no_id'),
                ephemeral=True
            )
            return
        
        try:
            # Obtener información del usuario
            username = interaction.user.display_name or interaction.user.name
            
            # Inscribir participante en Challonge usando API v2.1
            data = {
                'data': {
                    'type': 'Participants',
                    'attributes': {
                        'name': username
                    }
                }
            }
            
            response = await self.challonge_request('POST', f'tournaments/{tournament_id}/participants.json', data=data)
            
            # API v2.1 devuelve formato JSON API
            if isinstance(response, dict) and 'data' in response:
                participant_data = response.get('data', {}).get('attributes', {})
                participant_id = response.get('data', {}).get('id')
            else:
                participant_data = response.get('participant', response)
                participant_id = participant_data.get('id')
            
            embed = discord.Embed(
                title=t.t('tournament.join.title'),
                description=t.t('tournament.join.description', id=tournament_id),
                color=discord.Color.green()
            )
            embed.add_field(
                name=t.t('tournament.join.participant'),
                value=username,
                inline=True
            )
            embed.add_field(
                name=t.t('tournament.join.participant_id'),
                value=str(participant_id) if participant_id else "N/A",
                inline=True
            )
            embed.add_field(
                name=t.t('tournament.join.next_steps'),
                value=t.t('tournament.join.next_steps_value', id=tournament_id),
                inline=False
            )
            embed.set_footer(text=t.t('tournament.join.footer', username=username))
            embed.timestamp = datetime.utcnow()
            
            await interaction.followup.send(embed=embed, ephemeral=False)
            
        except Exception as e:
            error_msg = str(e)
            error_lower = error_msg.lower()
            
            # Detectar diferentes tipos de errores
            if any(phrase in error_lower for phrase in [
                "already registered",
                "ya está registrado",
                "already exists",
                "ya existe",
                "duplicate"
            ]):
                await interaction.followup.send(
                    t.t('tournament.join.errors.already_registered', id=tournament_id),
                    ephemeral=True
                )
            elif "not found" in error_lower or "no encontrado" in error_lower:
                await interaction.followup.send(
                    t.t('tournament.join.errors.not_found'),
                    ephemeral=True
                )
            elif "closed" in error_lower or "cerrado" in error_lower:
                await interaction.followup.send(
                    t.t('tournament.join.errors.closed', id=tournament_id),
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    t.t('errors.generic', error=error_msg),
                    ephemeral=True
                )
                print(f"Error detallado al inscribirse al torneo: {error_msg}")
                import traceback
                traceback.print_exc()
    
    async def delete_tournament(self, interaction: discord.Interaction, tournament_id: int):
        """Elimina un torneo (solo administradores o creador del torneo)"""
        
        with get_db() as db:
            player = self.get_player(db, str(interaction.user.id))
            t = get_player_translator(player) if player else get_translator('es')
        
        if not tournament_id:
            await interaction.followup.send(
                t.t('tournament.delete.errors.no_id'),
                ephemeral=True
            )
            return
        
        # Verificar permisos: admin o creador del torneo
        with get_db() as db:
            db_tournament = db.query(Tournament).filter(
                Tournament.challonge_tournament_id == tournament_id
            ).first()
            
            if not db_tournament:
                await interaction.followup.send(
                    t.t('tournament.delete.errors.not_found'),
                    ephemeral=True
                )
                return
            
            # Verificar si es admin o creador
            is_admin = interaction.user.guild_permissions.administrator
            player = self.get_player(db, str(interaction.user.id))
            is_creator = db_tournament.created_by == player.id
            
            if not is_admin and not is_creator:
                await interaction.followup.send(
                    t.t('tournament.delete.errors.no_permission'),
                    ephemeral=True
                )
                return
            
            tournament_name = db_tournament.name
        
        try:
            # Intentar eliminar de Challonge primero (puede que ya no exista)
            tournament_exists_in_challonge = True
            try:
                # Verificar que existe antes de eliminar
                await self.challonge_request('GET', f'tournaments/{tournament_id}.json')
            except Exception as e:
                error_msg = str(e)
                if "404" in error_msg or "not found" in error_msg.lower() or "does not exist" in error_msg.lower():
                    tournament_exists_in_challonge = False
                    logger.info(f"Torneo {tournament_id} no existe en Challonge, solo se eliminará de BD")
                else:
                    # Otro error, re-raise
                    raise
            
            # Eliminar torneo en Challonge solo si existe
            if tournament_exists_in_challonge:
                try:
                    await self.challonge_request('DELETE', f'tournaments/{tournament_id}.json')
                except Exception as e:
                    error_msg = str(e)
                    if "404" in error_msg or "not found" in error_msg.lower():
                        # Ya no existe en Challonge, continuar para eliminar de BD
                        tournament_exists_in_challonge = False
                        logger.info(f"Torneo {tournament_id} ya no existe en Challonge")
                    else:
                        raise
            
            # Eliminar de la base de datos
            with get_db() as db:
                db_tournament = db.query(Tournament).filter(
                    Tournament.challonge_tournament_id == tournament_id
                ).first()
                if db_tournament:
                    db.delete(db_tournament)
                    db.commit()
            
            if tournament_exists_in_challonge:
                embed = discord.Embed(
                    title=t.t('tournament.delete.title'),
                    description=t.t('tournament.delete.description', name=tournament_name, id=tournament_id),
                    color=discord.Color.red()
                )
            else:
                embed = discord.Embed(
                    title=t.t('tournament.delete.not_found_title'),
                    description=t.t('tournament.delete.not_found_description', name=tournament_name, id=tournament_id),
                    color=discord.Color.orange()
                )
            
            embed.set_footer(text=t.t('tournament.delete.footer', user=interaction.user.display_name))
            embed.timestamp = datetime.utcnow()
            
            await interaction.followup.send(embed=embed, ephemeral=False)
            
        except Exception as e:
            error_msg = str(e)
            error_lower = error_msg.lower()
            
            if "404" in error_msg or "not found" in error_lower or "does not exist" in error_lower:
                # Si el torneo no existe en Challonge pero sí en BD, eliminarlo de BD
                with get_db() as db:
                    db_tournament = db.query(Tournament).filter(
                        Tournament.challonge_tournament_id == tournament_id
                    ).first()
                    if db_tournament:
                        db.delete(db_tournament)
                        db.commit()
                        await interaction.followup.send(
                            t.t('tournament.delete.not_found_description', name='Torneo', id=tournament_id),
                            ephemeral=True
                        )
                    else:
                        await interaction.followup.send(
                            t.t('tournament.delete.errors.not_found'),
                            ephemeral=True
                        )
            else:
                await interaction.followup.send(
                    t.t('errors.generic', error=error_msg),
                    ephemeral=True
                )
                logger.error(f"Error detallado al eliminar torneo: {error_msg}")
                import traceback
                traceback.print_exc()
    
    @app_commands.command(name="tournament-score", description="Reporta el resultado de un partido del torneo")
    @app_commands.describe(
        myscore="Tu puntuación",
        opponentscore="Puntuación del oponente",
        opponent="Usuario oponente"
    )
    async def tournament_score(
        self,
        interaction: discord.Interaction,
        myscore: int,
        opponentscore: int,
        opponent: discord.Member
    ):
        """Reporta el resultado de un partido del torneo (detecta automáticamente el enfrentamiento)"""
        
        # Verificar que el oponente no sea el mismo usuario
        if interaction.user.id == opponent.id:
            await interaction.response.send_message(
                "❌ No puedes reportar un score contra ti mismo.",
                ephemeral=True
            )
            return
        
        await interaction.response.defer(ephemeral=False)
        
        with get_db() as db:
            player = self.get_player(db, str(interaction.user.id))
            t = get_player_translator(player) if player else get_translator('es')
            
            try:
                username = interaction.user.display_name or interaction.user.name
                opponent_username = opponent.display_name or opponent.name
                
                # Buscar torneos activos donde el usuario esté participando
                # Primero actualizar el estado de los torneos desde Challonge
                all_tournaments = db.query(Tournament).all()
                for t in all_tournaments:
                    try:
                        tournament_data = await self.challonge_request('GET', f'tournaments/{t.challonge_url}.json')
                        if isinstance(tournament_data, dict) and 'data' in tournament_data:
                            challonge_tournament = tournament_data.get('data', {}).get('attributes', {})
                        else:
                            challonge_tournament = tournament_data.get('tournament', tournament_data)
                        
                        new_state = challonge_tournament.get('state', t.status)
                        if new_state != t.status:
                            t.status = new_state
                            db.commit()
                    except Exception as e:
                        error_msg = str(e)
                        # Solo loggear como warning si no es un 404 (torneo no existe)
                        if "404" not in error_msg and "not found" not in error_msg.lower():
                            logger.warning(f"No se pudo actualizar estado del torneo {t.id}: {e}")
                        # 404 es normal si el torneo fue eliminado, no es un error crítico
                
                tournaments = db.query(Tournament).filter(
                    Tournament.status.in_(['open_signup', 'underway'])
                ).all()
                
                if not tournaments:
                    await interaction.followup.send(
                        "❌ No se encontraron torneos activos.",
                        ephemeral=True
                    )
                    return
                
                found_match = None
                found_tournament = None
                
                # Obtener IDs de Discord de los usuarios (una sola vez)
                user_discord_id = str(interaction.user.id)
                opponent_discord_id = str(opponent.id)
                
                # Buscar en cada torneo un partido abierto que coincida
                for tournament in tournaments:
                    try:
                        # Obtener mapeo desde la tabla tournament_participants (más confiable)
                        # Esto permite encontrar enfrentamientos incluso si el usuario cambió su nombre en Discord
                        tournament_participants = db.query(TournamentParticipant).filter(
                            TournamentParticipant.tournament_id == tournament.id
                        ).all()
                        
                        # Crear mapeo bidireccional:
                        # 1. Discord ID -> Nombre en Challonge (para obtener el nombre del usuario)
                        # 2. Nombre en Challonge -> Discord ID (para comparar con los partidos)
                        discord_id_to_challonge_name = {}
                        challonge_name_to_discord_id = {}
                        for tp in tournament_participants:
                            if tp.challonge_name and tp.player:
                                challonge_name_normalized = tp.challonge_name.lower().strip()
                                discord_id = tp.player.discord_id
                                discord_id_to_challonge_name[discord_id] = tp.challonge_name
                                challonge_name_to_discord_id[challonge_name_normalized] = discord_id
                        
                        # Obtener nombres en Challonge de los usuarios desde el mapeo
                        user_challonge_name = discord_id_to_challonge_name.get(user_discord_id)
                        opponent_challonge_name = discord_id_to_challonge_name.get(opponent_discord_id)
                        
                        if not user_challonge_name or not opponent_challonge_name:
                            logger.warning(f"⚠️ No se encontró mapeo para usuario {user_discord_id} o oponente {opponent_discord_id} en torneo {tournament.id}")
                            continue
                        
                        user_challonge_normalized = user_challonge_name.lower().strip()
                        opponent_challonge_normalized = opponent_challonge_name.lower().strip()
                        
                        logger.info(f"🔍 Buscando partido entre '{user_challonge_name}' y '{opponent_challonge_name}' en torneo {tournament.name}")
                        
                        # Si no hay mapeos guardados, intentar obtener desde Challonge y crear mapeos básicos
                        if not challonge_name_to_discord_id:
                            participants_data = await self.challonge_request('GET', f'tournaments/{tournament.challonge_url}/participants.json')
                            if isinstance(participants_data, dict) and 'data' in participants_data:
                                participants_list = participants_data.get('data', [])
                            else:
                                participants_list = participants_data.get('participants', [])
                            
                            for participant_item in participants_list:
                                if isinstance(participant_item, dict) and 'attributes' in participant_item:
                                    challonge_name = participant_item.get('attributes', {}).get('name', '')
                                else:
                                    challonge_name = participant_item.get('name', '')
                                
                                if not challonge_name:
                                    continue
                                
                                challonge_name_normalized = challonge_name.lower().strip()
                                challonge_name_clean = re.sub(r'[^\w]', '', challonge_name_normalized)
                                
                                possible_players = db.query(Player).filter(
                                    or_(
                                        func.lower(Player.username) == challonge_name_normalized,
                                        func.lower(Player.username).like(f'%{challonge_name_normalized}%'),
                                        func.lower(Player.username).like(f'%{challonge_name_clean}%')
                                    )
                                ).all()
                                
                                if possible_players:
                                    exact_match = next((p for p in possible_players if p.username.lower().strip() == challonge_name_normalized), None)
                                    if exact_match:
                                        challonge_name_to_discord_id[challonge_name_normalized] = exact_match.discord_id
                                    else:
                                        best_match = next((p for p in possible_players if challonge_name_normalized in p.username.lower()), None)
                                        if best_match:
                                            challonge_name_to_discord_id[challonge_name_normalized] = best_match.discord_id
                                        else:
                                            challonge_name_to_discord_id[challonge_name_normalized] = possible_players[0].discord_id
                        
                        # Obtener participantes primero para crear el mapa (usar URL, no ID)
                        # Manejar paginación para obtener todos los participantes
                        participant_id_to_name = {}
                        page = 1
                        per_page = 200
                        total_pages = 1
                        
                        while page <= total_pages:
                            participants_data = await self.challonge_request('GET', f'tournaments/{tournament.challonge_url}/participants.json?page={page}&per_page={per_page}')
                            
                            if isinstance(participants_data, dict) and 'data' in participants_data:
                                participants_list = participants_data.get('data', [])
                                # Verificar paginación en meta
                                meta = participants_data.get('meta', {})
                                if meta:
                                    pagination = meta.get('pagination', {})
                                    total_pages = pagination.get('total_pages', 1)
                            else:
                                participants_list = participants_data.get('participants', [])
                                total_pages = 1  # API v1 no tiene paginación en meta
                            
                            for participant_item in participants_list:
                                if isinstance(participant_item, dict) and 'attributes' in participant_item:
                                    attrs = participant_item.get('attributes', {})
                                    participant_id = str(participant_item.get('id', ''))
                                    participant_name = attrs.get('name', '')
                                else:
                                    participant_id = str(participant_item.get('id', ''))
                                    participant_name = participant_item.get('name', '')
                                
                                if participant_id and participant_name:
                                    participant_id_to_name[participant_id] = participant_name
                            
                            logger.info(f"📋 Página {page}/{total_pages}: {len(participants_list)} participantes obtenidos")
                            page += 1
                            
                            # Si no hay más páginas, salir
                            if page > total_pages:
                                break
                        
                        logger.info(f"📋 Mapa de participantes creado: {len(participant_id_to_name)} participantes totales")
                        
                        # Obtener partidos del torneo (usar URL, no ID)
                        # Manejar paginación para obtener todos los partidos
                        matches = []
                        page = 1
                        per_page = 200
                        total_pages = 1
                        
                        while page <= total_pages:
                            matches_data = await self.challonge_request('GET', f'tournaments/{tournament.challonge_url}/matches.json?page={page}&per_page={per_page}')
                            
                            if isinstance(matches_data, dict) and 'data' in matches_data:
                                page_matches = matches_data.get('data', [])
                                # Verificar paginación en meta
                                meta = matches_data.get('meta', {})
                                if meta:
                                    pagination = meta.get('pagination', {})
                                    total_pages = pagination.get('total_pages', 1)
                            else:
                                page_matches = matches_data.get('matches', [])
                                total_pages = 1  # API v1 no tiene paginación en meta
                            
                            matches.extend(page_matches)
                            logger.info(f"📊 Página {page}/{total_pages}: {len(page_matches)} partidos obtenidos")
                            page += 1
                            
                            # Si no hay más páginas, salir
                            if page > total_pages:
                                break
                        
                        logger.info(f"📊 Total de partidos encontrados: {len(matches)}")
                        logger.info(f"📋 Mapa de participantes: {len(participant_id_to_name)} participantes cargados")
                        if user_challonge_name in participant_id_to_name.values() or opponent_challonge_name in participant_id_to_name.values():
                            logger.info(f"✅ Los nombres buscados están en el mapa de participantes")
                        else:
                            logger.warning(f"⚠️ Los nombres '{user_challonge_name}' y '{opponent_challonge_name}' NO están en el mapa")
                        
                        # Lista para almacenar todos los partidos abiertos (para el mensaje de error)
                        open_matches_list = []
                        open_matches_count = 0
                        
                        # Buscar partido abierto que coincida con los usuarios
                        for match_item in matches:
                            if isinstance(match_item, dict) and 'attributes' in match_item:
                                attrs = match_item.get('attributes', {})
                                state = attrs.get('state', '')
                                match_id_challonge = match_item.get('id')
                            else:
                                attrs = match_item
                                state = match_item.get('state', '')
                                match_id_challonge = match_item.get('id')
                            
                            if state != 'open':
                                continue
                            
                            open_matches_count += 1
                            
                            # Obtener nombres de los jugadores desde points_by_participant (API v2.1)
                            p1_name = ''
                            p2_name = ''
                            
                            # La API v2.1 puede tener los IDs de participantes en points_by_participant
                            points_by_participant = attrs.get('points_by_participant', {})
                            
                            logger.debug(f"Partido {match_id_challonge} (estado: {state}): points_by_participant = {points_by_participant}")
                            
                            if points_by_participant:
                                # points_by_participant puede ser una lista o un diccionario
                                participant_ids = []
                                
                                if isinstance(points_by_participant, list):
                                    # Es una lista: [{'participant_id': 123, 'scores': []}, ...]
                                    for item in points_by_participant:
                                        if isinstance(item, dict):
                                            pid = item.get('participant_id')
                                            if pid:
                                                participant_ids.append(pid)
                                        else:
                                            participant_ids.append(item)
                                elif isinstance(points_by_participant, dict):
                                    # Es un diccionario: {participant_id: score, ...}
                                    participant_ids = list(points_by_participant.keys())
                                
                                logger.debug(f"  IDs encontrados en points_by_participant: {participant_ids}")
                                
                                if len(participant_ids) >= 2:
                                    participant1_id = str(participant_ids[0])
                                    participant2_id = str(participant_ids[1])
                                    
                                    logger.debug(f"  Buscando en mapa: {participant1_id} y {participant2_id}")
                                    
                                    # Obtener nombres desde el mapa de participantes
                                    if participant1_id in participant_id_to_name:
                                        p1_name = participant_id_to_name[participant1_id]
                                        logger.debug(f"  ✅ P1 encontrado: {p1_name}")
                                    else:
                                        logger.debug(f"  ⚠️ P1 ID {participant1_id} NO está en el mapa")
                                    
                                    if participant2_id in participant_id_to_name:
                                        p2_name = participant_id_to_name[participant2_id]
                                        logger.debug(f"  ✅ P2 encontrado: {p2_name}")
                                    else:
                                        logger.debug(f"  ⚠️ P2 ID {participant2_id} NO está en el mapa")
                            
                            # Si no encontramos los nombres desde points_by_participant, intentar relationships
                            if (not p1_name or not p2_name) and isinstance(match_item, dict) and 'relationships' in match_item:
                                rels = match_item.get('relationships', {})
                                
                                # Obtener participant1_id y participant2_id desde relationships
                                participant1_rel = rels.get('participant1', {})
                                participant2_rel = rels.get('participant2', {})
                                
                                participant1_id = None
                                participant2_id = None
                                
                                if isinstance(participant1_rel, dict) and 'data' in participant1_rel:
                                    participant1_id = str(participant1_rel['data'].get('id', ''))
                                elif isinstance(participant1_rel, dict) and 'id' in participant1_rel:
                                    participant1_id = str(participant1_rel['id'])
                                
                                if isinstance(participant2_rel, dict) and 'data' in participant2_rel:
                                    participant2_id = str(participant2_rel['data'].get('id', ''))
                                elif isinstance(participant2_rel, dict) and 'id' in participant2_rel:
                                    participant2_id = str(participant2_rel['id'])
                                
                                # Obtener nombres desde el mapa de participantes incluidos
                                if participant1_id and participant1_id in participant_id_to_name and not p1_name:
                                    p1_name = participant_id_to_name[participant1_id]
                                if participant2_id and participant2_id in participant_id_to_name and not p2_name:
                                    p2_name = participant_id_to_name[participant2_id]
                            
                            # Si aún no tenemos nombres, hacer una petición adicional para obtener los participantes del partido
                            if not p1_name or not p2_name:
                                try:
                                    # Obtener el partido individual con participantes incluidos (usar URL, no ID)
                                    match_detail = await self.challonge_request('GET', f'tournaments/{tournament.challonge_url}/matches/{match_id_challonge}.json?include=participants')
                                    
                                    if isinstance(match_detail, dict) and 'included' in match_detail:
                                        included = match_detail.get('included', [])
                                        for item in included:
                                            if isinstance(item, dict) and item.get('type') == 'participant':
                                                attrs_p = item.get('attributes', {})
                                                participant_id = str(item.get('id', ''))
                                                participant_name = attrs_p.get('name', '')
                                                if participant_id and participant_name:
                                                    participant_id_to_name[participant_id] = participant_name
                                        
                                        # Intentar de nuevo con points_by_participant
                                        points_by_participant = attrs.get('points_by_participant', {})
                                        if isinstance(points_by_participant, dict) and points_by_participant:
                                            participant_ids = list(points_by_participant.keys())
                                            if len(participant_ids) >= 2:
                                                participant1_id = str(participant_ids[0])
                                                participant2_id = str(participant_ids[1])
                                                if participant1_id in participant_id_to_name and not p1_name:
                                                    p1_name = participant_id_to_name[participant1_id]
                                                if participant2_id in participant_id_to_name and not p2_name:
                                                    p2_name = participant_id_to_name[participant2_id]
                                except Exception as e:
                                    logger.debug(f"Error obteniendo detalles del partido {match_id_challonge}: {e}")
                            
                            # Si aún no tenemos nombres, loggear para debug
                            if not p1_name or not p2_name:
                                logger.warning(f"⚠️ No se pudieron extraer nombres del partido {match_id_challonge}")
                                logger.warning(f"   points_by_participant: {attrs.get('points_by_participant', {})}")
                                logger.warning(f"   Participant map size: {len(participant_id_to_name)}")
                                if isinstance(match_item, dict) and 'relationships' in match_item:
                                    logger.warning(f"   Relationships keys: {list(match_item.get('relationships', {}).keys())}")
                            
                            # Normalizar nombres (lowercase, sin espacios extra)
                            p1_name_normalized = p1_name.lower().strip() if p1_name else ''
                            p2_name_normalized = p2_name.lower().strip() if p2_name else ''
                            
                            # Comparar nombres en Challonge directamente (case-insensitive)
                            p1_matches_user = p1_name_normalized == user_challonge_normalized
                            p1_matches_opponent = p1_name_normalized == opponent_challonge_normalized
                            p2_matches_user = p2_name_normalized == user_challonge_normalized
                            p2_matches_opponent = p2_name_normalized == opponent_challonge_normalized
                            
                            # Agregar a la lista de partidos abiertos (solo si tenemos nombres)
                            if p1_name and p2_name:
                                open_matches_list.append(f"{p1_name} vs {p2_name}")
                            
                            # Log detallado para todos los partidos abiertos
                            if p1_name and p2_name:
                                logger.info(f"📋 Partido abierto: {p1_name} vs {p2_name} (normalizados: '{p1_name_normalized}' vs '{p2_name_normalized}')")
                                logger.info(f"   Comparando con: '{user_challonge_normalized}' y '{opponent_challonge_normalized}'")
                                logger.info(f"   Coincidencias: p1_user={p1_matches_user}, p1_opp={p1_matches_opponent}, p2_user={p2_matches_user}, p2_opp={p2_matches_opponent}")
                            else:
                                logger.warning(f"📋 Partido abierto {match_id_challonge} pero sin nombres: p1='{p1_name}', p2='{p2_name}'")
                            
                            # Si aún no se encontró, intentar por nombre de Discord (último fallback)
                            if not (p1_matches_user or p1_matches_opponent or p2_matches_user or p2_matches_opponent):
                                user_names = [
                                    username.lower().strip() if username else '',
                                    interaction.user.name.lower().strip() if interaction.user.name else '',
                                    interaction.user.display_name.lower().strip() if interaction.user.display_name else ''
                                ]
                                opponent_names = [
                                    opponent_username.lower().strip() if opponent_username else '',
                                    opponent.name.lower().strip() if opponent.name else '',
                                    opponent.display_name.lower().strip() if opponent.display_name else ''
                                ]
                                
                                p1_matches_user = p1_name_normalized in user_names
                                p1_matches_opponent = p1_name_normalized in opponent_names
                                p2_matches_user = p2_name_normalized in user_names
                                p2_matches_opponent = p2_name_normalized in opponent_names
                            
                            if ((p1_matches_user and p2_matches_opponent) or
                                (p1_matches_opponent and p2_matches_user)):
                                found_match = {
                                    'match_id': match_id_challonge,
                                    'p1_name': p1_name,
                                    'p2_name': p2_name,
                                    'p1_is_user': p1_matches_user,
                                    'participant1_id': participant1_id if 'participant1_id' in locals() else None,
                                    'participant2_id': participant2_id if 'participant2_id' in locals() else None
                                }
                                found_tournament = tournament
                                break
                        
                        if found_match:
                            break
                    
                    except Exception as e:
                        logger.error(f"Error buscando en torneo {tournament.id}: {e}")
                        import traceback
                        traceback.print_exc()
                        continue
                
                if not found_match or not found_tournament:
                    # Obtener información de mapeo para el mensaje de error
                    user_discord_id = str(interaction.user.id)
                    opponent_discord_id = str(opponent.id)
                    
                    user_mapped_name = None
                    opponent_mapped_name = None
                    
                    if tournaments:
                        tournament = tournaments[0]
                        tournament_participants = db.query(TournamentParticipant).filter(
                            TournamentParticipant.tournament_id == tournament.id
                        ).all()
                        
                        for tp in tournament_participants:
                            if tp.player:
                                if tp.player.discord_id == user_discord_id:
                                    user_mapped_name = tp.challonge_name
                                if tp.player.discord_id == opponent_discord_id:
                                    opponent_mapped_name = tp.challonge_name
                    
                    # Mensaje más detallado para ayudar a debuggear
                    debug_info = f"\n\n💡 Información de debug:\n"
                    debug_info += f"- Usuario: {username} (name: {interaction.user.name}, display: {interaction.user.display_name}, ID: {user_discord_id})\n"
                    debug_info += f"- Oponente: {opponent_username} (name: {opponent.name}, display: {opponent.display_name}, ID: {opponent_discord_id})\n"
                    debug_info += f"- Torneos activos encontrados: {len(tournaments)}\n"
                    if user_mapped_name:
                        debug_info += f"- ✅ Nombre en Challonge del usuario: **{user_mapped_name}**\n"
                    else:
                        debug_info += f"- ⚠️ Usuario NO está mapeado en tournament_participants (ID: {user_discord_id})\n"
                    if opponent_mapped_name:
                        debug_info += f"- ✅ Nombre en Challonge del oponente: **{opponent_mapped_name}**\n"
                    else:
                        debug_info += f"- ⚠️ Oponente NO está mapeado en tournament_participants (ID: {opponent_discord_id})\n"
                    
                    # Intentar obtener información de los participantes y partidos abiertos del torneo
                    if tournaments:
                        try:
                            first_tournament = tournaments[0]
                            
                            # Obtener participantes (usar URL, no ID)
                            participants_data = await self.challonge_request('GET', f'tournaments/{first_tournament.challonge_url}/participants.json')
                            if isinstance(participants_data, dict) and 'data' in participants_data:
                                participants = participants_data.get('data', [])
                            else:
                                participants = participants_data.get('participants', [])
                            
                            participant_names = []
                            for p in participants[:10]:  # Solo primeros 10 para no hacer el mensaje muy largo
                                if isinstance(p, dict) and 'attributes' in p:
                                    p_name = p.get('attributes', {}).get('name', '')
                                else:
                                    p_name = p.get('name', '')
                                if p_name:
                                    participant_names.append(p_name)
                            
                            if participant_names:
                                debug_info += f"- Participantes en el torneo (primeros 10): {', '.join(participant_names)}\n"
                            
                            # Obtener partidos abiertos (usar URL, no ID)
                            matches_data = await self.challonge_request('GET', f'tournaments/{first_tournament.challonge_url}/matches.json')
                            if isinstance(matches_data, dict) and 'data' in matches_data:
                                matches = matches_data.get('data', [])
                            else:
                                matches = matches_data.get('matches', [])
                            
                            open_matches_found = []
                            for match_item in matches:
                                if isinstance(match_item, dict) and 'attributes' in match_item:
                                    attrs = match_item.get('attributes', {})
                                    state = attrs.get('state', '')
                                else:
                                    attrs = match_item
                                    state = match_item.get('state', '')
                                
                                if state == 'open':
                                    p1_data = attrs.get('player1', {})
                                    p2_data = attrs.get('player2', {})
                                    p1_name = p1_data.get('name', '') if isinstance(p1_data, dict) else (str(p1_data) if p1_data else '')
                                    p2_name = p2_data.get('name', '') if isinstance(p2_data, dict) else (str(p2_data) if p2_data else '')
                                    if p1_name and p2_name:
                                        open_matches_found.append(f"{p1_name} vs {p2_name}")
                            
                            if open_matches_found:
                                debug_info += f"- Partidos ABIERTOS encontrados en Challonge (primeros 10): {', '.join(open_matches_found[:10])}\n"
                            else:
                                debug_info += f"- ❌ No se encontraron partidos ABIERTOS en Challonge.\n"
                        except Exception as e:
                            debug_info += f"- ⚠️ Error obteniendo información del torneo: {str(e)}\n"
                    
                    await interaction.followup.send(
                        f"❌ No se encontró un enfrentamiento abierto entre **{username}** y **{opponent_username}** en ningún torneo activo.\n"
                        f"Verifica que ambos estén inscritos y que haya un partido pendiente entre ustedes."
                        + (debug_info if len(tournaments) > 0 else ""),
                        ephemeral=True
                    )
                    return
                
                # Verificar permisos (usuario debe ser uno de los jugadores o organizador)
                is_organizer = False
                if found_tournament.organizer_role_id:
                    try:
                        role = interaction.guild.get_role(int(found_tournament.organizer_role_id))
                        if role and role in interaction.user.roles:
                            is_organizer = True
                    except:
                        pass
                
                if not is_organizer:
                    # Verificar que el usuario sea uno de los jugadores
                    user_names = [username, interaction.user.name]
                    if found_match['p1_name'] not in user_names and found_match['p2_name'] not in user_names:
                        await interaction.followup.send(
                            "❌ Solo los participantes del partido o los organizadores pueden reportar resultados.",
                            ephemeral=True
                        )
                        return
                
                # Determinar el orden correcto del score
                if found_match['p1_is_user']:
                    # Usuario es player1, oponente es player2
                    score1 = myscore
                    score2 = opponentscore
                    final_p1_name = found_match['p1_name']
                    final_p2_name = found_match['p2_name']
                else:
                    # Usuario es player2, oponente es player1
                    score1 = opponentscore
                    score2 = myscore
                    final_p1_name = found_match['p1_name']
                    final_p2_name = found_match['p2_name']
                
                # NO actualizar Challonge ni otorgar ELO todavía
                # Primero mostrar vista de confirmación (igual que /score)
                # El ELO y Challonge se actualizarán cuando el oponente confirme
                
                # Obtener jugadores desde la BD
                user_player = db.query(Player).filter(Player.discord_id == user_discord_id).first()
                opponent_player = db.query(Player).filter(Player.discord_id == opponent_discord_id).first()
                
                if not user_player:
                    user_player = Player(
                        discord_id=user_discord_id,
                        username=interaction.user.name
                    )
                    db.add(user_player)
                    db.commit()
                    db.refresh(user_player)
                
                if not opponent_player:
                    opponent_player = Player(
                        discord_id=opponent_discord_id,
                        username=opponent.name
                    )
                    db.add(opponent_player)
                    db.commit()
                    db.refresh(opponent_player)
                
                # Crear embed de confirmación (igual que /score)
                from utils.embeds import create_score_report_embed
                embed = create_score_report_embed(interaction.user, opponent, myscore, opponentscore, user_player)
                
                # Añadir información del torneo
                embed.add_field(
                    name="🏆 Torneo",
                    value=found_tournament.name,
                    inline=False
                )
                
                # Crear vista de confirmación
                view = ConfirmTournamentMatchView(
                    tournament_id=found_tournament.id,
                    tournament_url=found_tournament.challonge_url,
                    match_id_challonge=found_match["match_id"],
                    user_player_id=user_player.id,
                    opponent_player_id=opponent_player.id,
                    user_discord_id=user_discord_id,
                    opponent_discord_id=opponent_discord_id,
                    score1=score1,
                    score2=score2,
                    p1_is_user=found_match['p1_is_user'],
                    p1_name=final_p1_name,
                    p2_name=final_p2_name,
                    participant1_id=found_match.get('participant1_id'),
                    participant2_id=found_match.get('participant2_id'),
                    bot=self.bot,
                    cog=self
                )
                
                # Enviar mensaje de confirmación
                mensaje_notificacion = f"{interaction.user.mention} ha reportado un score de torneo con tu nombre {opponent.mention}."
                await interaction.followup.send(content=mensaje_notificacion, embed=embed, view=view, ephemeral=False)
                return
                
                # Verificar si el torneo terminó y procesar top 5 (usar URL, no ID)
                try:
                    tournament_data = await self.challonge_request('GET', f'tournaments/{found_tournament.challonge_url}.json')
                    if isinstance(tournament_data, dict) and 'data' in tournament_data:
                        challonge_tournament = tournament_data.get('data', {}).get('attributes', {})
                    else:
                        challonge_tournament = tournament_data.get('tournament', tournament_data)
                    
                    tournament_state = challonge_tournament.get('state', '')
                    
                    # Si el torneo está completo y aún no se ha procesado
                    if tournament_state == 'complete' and found_tournament.status != 'complete':
                        # Actualizar estado en BD
                        with get_db() as db:
                            db_tournament = db.query(Tournament).filter(Tournament.id == found_tournament.id).first()
                            if db_tournament:
                                db_tournament.status = 'complete'
                                db_tournament.completed_at = datetime.utcnow()
                                db.commit()
                                db.refresh(db_tournament)
                                found_tournament = db_tournament
                        
                        # Procesar top 5 y otorgar ELO
                        top_5 = await self.finish_tournament(found_tournament)
                        
                        if top_5:
                            # Crear embed con top 5
                            embed = discord.Embed(
                                title=f"🏆 Torneo Finalizado - {found_tournament.name}",
                                description="**Top 5 Finalistas**\n\n*ELO otorgado y sumado al ELO 1v1 individual*",
                                color=discord.Color.gold()
                            )
                            
                            medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
                            for i, player_info in enumerate(top_5):
                                medal = medals[i] if i < len(medals) else f"{i+1}."
                                rank_text = f"{medal} **{player_info['name']}**"
                                if player_info['new_elo'] is not None:
                                    rank_text += f"\n   ➕ {player_info['elo_gained']} ELO (Total: {player_info['new_elo']:.0f})"
                                else:
                                    rank_text += f"\n   ➕ {player_info['elo_gained']} ELO (⚠️ Jugador no encontrado en BD)"
                                embed.add_field(
                                    name=f"Posición #{player_info['rank']}",
                                    value=rank_text,
                                    inline=False
                                )
                            
                            embed.add_field(
                                name="🔗 Bracket Completo",
                                value=f"https://challonge.com/{found_tournament.challonge_url}",
                                inline=False
                            )
                            embed.set_footer(text="ELO otorgado según posición final en el torneo")
                            
                            # Enviar al panel_channel si existe
                            if found_tournament.panel_channel_id:
                                try:
                                    panel_channel = self.bot.get_channel(int(found_tournament.panel_channel_id))
                                    if panel_channel:
                                        await panel_channel.send(embed=embed)
                                except Exception as e:
                                    print(f"Error al enviar top 5 al panel: {e}")
                            
                            # También enviar al result_channel si existe
                            if found_tournament.result_channel_id:
                                try:
                                    result_channel = self.bot.get_channel(int(found_tournament.result_channel_id))
                                    if result_channel:
                                        await result_channel.send(embed=embed)
                                except Exception as e:
                                    print(f"Error al enviar top 5 a resultados: {e}")
                except Exception as e:
                    print(f"Error verificando estado del torneo: {e}")
                
                # Actualizar el bracket en panel_channel si existe
                if found_tournament.bracket_message_id and found_tournament.panel_channel_id:
                    try:
                        await self.update_bracket_message(found_tournament)
                    except Exception as e:
                        print(f"Error al actualizar bracket: {e}")
                
                # Enviar mensaje al canal de resultados si está configurado
                if found_tournament.result_channel_id:
                    try:
                        result_channel = self.bot.get_channel(int(found_tournament.result_channel_id))
                        if result_channel:
                            embed = discord.Embed(
                                title="⚔️ Resultado Reportado",
                                description=f"**Partido:** {final_p1_name} vs {final_p2_name}\n**Resultado:** {score1} - {score2}",
                                color=discord.Color.green()
                            )
                            embed.add_field(name="Torneo", value=found_tournament.name, inline=True)
                            embed.add_field(name="Reportado por", value=username, inline=True)
                            await result_channel.send(embed=embed)
                    except Exception as e:
                        print(f"Error al enviar mensaje a canal de resultados: {e}")
                
                # Crear embed visual igual que /score usando create_match_result_embed
                from utils.embeds import create_match_result_embed
                from config import STADIUM_IMAGE_URL, STADIUM_IMAGE_URL_FALLBACK
                import discord
                
                # Obtener usuarios de Discord para el embed
                try:
                    user1 = await interaction.client.fetch_user(int(player1.discord_id))
                except:
                    user1 = None
                try:
                    user2 = await interaction.client.fetch_user(int(player2.discord_id))
                except:
                    user2 = None
                
                # Crear un objeto Match temporal para usar con create_match_result_embed
                # (no lo guardamos en BD, solo lo usamos para el embed)
                from database.models import Match
                from datetime import datetime
                temp_match = Match(
                    id=0,  # ID temporal
                    player1_id=player1.id,
                    player2_id=player2.id,
                    score1=player1_score,
                    score2=player2_score,
                    status='confirmed',  # Ya está confirmado automáticamente
                    confirmed_by=player1.id,  # El que reportó
                    confirmed_at=datetime.utcnow(),
                    elo_change1=elo_change1,
                    elo_change2=elo_change2,
                    xp_gained1=xp1,
                    xp_gained2=xp2
                )
                
                # Obtener rangos ANTES de actualizar ELO (para detectar subida de rango)
                player1_rank_before = get_rank_from_elo(player1_elo_before)
                player2_rank_before = get_rank_from_elo(player2_elo_before)
                
                # Obtener rangos DESPUÉS de actualizar ELO
                if use_elo_1v1:
                    player1_elo_after = player1.elo_1v1 if player1.elo_1v1 is not None else 0
                    player2_elo_after = player2.elo_1v1 if player2.elo_1v1 is not None else 0
                else:
                    player1_elo_after = player1.elo
                    player2_elo_after = player2.elo
                
                player1_rank_after = get_rank_from_elo(player1_elo_after)
                player2_rank_after = get_rank_from_elo(player2_elo_after)
                
                # Actualizar roles de Discord según rango (igual que /score)
                if interaction.guild:
                    try:
                        member1 = interaction.guild.get_member(int(player1.discord_id))
                        if member1:
                            await update_member_rank_roles(member1, player1_rank_after, interaction.guild)
                        member2 = interaction.guild.get_member(int(player2.discord_id))
                        if member2:
                            await update_member_rank_roles(member2, player2_rank_after, interaction.guild)
                    except Exception as e:
                        logger.warning(f"Error actualizando roles de rango (torneo): {e}")
                
                # Detectar si subieron de rango
                player1_rank_up = player1_rank_before != player1_rank_after
                player2_rank_up = player2_rank_before != player2_rank_after
                
                # Determinar quién ganó
                player1_won_result = None if is_draw else (player1_score > player2_score)
                
                # URL de imagen de estadio
                stadium_image_url = STADIUM_IMAGE_URL
                
                # Obtener idioma del jugador que reportó
                player_language = getattr(player1, 'language', None) or 'es'
                
                # Generar imagen del estadio con marcador superpuesto (igual que /score)
                image_file = None
                if stadium_image_url:
                    try:
                        from utils.image_generator import generate_stadium_image_with_score
                        player1_avatar_url = user1.avatar.url if user1 and user1.avatar else None
                        player2_avatar_url = user2.avatar.url if user2 and user2.avatar else None
                        player1_name = user1.display_name if user1 else player1.username
                        player2_name = user2.display_name if user2 else player2.username
                        
                        import asyncio
                        loop = asyncio.get_event_loop()
                        image_urls_to_try = [STADIUM_IMAGE_URL]
                        if STADIUM_IMAGE_URL_FALLBACK:
                            image_urls_to_try.append(STADIUM_IMAGE_URL_FALLBACK)
                        
                        for candidate_url in image_urls_to_try:
                            try:
                                image_bytes = await asyncio.wait_for(
                                    loop.run_in_executor(
                                        None,
                                        generate_stadium_image_with_score,
                                        candidate_url,
                                        player1_score,
                                        player2_score,
                                        player1_avatar_url,
                                        player2_avatar_url,
                                        player1_name,
                                        player2_name,
                                        elo_change1,
                                        elo_change2,
                                        xp1,
                                        xp2,
                                        player1_elo_after,
                                        player2_elo_after
                                    ),
                                    timeout=10.0
                                )
                                if image_bytes:
                                    image_file = discord.File(image_bytes, filename="match_result.png")
                                    stadium_image_url = "attachment://match_result.png"
                                    break
                            except Exception as e:
                                logger.warning(f"Error generando imagen con {candidate_url}: {e}")
                                continue
                    except Exception as e:
                        logger.warning(f"Error al generar imagen: {e}")
                        stadium_image_url = STADIUM_IMAGE_URL  # Usar URL directa como fallback
                
                # Crear embed usando la misma función que /score
                embed = create_match_result_embed(
                    temp_match, player1, player2, user1, user2, is_draw, 
                    interaction.user, stadium_image_url, use_elo_1v1, 
                    language=player_language,
                    player1_rank_before=player1_rank_before, 
                    player2_rank_before=player2_rank_before,
                    player1_rank_after=player1_rank_after, 
                    player2_rank_after=player2_rank_after,
                    player1_rank_up=player1_rank_up, 
                    player2_rank_up=player2_rank_up,
                    player1_won=player1_won_result,
                    winner_streak=0,  # No hay racha en torneos
                    winner_streak_bonus=0.0,
                    elo_bonus_active=False,  # No hay bonus en torneos
                    elo_bonus_win_mult=1.0,
                    elo_bonus_loss_mult=1.0
                )
                
                # Añadir información del torneo al embed
                embed.add_field(
                    name="🏆 Torneo",
                    value=found_tournament.name,
                    inline=True
                )
                embed.add_field(
                    name="📝 Reportado por",
                    value=username,
                    inline=True
                )
                
                # Enviar mensaje con embed e imagen
                if image_file:
                    await interaction.followup.send(embed=embed, file=image_file)
                else:
                    await interaction.followup.send(embed=embed)
                
            except Exception as e:
                await interaction.followup.send(
                    f"❌ Error al reportar resultado: {str(e)}",
                    ephemeral=True
                )
                print(f"Error en tournament-score: {e}")
                import traceback
                traceback.print_exc()
    
    @app_commands.command(name="tournament-finish", description="Finaliza un torneo, otorga ELO al top 5 y muestra resultados (solo administradores)")
    @app_commands.describe(
        tournament_id="ID del torneo en la base de datos (opcional, si no se especifica busca el más reciente)"
    )
    async def tournament_finish(
        self,
        interaction: discord.Interaction,
        tournament_id: int = None
    ):
        """Finaliza un torneo, procesa el top 5 y otorga ELO"""
        
        # Verificar permisos
        is_admin = (
            interaction.user.guild_permissions.administrator or
            interaction.user.id in ADMIN_IDS
        )
        
        if not is_admin:
            await interaction.response.send_message(
                "❌ Solo los administradores pueden usar este comando.",
                ephemeral=True
            )
            return
        
        await interaction.response.defer(ephemeral=False)
        
        with get_db() as db:
            player = self.get_player(db, str(interaction.user.id))
            t = get_player_translator(player) if player else get_translator('es')
            
            try:
                if tournament_id:
                    tournament = db.query(Tournament).filter(Tournament.id == tournament_id).first()
                else:
                    # Buscar el torneo más reciente que esté en curso
                    tournament = db.query(Tournament).filter(
                        Tournament.status.in_(['underway', 'open_signup'])
                    ).order_by(Tournament.created_at.desc()).first()
                
                if not tournament:
                    await interaction.followup.send(
                        "❌ No se encontró ningún torneo activo.",
                        ephemeral=True
                    )
                    return
                
                # Verificar estado en Challonge (usar URL, no ID)
                tournament_data = await self.challonge_request('GET', f'tournaments/{tournament.challonge_url}.json')
                if isinstance(tournament_data, dict) and 'data' in tournament_data:
                    challonge_tournament = tournament_data.get('data', {}).get('attributes', {})
                else:
                    challonge_tournament = tournament_data.get('tournament', tournament_data)
                
                tournament_state = challonge_tournament.get('state', '')
                
                if tournament_state != 'complete':
                    await interaction.followup.send(
                        f"⚠️ El torneo **{tournament.name}** aún no está completo.\n"
                        f"Estado actual: {tournament_state}\n"
                        f"Espera a que termine el torneo o finalízalo manualmente en Challonge.",
                        ephemeral=True
                    )
                    return
                
                # Procesar top 5 y otorgar ELO
                top_5 = await self.finish_tournament(tournament)
                
                if not top_5:
                    await interaction.followup.send(
                        "❌ No se pudo obtener el top 5 del torneo. Verifica que el torneo esté completo en Challonge.",
                        ephemeral=True
                    )
                    return
                
                # Actualizar estado en BD
                tournament.status = 'complete'
                tournament.completed_at = datetime.utcnow()
                db.commit()
                
                # Crear embed con top 5
                embed = discord.Embed(
                    title=f"🏆 Torneo Finalizado - {tournament.name}",
                    description="**Top 5 Finalistas**\n\n*ELO otorgado y sumado al ELO 1v1 individual*",
                    color=discord.Color.gold()
                )
                
                medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
                for i, player_info in enumerate(top_5):
                    medal = medals[i] if i < len(medals) else f"{i+1}."
                    rank_text = f"{medal} **{player_info['name']}**"
                    if player_info['new_elo'] is not None:
                        rank_text += f"\n   ➕ {player_info['elo_gained']} ELO (Total: {player_info['new_elo']:.0f})"
                    else:
                        rank_text += f"\n   ➕ {player_info['elo_gained']} ELO (⚠️ Jugador no encontrado en BD)"
                    embed.add_field(
                        name=f"Posición #{player_info['rank']}",
                        value=rank_text,
                        inline=False
                    )
                
                embed.add_field(
                    name="🔗 Bracket Completo",
                    value=f"https://challonge.com/{tournament.challonge_url}",
                    inline=False
                )
                embed.set_footer(text="ELO otorgado según posición final en el torneo")
                
                await interaction.followup.send(embed=embed)
                
                # También enviar al panel_channel y result_channel si existen
                if tournament.panel_channel_id:
                    try:
                        panel_channel = self.bot.get_channel(int(tournament.panel_channel_id))
                        if panel_channel:
                            await panel_channel.send(embed=embed)
                    except Exception as e:
                        print(f"Error al enviar top 5 al panel: {e}")
                
                if tournament.result_channel_id:
                    try:
                        result_channel = self.bot.get_channel(int(tournament.result_channel_id))
                        if result_channel:
                            await result_channel.send(embed=embed)
                    except Exception as e:
                        print(f"Error al enviar top 5 a resultados: {e}")
                
            except Exception as e:
                await interaction.followup.send(
                    f"❌ Error al finalizar torneo: {str(e)}",
                    ephemeral=True
                )
                print(f"Error en tournament-finish: {e}")
                import traceback
                traceback.print_exc()


class TournamentJoinButtonView(discord.ui.View):
    """Vista con botón para inscribirse a un torneo específico"""
    
    def __init__(self, tournament_id: int, cog):
        super().__init__(timeout=86400)  # 24 horas de timeout
        self.tournament_id = tournament_id
        self.cog = cog
    
    @discord.ui.button(label="✅ Inscribirse", style=discord.ButtonStyle.success, emoji="📝", custom_id=None)
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Maneja el clic en el botón de inscribirse"""
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Obtener información del usuario
            username = interaction.user.display_name or interaction.user.name
            
            # Inscribir participante en Challonge usando API v2.1
            data = {
                'data': {
                    'type': 'Participants',
                    'attributes': {
                        'name': username
                    }
                }
            }
            
            response = await self.cog.challonge_request('POST', f'tournaments/{self.tournament_id}/participants.json', data=data)
            
            # API v2.1 devuelve formato JSON API
            if isinstance(response, dict) and 'data' in response:
                participant_data = response.get('data', {}).get('attributes', {})
                participant_id = response.get('data', {}).get('id')
            else:
                participant_data = response.get('participant', response)
                participant_id = participant_data.get('id')
            
            with get_db() as db:
                player = self.cog.get_player(db, str(interaction.user.id))
                t = get_player_translator(player) if player else get_translator('es')
            
            embed = discord.Embed(
                title=t.t('tournament.join.title'),
                description=t.t('tournament.join.description', id=self.tournament_id),
                color=discord.Color.green()
            )
            embed.add_field(
                name=t.t('tournament.join.participant'),
                value=username,
                inline=True
            )
            embed.add_field(
                name=t.t('tournament.join.participant_id'),
                value=str(participant_id) if participant_id else "N/A",
                inline=True
            )
            embed.add_field(
                name=t.t('tournament.join.next_steps'),
                value=t.t('tournament.join.next_steps_value', id=self.tournament_id),
                inline=False
            )
            embed.set_footer(text=t.t('tournament.join.footer', username=username))
            embed.timestamp = datetime.utcnow()
            
            await interaction.followup.send(embed=embed, ephemeral=False)
            
            # Deshabilitar el botón después de inscribirse
            button.disabled = True
            button.label = t.t('tournament.join.button_already')
            button.style = discord.ButtonStyle.secondary
            
            # Actualizar el mensaje original
            try:
                await interaction.message.edit(view=self)
            except:
                pass  # Si no se puede editar, no pasa nada
            
        except Exception as e:
            error_msg = str(e)
            error_lower = error_msg.lower()
            
            with get_db() as db:
                player = self.cog.get_player(db, str(interaction.user.id))
                t = get_player_translator(player) if player else get_translator('es')
            
            # Detectar diferentes tipos de errores
            if any(phrase in error_lower for phrase in [
                "already registered",
                "ya está registrado",
                "already exists",
                "ya existe",
                "duplicate"
            ]):
                await interaction.followup.send(
                    t.t('tournament.join.errors.already_registered', id=self.tournament_id),
                    ephemeral=True
                )
                # Deshabilitar el botón
                button.disabled = True
                button.label = t.t('tournament.join.button_already')
                button.style = discord.ButtonStyle.secondary
                try:
                    await interaction.message.edit(view=self)
                except:
                    pass
            elif "not found" in error_lower or "no encontrado" in error_lower:
                await interaction.followup.send(
                    t.t('tournament.join.errors.not_found'),
                    ephemeral=True
                )
            elif "closed" in error_lower or "cerrado" in error_lower:
                await interaction.followup.send(
                    t.t('tournament.join.errors.closed', id=self.tournament_id),
                    ephemeral=True
                )
                # Deshabilitar el botón
                button.disabled = True
                button.label = t.t('tournament.join.button_closed')
                button.style = discord.ButtonStyle.secondary
                try:
                    await interaction.message.edit(view=self)
                except:
                    pass
            else:
                await interaction.followup.send(
                    t.t('errors.generic', error=error_msg),
                    ephemeral=True
                )
                logger.error(f"Error detallado al inscribirse al torneo: {error_msg}")
                import traceback
                traceback.print_exc()


class TournamentListView(discord.ui.View):
    """Vista con botones para inscribirse a múltiples torneos"""
    
    def __init__(self, tournaments, cog):
        super().__init__(timeout=86400)  # 24 horas de timeout
        self.cog = cog
        
        # Agregar botones solo para torneos abiertos a inscripciones (máximo 5 botones por Discord)
        open_tournaments = [t for t in tournaments if t.status in ['pending', 'open_signup']][:5]
        
        for tournament in open_tournaments:
            button = TournamentJoinButton(
                tournament.challonge_url,  # Usar URL en lugar de ID para mayor compatibilidad
                tournament.name,
                cog
            )
            self.add_item(button)


class TournamentJoinButton(discord.ui.Button):
    """Botón individual para inscribirse a un torneo específico"""
    
    def __init__(self, tournament_url: str, tournament_name: str, cog):
        # Limitar el nombre del torneo para el label (máximo 80 caracteres)
        label = f"Inscribirse: {tournament_name[:50]}..." if len(tournament_name) > 50 else f"Inscribirse: {tournament_name}"
        super().__init__(
            label=label,
            style=discord.ButtonStyle.success,
            emoji="📝",
            custom_id=f"tournament_join_{tournament_url}"
        )
        self.tournament_url = tournament_url  # Usar URL en lugar de ID
        self.tournament_name = tournament_name
        self.cog = cog
    
    async def callback(self, interaction: discord.Interaction):
        """Maneja el clic en el botón"""
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Obtener información del usuario
            username = interaction.user.display_name or interaction.user.name
            
            # Inscribir participante en Challonge usando API v2.1 (usar URL, no ID)
            data = {
                'data': {
                    'type': 'Participants',
                    'attributes': {
                        'name': username
                    }
                }
            }
            
            response = await self.cog.challonge_request('POST', f'tournaments/{self.tournament_url}/participants.json', data=data)
            
            # API v2.1 devuelve formato JSON API
            if isinstance(response, dict) and 'data' in response:
                participant_data = response.get('data', {}).get('attributes', {})
                participant_id = response.get('data', {}).get('id')
            else:
                participant_data = response.get('participant', response)
                participant_id = participant_data.get('id')
            
            with get_db() as db:
                player = self.cog.get_player(db, str(interaction.user.id))
                t = get_player_translator(player) if player else get_translator('es')
            
            embed = discord.Embed(
                title=t.t('tournament.join.title'),
                description=t.t('tournament.join.description', id=self.tournament_id),
                color=discord.Color.green()
            )
            embed.add_field(
                name=t.t('tournament.join.participant'),
                value=username,
                inline=True
            )
            embed.add_field(
                name=t.t('tournament.join.participant_id'),
                value=str(participant_id) if participant_id else "N/A",
                inline=True
            )
            embed.add_field(
                name=t.t('tournament.join.next_steps'),
                value=t.t('tournament.join.next_steps_value', id=self.tournament_id),
                inline=False
            )
            embed.set_footer(text=t.t('tournament.join.footer', username=username))
            embed.timestamp = datetime.utcnow()
            
            await interaction.followup.send(embed=embed, ephemeral=False)
            
            # Deshabilitar el botón después de inscribirse
            self.disabled = True
            self.label = f"{t.t('tournament.join.button_already')}: {self.tournament_name[:40]}..."
            self.style = discord.ButtonStyle.secondary
            
            # Actualizar el mensaje original
            try:
                await interaction.message.edit(view=self.view)
            except:
                pass  # Si no se puede editar, no pasa nada
            
        except Exception as e:
            with get_db() as db:
                player = self.cog.get_player(db, str(interaction.user.id))
                t = get_player_translator(player) if player else get_translator('es')
            
            error_msg = str(e)
            error_lower = error_msg.lower()
            
            # Detectar diferentes tipos de errores
            if any(phrase in error_lower for phrase in [
                "already registered",
                "ya está registrado",
                "already exists",
                "ya existe",
                "duplicate"
            ]):
                await interaction.followup.send(
                    t.t('tournament.join.errors.already_registered', id=self.tournament_id),
                    ephemeral=True
                )
                # Deshabilitar el botón
                self.disabled = True
                self.label = f"{t.t('tournament.join.button_already')}: {self.tournament_name[:40]}..."
                self.style = discord.ButtonStyle.secondary
                try:
                    await interaction.message.edit(view=self.view)
                except:
                    pass
            elif "not found" in error_lower or "no encontrado" in error_lower:
                await interaction.followup.send(
                    t.t('tournament.join.errors.not_found'),
                    ephemeral=True
                )
            elif "closed" in error_lower or "cerrado" in error_lower:
                await interaction.followup.send(
                    t.t('tournament.join.errors.closed', id=self.tournament_id),
                    ephemeral=True
                )
                # Deshabilitar el botón
                self.disabled = True
                self.label = f"{t.t('tournament.join.button_closed')}: {self.tournament_name[:40]}..."
                self.style = discord.ButtonStyle.secondary
                try:
                    await interaction.message.edit(view=self.view)
                except:
                    pass
            else:
                await interaction.followup.send(
                    t.t('errors.generic', error=error_msg),
                    ephemeral=True
                )
                logger.error(f"Error detallado al inscribirse al torneo: {error_msg}")
                import traceback
                traceback.print_exc()

class TournamentInscriptionView(discord.ui.View):
    """Vista con botones para inscribirse/cancelar inscripción en un torneo"""
    
    def __init__(self, tournament_db_id: int, cog):
        super().__init__(timeout=None)  # Sin timeout para que los botones funcionen indefinidamente
        self.tournament_db_id = tournament_db_id
        self.cog = cog
    
    @discord.ui.button(label="✅ Inscribirse", style=discord.ButtonStyle.success, emoji="📝")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Maneja el clic en el botón de inscribirse"""
        await interaction.response.defer(ephemeral=True)
        
        with get_db() as db:
            tournament = db.query(Tournament).filter(Tournament.id == self.tournament_db_id).first()
            if not tournament:
                await interaction.followup.send("❌ Torneo no encontrado.", ephemeral=True)
                return
            
            player = self.cog.get_player(db, str(interaction.user.id))
            t = get_player_translator(player) if player else get_translator('es')
            
            try:
                username = interaction.user.display_name or interaction.user.name
                
                # Inscribir participante en Challonge
                data = {
                    'data': {
                        'type': 'Participants',
                        'attributes': {
                            'name': username
                        }
                    }
                }
                
                response = await self.cog.challonge_request('POST', f'tournaments/{tournament.challonge_url}/participants.json', data=data)
                
                if isinstance(response, dict) and 'data' in response:
                    participant_data = response.get('data', {}).get('attributes', {})
                    participant_id = response.get('data', {}).get('id')
                else:
                    participant_data = response.get('participant', response)
                    participant_id = participant_data.get('id')
                
                # Guardar el mapeo Discord ID -> Nombre en Challonge
                if player:
                    # Verificar si ya existe el mapeo
                    existing = db.query(TournamentParticipant).filter(
                        TournamentParticipant.tournament_id == tournament.id,
                        TournamentParticipant.player_id == player.id
                    ).first()
                    
                    if existing:
                        # Actualizar el nombre en Challonge si cambió
                        existing.challonge_name = username
                        existing.challonge_participant_id = str(participant_id) if participant_id else None
                    else:
                        # Crear nuevo mapeo
                        new_participant = TournamentParticipant(
                            tournament_id=tournament.id,
                            player_id=player.id,
                            challonge_name=username,
                            challonge_participant_id=str(participant_id) if participant_id else None
                        )
                        db.add(new_participant)
                    
                    db.commit()
                
                # Asignar rol si está configurado
                if tournament.participant_role_id:
                    try:
                        role = interaction.guild.get_role(int(tournament.participant_role_id))
                        if role:
                            await interaction.user.add_roles(role, reason=f"Inscripción al torneo {tournament.name}")
                    except Exception as e:
                        print(f"Error al asignar rol: {e}")
                
                embed = discord.Embed(
                    title="✅ Inscripción exitosa",
                    description=f"Te has inscrito correctamente al torneo **{tournament.name}**",
                    color=discord.Color.green()
                )
                embed.add_field(name="Participante", value=username, inline=True)
                embed.add_field(name="ID", value=str(participant_id) if participant_id else "N/A", inline=True)
                embed.set_footer(text=f"Bracket: https://challonge.com/{tournament.challonge_url}")
                
                await interaction.followup.send(embed=embed, ephemeral=True)
                
            except Exception as e:
                error_msg = str(e)
                error_lower = error_msg.lower()
                
                if any(phrase in error_lower for phrase in [
                    "already registered", "ya está registrado", "already exists", "ya existe", "duplicate"
                ]):
                    await interaction.followup.send(
                        f"⚠️ Ya estás inscrito en el torneo **{tournament.name}**",
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        f"❌ Error al inscribirse: {error_msg}",
                        ephemeral=True
                    )
                    print(f"Error al inscribirse al torneo: {error_msg}")
                    import traceback
                    traceback.print_exc()
    
    @discord.ui.button(label="❌ Cancelar Inscripción", style=discord.ButtonStyle.danger, emoji="🚫")
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Maneja el clic en el botón de cancelar inscripción"""
        await interaction.response.defer(ephemeral=True)
        
        with get_db() as db:
            tournament = db.query(Tournament).filter(Tournament.id == self.tournament_db_id).first()
            if not tournament:
                await interaction.followup.send("❌ Torneo no encontrado.", ephemeral=True)
                return
            
            player = self.cog.get_player(db, str(interaction.user.id))
            t = get_player_translator(player) if player else get_translator('es')
            
            try:
                # Obtener lista de participantes (usar URL, no ID)
                participants_data = await self.cog.challonge_request('GET', f'tournaments/{tournament.challonge_url}/participants.json')
                
                if isinstance(participants_data, dict) and 'data' in participants_data:
                    participants = participants_data.get('data', [])
                elif isinstance(participants_data, list):
                    participants = participants_data
                else:
                    participants = participants_data.get('participants', [])
                
                # Buscar el participante por nombre
                username = interaction.user.display_name or interaction.user.name
                participant_id = None
                
                for p in participants:
                    if isinstance(p, dict):
                        if 'attributes' in p:
                            p_name = p.get('attributes', {}).get('name', '')
                            p_id = p.get('id')
                        else:
                            p_name = p.get('name', '')
                            p_id = p.get('id')
                    else:
                        p_name = str(p.get('name', '')) if hasattr(p, 'get') else str(p)
                        p_id = None
                    
                    if p_name == username:
                        participant_id = p_id
                        break
                
                if not participant_id:
                    await interaction.followup.send(
                        f"⚠️ No estás inscrito en el torneo **{tournament.name}**",
                        ephemeral=True
                    )
                    return
                
                # Eliminar participante de Challonge (usar URL, no ID)
                await self.cog.challonge_request('DELETE', f'tournaments/{tournament.challonge_url}/participants/{participant_id}.json')
                
                # Quitar rol si está configurado
                if tournament.participant_role_id:
                    try:
                        role = interaction.guild.get_role(int(tournament.participant_role_id))
                        if role:
                            await interaction.user.remove_roles(role, reason=f"Cancelación de inscripción al torneo {tournament.name}")
                    except Exception as e:
                        print(f"Error al quitar rol: {e}")
                
                embed = discord.Embed(
                    title="✅ Inscripción cancelada",
                    description=f"Has cancelado tu inscripción al torneo **{tournament.name}**",
                    color=discord.Color.orange()
                )
                
                await interaction.followup.send(embed=embed, ephemeral=True)
                
            except Exception as e:
                error_msg = str(e)
                await interaction.followup.send(
                    f"❌ Error al cancelar inscripción: {error_msg}",
                    ephemeral=True
                )
                print(f"Error al cancelar inscripción: {error_msg}")
                import traceback
                traceback.print_exc()


class TournamentBracketView(discord.ui.View):
    """Vista para mostrar el bracket del torneo"""
    
    def __init__(self, tournament_db_id: int, cog):
        super().__init__(timeout=None)
        self.tournament_db_id = tournament_db_id
        self.cog = cog
    
    @discord.ui.button(label="🔄 Actualizar Bracket", style=discord.ButtonStyle.primary)
    async def refresh_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Actualiza el mensaje del bracket"""
        await interaction.response.defer(ephemeral=True)
        
        with get_db() as db:
            tournament = db.query(Tournament).filter(Tournament.id == self.tournament_db_id).first()
            if not tournament:
                await interaction.followup.send("❌ Torneo no encontrado.", ephemeral=True)
                return
            
            try:
                # Obtener información actualizada del torneo (usar URL, no ID)
                tournament_data = await self.cog.challonge_request('GET', f'tournaments/{tournament.challonge_url}.json')
                if isinstance(tournament_data, dict) and 'data' in tournament_data:
                    challonge_tournament = tournament_data.get('data', {}).get('attributes', {})
                else:
                    challonge_tournament = tournament_data.get('tournament', tournament_data)
                
                # Obtener participantes con paginación
                participants = []
                page = 1
                per_page = 200
                total_pages = 1
                
                while page <= total_pages:
                    participants_data = await self.cog.challonge_request('GET', f'tournaments/{tournament.challonge_url}/participants.json?page={page}&per_page={per_page}')
                    
                    if isinstance(participants_data, dict) and 'data' in participants_data:
                        page_participants = participants_data.get('data', [])
                        meta = participants_data.get('meta', {})
                        if meta:
                            pagination = meta.get('pagination', {})
                            total_pages = pagination.get('total_pages', 1)
                    else:
                        page_participants = participants_data.get('participants', [])
                        total_pages = 1
                    
                    participants.extend(page_participants)
                    page += 1
                    if page > total_pages:
                        break
                
                # Obtener partidos con paginación
                matches = []
                page = 1
                total_pages = 1
                
                while page <= total_pages:
                    matches_data = await self.cog.challonge_request('GET', f'tournaments/{tournament.challonge_url}/matches.json?page={page}&per_page={per_page}')
                    
                    if isinstance(matches_data, dict) and 'data' in matches_data:
                        page_matches = matches_data.get('data', [])
                        meta = matches_data.get('meta', {})
                        if meta:
                            pagination = meta.get('pagination', {})
                            total_pages = pagination.get('total_pages', 1)
                    else:
                        page_matches = matches_data.get('matches', [])
                        total_pages = 1
                    
                    matches.extend(page_matches)
                    page += 1
                    if page > total_pages:
                        break
                
                embed = discord.Embed(
                    title=f"📊 Bracket - {tournament.name}",
                    description=f"**Juego:** {tournament.game or 'N/A'}\n**Estado:** {challonge_tournament.get('state', 'Pendiente')}",
                    color=discord.Color.blue()
                )
                embed.add_field(name="👥 Participantes", value=str(len(participants)), inline=True)
                embed.add_field(name="⚔️ Partidos", value=str(len(matches)), inline=True)
                embed.add_field(
                    name="🔗 Ver Bracket Completo",
                    value=f"https://challonge.com/{tournament.challonge_url}",
                    inline=False
                )
                
                # Actualizar el mensaje original si existe
                if tournament.bracket_message_id and tournament.panel_channel_id:
                    try:
                        channel = self.cog.bot.get_channel(int(tournament.panel_channel_id))
                        if channel:
                            message = await channel.fetch_message(int(tournament.bracket_message_id))
                            await message.edit(embed=embed)
                    except Exception as e:
                        print(f"Error al actualizar mensaje del bracket: {e}")
                
                await interaction.followup.send("✅ Bracket actualizado.", ephemeral=True)
                
            except Exception as e:
                await interaction.followup.send(
                    f"❌ Error al actualizar bracket: {str(e)}",
                    ephemeral=True
                )


class ConfirmTournamentMatchView(discord.ui.View):
    def __init__(self, tournament_id: int, tournament_url: str, match_id_challonge: str, 
                 user_player_id: int, opponent_player_id: int, user_discord_id: str, 
                 opponent_discord_id: str, score1: int, score2: int, p1_is_user: bool,
                 p1_name: str, p2_name: str, participant1_id: str = None, participant2_id: str = None,
                 bot=None, cog=None):
        super().__init__(timeout=86400)  # 24 horas
        self.tournament_id = tournament_id
        self.tournament_url = tournament_url
        self.match_id_challonge = match_id_challonge
        self.user_player_id = user_player_id
        self.opponent_player_id = opponent_player_id
        self.user_discord_id = user_discord_id
        self.opponent_discord_id = opponent_discord_id
        self.score1 = score1
        self.score2 = score2
        self.p1_is_user = p1_is_user
        self.participant1_id = participant1_id
        self.participant2_id = participant2_id
        self.p1_name = p1_name
        self.p2_name = p2_name
        self.bot = bot
        self.cog = cog
    
    @discord.ui.button(label="Sí", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm_match(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        
        with get_db() as db:
            player = db.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
            if not player:
                await interaction.followup.send(
                    "❌ No tienes un perfil creado. Usa `/register` primero.",
                    ephemeral=True
                )
                return
            
            # Verificar permisos (solo el oponente o admin puede confirmar)
            from config import ADMIN_IDS
            is_admin = (
                interaction.user.guild_permissions.administrator or
                interaction.user.id in ADMIN_IDS
            )
            
            if player.id != self.opponent_player_id and not is_admin:
                await interaction.followup.send(
                    "❌ Solo el oponente puede confirmar este resultado.",
                    ephemeral=True
                )
                return
            
            # Obtener jugadores
            player1_obj = db.query(Player).filter(Player.id == self.user_player_id).first()
            player2_obj = db.query(Player).filter(Player.id == self.opponent_player_id).first()
            
            if not player1_obj or not player2_obj:
                await interaction.followup.send(
                    "❌ Error: No se encontraron los jugadores.",
                    ephemeral=True
                )
                return
            
            # Determinar quién es player1 y player2 según el orden del partido
            if self.p1_is_user:
                player1 = player1_obj
                player2 = player2_obj
                player1_score = self.score1
                player2_score = self.score2
            else:
                player1 = player2_obj
                player2 = player1_obj
                player1_score = self.score1
                player2_score = self.score2
            
            # Obtener ELO ANTES de cualquier cambio
            use_elo_1v1 = True
            if use_elo_1v1:
                player1_elo_before = player1.elo_1v1 if player1.elo_1v1 is not None else 0
                player2_elo_before = player2.elo_1v1 if player2.elo_1v1 is not None else 0
            else:
                player1_elo_before = player1.elo
                player2_elo_before = player2.elo
            
            # Verificar si es empate
            is_draw = player1_score == player2_score
            
            # Calcular ELO y XP
            from utils.elo import calculate_elo, get_rank_from_elo
            from config import XP_WIN, XP_LOSS, XP_BONUS_MULTIPLIER
            
            if is_draw:
                elo_change1 = 0
                elo_change2 = 0
                xp1 = 0
                xp2 = 0
                player1.draws += 1
                player2.draws += 1
                player1.win_streak = 0
                player2.win_streak = 0
            else:
                player1_won = player1_score > player2_score
                player1_streak_before = player1.win_streak
                player2_streak_before = player2.win_streak
                elo_change1, elo_change2, _, _ = calculate_elo(
                    player1_elo_before, player2_elo_before, player1_won,
                    player1_streak_before, player2_streak_before
                )
                
                # Actualizar ELO
                if use_elo_1v1:
                    if player1.elo_1v1 is None:
                        player1.elo_1v1 = 0
                    if player2.elo_1v1 is None:
                        player2.elo_1v1 = 0
                    player1.elo_1v1 += elo_change1
                    player2.elo_1v1 += elo_change2
                    if player1.elo_1v1 < 0:
                        player1.elo_1v1 = 0
                    if player2.elo_1v1 < 0:
                        player2.elo_1v1 = 0
                    player1.elo += elo_change1
                    player2.elo += elo_change2
                    if player1.elo < 0:
                        player1.elo = 0
                    if player2.elo < 0:
                        player2.elo = 0
                    
                    # Actualizar ELO de equipos
                    for player_obj in [player1, player2]:
                        for membership in player_obj.team_memberships:
                            if membership.team:
                                membership.team.update_team_elo()
                
                # Calcular XP
                if player1_won:
                    xp1 = XP_WIN
                    xp2 = XP_LOSS
                    if player2_elo_before > player1_elo_before:
                        xp1 = int(xp1 * XP_BONUS_MULTIPLIER)
                else:
                    xp1 = XP_LOSS
                    xp2 = XP_WIN
                    if player1_elo_before > player2_elo_before:
                        xp2 = int(xp2 * XP_BONUS_MULTIPLIER)
                
                player1.xp += xp1
                player2.xp += xp2
                
                if player1_won:
                    player1.wins += 1
                    player2.losses += 1
                    player1.win_streak += 1
                    if player1.win_streak > player1.best_win_streak:
                        player1.best_win_streak = player1.win_streak
                    player2.win_streak = 0
                else:
                    player2.wins += 1
                    player1.losses += 1
                    player2.win_streak += 1
                    if player2.win_streak > player2.best_win_streak:
                        player2.best_win_streak = player2.win_streak
                    player1.win_streak = 0
            
            db.commit()
            
            # AHORA actualizar Challonge
            scores_csv = f"{self.score1}-{self.score2}"
            match_id_str = str(self.match_id_challonge)
            
            # Obtener participant IDs si no los tenemos
            participant1_id = self.participant1_id
            participant2_id = self.participant2_id
            
            if not participant1_id or not participant2_id:
                # Intentar obtenerlos del match
                try:
                    match_detail = await self.cog.challonge_request('GET', f'tournaments/{self.tournament_url}/matches/{match_id_str}.json')
                    if isinstance(match_detail, dict) and 'data' in match_detail:
                        attrs = match_detail.get('data', {}).get('attributes', {})
                        points_by_participant = attrs.get('points_by_participant', [])
                        if isinstance(points_by_participant, list) and len(points_by_participant) >= 2:
                            participant1_id = str(points_by_participant[0].get('participant_id', ''))
                            participant2_id = str(points_by_participant[1].get('participant_id', ''))
                        elif isinstance(points_by_participant, dict):
                            participant_ids = list(points_by_participant.keys())
                            if len(participant_ids) >= 2:
                                participant1_id = str(participant_ids[0])
                                participant2_id = str(participant_ids[1])
                    else:
                        # API v1 format
                        match_data = match_detail.get('match', match_detail)
                        if isinstance(match_data, dict):
                            participant1_id = str(match_data.get('player1_id', ''))
                            participant2_id = str(match_data.get('player2_id', ''))
                except Exception as e:
                    logger.warning(f"⚠️ No se pudieron obtener participant IDs del match: {e}")
            
            # Determinar qué score va a cada participant
            # Si p1_is_user es True, entonces participant1 es el usuario (score1)
            if self.p1_is_user:
                user_participant_id = participant1_id
                opponent_participant_id = participant2_id
                user_score = self.score1
                opponent_score = self.score2
            else:
                user_participant_id = participant2_id
                opponent_participant_id = participant1_id
                user_score = self.score2
                opponent_score = self.score1
            
            # Determinar quién ganó para establecer advancing
            user_won = user_score > opponent_score
            opponent_won = opponent_score > user_score
            
            # Formato según API v2.1 o v1
            # Para API v2.1: usar formato con match array y score_set
            # Para API v1: usar scores_csv
            if participant1_id and participant2_id:
                # API v2.1 format según documentación: https://challonge.apidog.io/update-match-23619747e0
                # IMPORTANTE: incluir 'advancing' para que Challonge avance al ganador
                data = {
                    'data': {
                        'type': 'Match',
                        'attributes': {
                            'match': [
                                {
                                    'participant_id': user_participant_id,
                                    'score_set': str(user_score),
                                    'advancing': user_won  # True si ganó, False si perdió
                                },
                                {
                                    'participant_id': opponent_participant_id,
                                    'score_set': str(opponent_score),
                                    'advancing': opponent_won  # True si ganó, False si perdió
                                }
                            ]
                        }
                    }
                }
            else:
                # Fallback a formato v1 con scores_csv
                data = {
                    'data': {
                        'type': 'Matches',
                        'id': match_id_str,
                        'attributes': {
                            'scores_csv': scores_csv
                        }
                    }
                }
            
            try:
                logger.info(f"🔄 Intentando actualizar Challonge: tournament={self.tournament_url}, match={match_id_str}, score={scores_csv}")
                result = await self.cog.challonge_request('PUT', f'tournaments/{self.tournament_url}/matches/{match_id_str}.json', data=data)
                logger.info(f"✅ Score actualizado en Challonge: {scores_csv} para match {match_id_str}")
                logger.info(f"📋 Respuesta de Challonge: {result}")
                
                # Verificar que se actualizó correctamente consultando el match
                try:
                    verify_match = await self.cog.challonge_request('GET', f'tournaments/{self.tournament_url}/matches/{match_id_str}.json')
                    if isinstance(verify_match, dict) and 'data' in verify_match:
                        match_attrs = verify_match.get('data', {}).get('attributes', {})
                        verified_score = match_attrs.get('scores_csv', 'N/A')
                    else:
                        match_data = verify_match.get('match', verify_match)
                        verified_score = match_data.get('scores_csv', 'N/A') if isinstance(match_data, dict) else 'N/A'
                    
                    logger.info(f"🔍 Verificación: Score en Challonge después de actualizar: {verified_score}")
                    if verified_score == scores_csv:
                        logger.info(f"✅ VERIFICADO: El score se actualizó correctamente en Challonge")
                    elif verified_score != 'N/A':
                        # Solo advertir si el score es diferente pero no es N/A (puede ser formato diferente)
                        # Challonge puede devolver el score en formato diferente (ej: "2-1" vs "2 - 1")
                        scores_match = verified_score.replace(' ', '').replace('-', '') == scores_csv.replace(' ', '').replace('-', '')
                        if not scores_match:
                            logger.warning(f"⚠️ ADVERTENCIA: Score esperado '{scores_csv}', pero Challonge muestra '{verified_score}'")
                        else:
                            logger.info(f"✅ Score verificado (formato diferente pero equivalente): '{verified_score}'")
                    # Si es 'N/A', puede ser que Challonge aún no haya procesado el update, no es crítico
                except Exception as verify_error:
                    logger.warning(f"⚠️ No se pudo verificar el score actualizado: {verify_error}")
                    
            except Exception as e:
                logger.error(f"❌ Error al actualizar score en Challonge: {e}")
                import traceback
                logger.error(f"📋 Traceback completo:\n{traceback.format_exc()}")
                await interaction.followup.send(
                    f"⚠️ El resultado se confirmó pero hubo un error al actualizar Challonge: {str(e)}\n"
                    f"Por favor, actualiza el resultado manualmente en el bracket.",
                    ephemeral=True
                )
            
            # Obtener torneo para actualizar bracket
            tournament = db.query(Tournament).filter(Tournament.id == self.tournament_id).first()
            if tournament:
                # Actualizar bracket si existe
                if tournament.bracket_message_id and tournament.panel_channel_id:
                    try:
                        await self.cog.update_bracket_message(tournament)
                    except Exception as e:
                        logger.warning(f"Error al actualizar bracket: {e}")
                
                # Verificar si el torneo terminó
                try:
                    tournament_data = await self.cog.challonge_request('GET', f'tournaments/{tournament.challonge_url}.json')
                    if isinstance(tournament_data, dict) and 'data' in tournament_data:
                        challonge_tournament = tournament_data.get('data', {}).get('attributes', {})
                    else:
                        challonge_tournament = tournament_data.get('tournament', tournament_data)
                    
                    tournament_state = challonge_tournament.get('state', '')
                    
                    if tournament_state == 'complete' and tournament.status != 'complete':
                        tournament.status = 'complete'
                        tournament.completed_at = datetime.utcnow()
                        db.commit()
                        
                        # Procesar top 5
                        top_5 = await self.cog.finish_tournament(tournament)
                        if top_5:
                            embed = discord.Embed(
                                title=f"🏆 Torneo Finalizado - {tournament.name}",
                                description="**Top 5 Finalistas**\n\n*ELO otorgado y sumado al ELO 1v1 individual*",
                                color=discord.Color.gold()
                            )
                            
                            medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
                            for i, player_info in enumerate(top_5):
                                medal = medals[i] if i < len(medals) else f"{i+1}."
                                rank_text = f"{medal} **{player_info['name']}**"
                                if player_info['new_elo'] is not None:
                                    rank_text += f"\n   ➕ {player_info['elo_gained']} ELO (Total: {player_info['new_elo']:.0f})"
                                else:
                                    rank_text += f"\n   ➕ {player_info['elo_gained']} ELO (⚠️ Jugador no encontrado en BD)"
                                embed.add_field(
                                    name=f"Posición #{player_info['rank']}",
                                    value=rank_text,
                                    inline=False
                                )
                            
                            embed.add_field(
                                name="🔗 Bracket Completo",
                                value=f"https://challonge.com/{tournament.challonge_url}",
                                inline=False
                            )
                            embed.set_footer(text="ELO otorgado según posición final en el torneo")
                            
                            if tournament.panel_channel_id:
                                try:
                                    panel_channel = self.bot.get_channel(int(tournament.panel_channel_id))
                                    if panel_channel:
                                        await panel_channel.send(embed=embed)
                                except:
                                    pass
                            
                            if tournament.result_channel_id:
                                try:
                                    result_channel = self.bot.get_channel(int(tournament.result_channel_id))
                                    if result_channel:
                                        await result_channel.send(embed=embed)
                                except:
                                    pass
                except Exception as e:
                    logger.warning(f"Error verificando estado del torneo: {e}")
            
            # Crear embed visual igual que /score
            from utils.embeds import create_match_result_embed
            from config import STADIUM_IMAGE_URL, STADIUM_IMAGE_URL_FALLBACK
            
            try:
                user1 = await self.bot.fetch_user(int(player1.discord_id))
            except:
                user1 = None
            try:
                user2 = await self.bot.fetch_user(int(player2.discord_id))
            except:
                user2 = None
            
            # Crear objeto Match temporal
            from database.models import Match
            temp_match = Match(
                id=0,
                player1_id=player1.id,
                player2_id=player2.id,
                score1=player1_score,
                score2=player2_score,
                status='confirmed',
                confirmed_by=player.id,
                confirmed_at=datetime.utcnow(),
                elo_change1=elo_change1,
                elo_change2=elo_change2,
                xp_gained1=xp1,
                xp_gained2=xp2
            )
            
            # Obtener rangos
            player1_rank_before = get_rank_from_elo(player1_elo_before)
            player2_rank_before = get_rank_from_elo(player2_elo_before)
            
            if use_elo_1v1:
                player1_elo_after = player1.elo_1v1 if player1.elo_1v1 is not None else 0
                player2_elo_after = player2.elo_1v1 if player2.elo_1v1 is not None else 0
            else:
                player1_elo_after = player1.elo
                player2_elo_after = player2.elo
            
            player1_rank_after = get_rank_from_elo(player1_elo_after)
            player2_rank_after = get_rank_from_elo(player2_elo_after)
            
            # Actualizar roles de Discord según rango (igual que /score)
            if interaction.guild:
                try:
                    member1 = interaction.guild.get_member(int(player1.discord_id))
                    if member1:
                        await update_member_rank_roles(member1, player1_rank_after, interaction.guild)
                    member2 = interaction.guild.get_member(int(player2.discord_id))
                    if member2:
                        await update_member_rank_roles(member2, player2_rank_after, interaction.guild)
                except Exception as e:
                    logger.warning(f"Error actualizando roles de rango (torneo): {e}")
            
            player1_rank_up = player1_rank_before != player1_rank_after
            player2_rank_up = player2_rank_before != player2_rank_after
            player1_won_result = None if is_draw else (player1_score > player2_score)
            
            stadium_image_url = STADIUM_IMAGE_URL
            player_language = getattr(player1, 'language', None) or 'es'
            
            # Generar imagen
            image_file = None
            if stadium_image_url:
                try:
                    from utils.image_generator import generate_stadium_image_with_score
                    player1_avatar_url = user1.avatar.url if user1 and user1.avatar else None
                    player2_avatar_url = user2.avatar.url if user2 and user2.avatar else None
                    player1_name = user1.display_name if user1 else player1.username
                    player2_name = user2.display_name if user2 else player2.username
                    
                    import asyncio
                    loop = asyncio.get_event_loop()
                    image_urls_to_try = [STADIUM_IMAGE_URL]
                    if STADIUM_IMAGE_URL_FALLBACK:
                        image_urls_to_try.append(STADIUM_IMAGE_URL_FALLBACK)
                    
                    for candidate_url in image_urls_to_try:
                        try:
                            image_bytes = await asyncio.wait_for(
                                loop.run_in_executor(
                                    None,
                                    generate_stadium_image_with_score,
                                    candidate_url,
                                    player1_score,
                                    player2_score,
                                    player1_avatar_url,
                                    player2_avatar_url,
                                    player1_name,
                                    player2_name,
                                    elo_change1,
                                    elo_change2,
                                    xp1,
                                    xp2,
                                    player1_elo_after,
                                    player2_elo_after
                                ),
                                timeout=10.0
                            )
                            if image_bytes:
                                image_file = discord.File(image_bytes, filename="match_result.png")
                                stadium_image_url = "attachment://match_result.png"
                                break
                        except Exception as e:
                            logger.warning(f"Error generando imagen: {e}")
                            continue
                except Exception as e:
                    logger.warning(f"Error al generar imagen: {e}")
                    stadium_image_url = STADIUM_IMAGE_URL
            
            # Crear embed final
            embed = create_match_result_embed(
                temp_match, player1, player2, user1, user2, is_draw,
                interaction.user, stadium_image_url, use_elo_1v1,
                language=player_language,
                player1_rank_before=player1_rank_before,
                player2_rank_before=player2_rank_before,
                player1_rank_after=player1_rank_after,
                player2_rank_after=player2_rank_after,
                player1_rank_up=player1_rank_up,
                player2_rank_up=player2_rank_up,
                player1_won=player1_won_result,
                winner_streak=0,
                winner_streak_bonus=0.0,
                elo_bonus_active=False,
                elo_bonus_win_mult=1.0,
                elo_bonus_loss_mult=1.0
            )
            
            # Añadir información del torneo
            if tournament:
                embed.add_field(
                    name="🏆 Torneo",
                    value=tournament.name,
                    inline=True
                )
            
            # Borrar mensaje original
            try:
                if interaction.message:
                    await interaction.message.delete()
            except:
                pass
            
            # Enviar embed final
            if image_file:
                await interaction.followup.send(embed=embed, file=image_file)
            else:
                await interaction.followup.send(embed=embed)
            
            self.stop()
    
    @discord.ui.button(label="No", style=discord.ButtonStyle.danger, emoji="❌")
    async def dispute_match(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        with get_db() as db:
            player = db.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
            if not player:
                await interaction.followup.send(
                    "❌ No tienes un perfil creado.",
                    ephemeral=True
                )
                return
            
            # Solo el oponente puede disputar
            if player.id != self.opponent_player_id:
                await interaction.followup.send(
                    "❌ Solo el oponente puede disputar este resultado.",
                    ephemeral=True
                )
                return
            
            # Borrar mensaje original
            try:
                if interaction.message:
                    await interaction.message.delete()
            except:
                pass
            
            await interaction.followup.send(
                "❌ Has disputado este resultado. Contacta con un administrador si hay un problema.",
                ephemeral=True
            )
            self.stop()

async def setup(bot):
    await bot.add_cog(TournamentsCog(bot))

