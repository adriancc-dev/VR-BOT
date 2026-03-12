import discord
from discord import app_commands
from discord.ext import commands
from database.database import get_db
from database.models import Player, Match, TeamMember, Team
from utils.embeds import create_profile_embed
from utils.i18n import get_player_translator, get_translator
from sqlalchemy import and_, or_

class ProfileCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    def calculate_goal_averages(self, db, player_id):
        """Calcula el promedio de goles marcados y encajados por partida"""
        # obtener todas las partidas confirmadas donde el jugador participo
        matches = db.query(Match).filter(
            and_(
                or_(Match.player1_id == player_id, Match.player2_id == player_id),
                Match.status == 'confirmed',
                Match.score1.isnot(None),
                Match.score2.isnot(None)
            )
        ).all()
        
        if not matches:
            return 0.0, 0.0
        
        total_goals_scored = 0
        total_goals_conceded = 0
        
        for match in matches:
            if match.player1_id == player_id:
                total_goals_scored += match.score1 or 0
                total_goals_conceded += match.score2 or 0
            elif match.player2_id == player_id:
                total_goals_scored += match.score2 or 0
                total_goals_conceded += match.score1 or 0
        
        avg_scored = total_goals_scored / len(matches) if matches else 0.0
        avg_conceded = total_goals_conceded / len(matches) if matches else 0.0
        
        return avg_scored, avg_conceded
    
    @app_commands.command(name="profile", description="Muestra tu propio perfil")
    async def profile(self, interaction: discord.Interaction):
        # responder inmediatamente para evitar timeout
        await interaction.response.defer()
        
        target_user = interaction.user
        
        with get_db() as db:
            player = db.query(Player).filter(Player.discord_id == str(target_user.id)).first()
            
            if not player:
                # crear perfil automaticamente
                player = Player(
                    discord_id=str(interaction.user.id),
                    username=interaction.user.name
                )
                db.add(player)
                db.commit()
                db.refresh(player)
            
            # obtener equipo del jugador
            team = None
            membership = db.query(TeamMember).filter(TeamMember.player_id == player.id).first()
            if membership:
                team = db.query(Team).filter(Team.id == membership.team_id).first()
            
            # calcular promedios de goles
            avg_scored, avg_conceded = self.calculate_goal_averages(db, player.id)
            
            embed = create_profile_embed(player, target_user, team, avg_scored, avg_conceded)
            await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(ProfileCog(bot))

