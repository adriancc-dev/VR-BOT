import discord
from discord import app_commands
from discord.ext import commands
from database.database import get_db
from database.models import Player, Team
from utils.elo import get_rank_from_elo, get_rank_emoji
from utils.i18n import translate_rank
from utils.i18n import get_player_translator, get_translator

class LeaderboardCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="leaderboard", description="Muestra el ranking de jugadores o equipos")
    @app_commands.describe(
        category="Categoría: jugadores o equipos",
        type="Tipo de ranking",
        page="Página del ranking (1-10)"
    )
    @app_commands.choices(category=[
        app_commands.Choice(name="Jugadores", value="players"),
        app_commands.Choice(name="Equipos", value="teams"),
    ])
    @app_commands.choices(type=[
        app_commands.Choice(name="ELO", value="elo"),
        app_commands.Choice(name="XP", value="xp"),
        app_commands.Choice(name="Victorias", value="wins"),
        app_commands.Choice(name="Win Rate", value="winrate"),
        app_commands.Choice(name="Prestigio", value="prestige"),
    ])
    async def leaderboard(self, interaction: discord.Interaction, category: str = "players", type: str = "elo", page: int = 1):
        
        # responder inmediatamente para evitar timeout
        await interaction.response.defer()
        
        if page < 1:
            page = 1
        
        with get_db() as db:
            
            # obtener jugador para determinar idioma
            player = db.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
            t = get_player_translator(player) if player else get_translator('es')
            
            # leaderboard para jugadores
            if category == "players":
                if type == "elo":
                    players = db.query(Player).order_by(Player.elo.desc()).limit(10).offset((page-1)*10).all()
                    title = t.t('leaderboard.elo')
                elif type == "xp":
                    players = db.query(Player).order_by(Player.xp.desc()).limit(10).offset((page-1)*10).all()
                    title = t.t('leaderboard.xp')
                elif type == "wins":
                    players = db.query(Player).order_by(Player.wins.desc()).limit(10).offset((page-1)*10).all()
                    title = t.t('leaderboard.wins')
                elif type == "winrate":
                    all_players = db.query(Player).all()
                    players_with_games = [p for p in all_players if p.wins + p.losses > 0]
                    players = sorted(players_with_games, key=lambda p: p.win_rate(), reverse=True)[(page-1)*10:page*10]
                    title = t.t('leaderboard.winrate')
                else:  # prestige
                    all_players = db.query(Player).all()

                    # filtrar jugadores con al menos una partida
                    players_with_matches = [p for p in all_players if (p.wins + p.losses + p.draws) > 0]
                    players = sorted(players_with_matches, key=lambda p: p.prestige(), reverse=True)[(page-1)*10:page*10]
                    title = t.t('leaderboard.prestige')
                
                if not players:
                    await interaction.followup.send(t.t('leaderboard.no_players'), ephemeral=True)
                    return
                
                embed = discord.Embed(title=title, color=discord.Color.gold())
                description = ""
                
                for i, player_obj in enumerate(players, start=(page-1)*10+1):
                    position_emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
                    rank_base = get_rank_from_elo(player_obj.elo)

                    # traducir rango segun el idioma del usuario
                    rank = translate_rank(rank_base, t.language)
                    rank_emoji = get_rank_emoji(rank_base)  # emoji usa el rango base
                    
                    if type == "elo":
                        value = t.t('leaderboard.value_elo', rank=rank, elo=player_obj.elo)
                    elif type == "xp":
                        value = t.t('leaderboard.value_xp', level=player_obj.level, xp=player_obj.xp)
                    elif type == "wins":
                        value = t.t('leaderboard.value_wins', wins=player_obj.wins)
                    elif type == "winrate":
                        value = t.t('leaderboard.value_winrate', winrate=player_obj.win_rate(), wins=player_obj.wins, losses=player_obj.losses)
                    else:  # prestige
                        prestige_value = player_obj.prestige()
                        value = t.t('leaderboard.value_prestige', prestige=prestige_value)
                    
                    # mostrar emoji del rango antes del nombre del jugador
                    description += f"{position_emoji} {rank_emoji} <@{player_obj.discord_id}> - {value}\n"
                
                embed.description = description
                embed.set_footer(text=t.t('leaderboard.page', page=page))
                await interaction.followup.send(embed=embed)
            
            # leaderboard de equipos
            else:  # category == "teams"
                # para equipo: solo se clasifica mediante elo
                if type != "elo":
                    await interaction.followup.send(t.t('leaderboard.teams.only_elo'), ephemeral=True)
                    return
                
                teams = db.query(Team).order_by(Team.elo.desc()).limit(10).offset((page-1)*10).all()
                title = t.t('leaderboard.teams.elo')
                
                if not teams:
                    await interaction.followup.send(t.t('leaderboard.teams.no_teams'), ephemeral=True)
                    return
                
                embed = discord.Embed(title=title, color=discord.Color.blue())
                description = ""
                
                for i, team in enumerate(teams, start=(page-1)*10+1):
                    position_emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
                    rank_base = get_rank_from_elo(team.elo)

                    # traducir rango segun el idioma del usuario
                    rank = translate_rank(rank_base, t.language)
                    rank_emoji = get_rank_emoji(rank_base)  # Emoji usa el rango base
                    
                    # mostrar tag si existe
                    team_display = f"**{team.name}**"
                    if team.tag:
                        team_display = f"**[{team.tag}] {team.name}**"
                    
                    value = t.t('leaderboard.teams.value_elo', rank=rank, elo=team.elo)
                    
                    # mostrar numero de miembros
                    member_count = team.member_count()
                    members_text = t.t('leaderboard.teams.members', count=member_count)
                    
                    description += f"{position_emoji} {rank_emoji} {team_display} - {value} ({members_text})\n"
                
                embed.description = description
                embed.set_footer(text=t.t('leaderboard.page', page=page))
                await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(LeaderboardCog(bot))

