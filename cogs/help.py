import discord
from discord import app_commands
from discord.ext import commands
from database.database import get_db
from database.models import Player
from utils.i18n import get_player_translator, get_translator

class HelpCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="help", description="Muestra todos los comandos disponibles del bot")
    async def help_command(self, interaction: discord.Interaction):
        """Muestra todos los comandos disponibles organizados por categorías"""
        
        with get_db() as db:
            player = db.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
            t = get_player_translator(player) if player else get_translator('es')
        
        embed = discord.Embed(
            title=t.t('help.title'),
            description=t.t('help.description'),
            color=discord.Color.blue()
        )
        
        # perfil y estadisticas
        embed.add_field(
            name=t.t('help.profile_stats.name'),
            value=t.t('help.profile_stats.value'),
            inline=False
        )
        
        # partidas
        embed.add_field(
            name=t.t('help.matches.name'),
            value=t.t('help.matches.value'),
            inline=False
        )
        
        # equipos
        embed.add_field(
            name=t.t('help.teams.name'),
            value=t.t('help.teams.value'),
            inline=False
        )
        
        # torneos
        embed.add_field(
            name=t.t('help.tournaments.name'),
            value=t.t('help.tournaments.value'),
            inline=False
        )
        
        # administracion
        embed.add_field(
            name=t.t('help.admin.name'),
            value=t.t('help.admin.value'),
            inline=False
        )
        
        # informacion adicional
        embed.add_field(
            name=t.t('help.info.name'),
            value=t.t('help.info.value'),
            inline=False
        )
        
        embed.set_footer(text=t.t('help.footer'))
        embed.timestamp = discord.utils.utcnow()
        
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(HelpCog(bot))

