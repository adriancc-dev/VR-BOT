"""
Cog para cambiar el idioma del bot
Soporta: Español (es), Inglés (en), Francés (fr), Italiano (it)
"""
import discord
from discord import app_commands
from discord.ext import commands
from database.database import get_db
from database.models import Player
from utils.i18n import Translator

class LanguageCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="language", description="Cambia el idioma del bot")
    @app_commands.describe(lang="Idioma a seleccionar")
    @app_commands.choices(lang=[
        app_commands.Choice(name="Español", value="es"),
        app_commands.Choice(name="English", value="en"),
        app_commands.Choice(name="Français", value="fr"),
        app_commands.Choice(name="Italiano", value="it"),
    ])
    async def language(self, interaction: discord.Interaction, lang: str):
        """Cambia el idioma preferido del usuario"""
        await interaction.response.defer(ephemeral=True)
        
        # validar idioma
        if lang not in ['es', 'en', 'fr', 'it']:
            t = Translator('es')  # Usar español como fallback
            await interaction.followup.send(
                t.t('language.errors.invalid'),
                ephemeral=True
            )
            return
        
        with get_db() as db:

            # obtener o crear jugador
            player = db.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
            
            if not player:
                # crear jugador si no existe
                player = Player(
                    discord_id=str(interaction.user.id),
                    username=interaction.user.name,
                    language=lang
                )
                db.add(player)
            else:
                # actualizar idioma
                player.language = lang
                if player.username != interaction.user.name:
                    player.username = interaction.user.name
            
            db.commit()
            db.refresh(player)
        
        # obtener traductor con el nuevo idioma
        t = Translator(lang)
        
        # nombres de idiomas
        language_names = {
            'es': 'Español',
            'en': 'English',
            'fr': 'Français',
            'it': 'Italiano'
        }
        
        language_name = language_names.get(lang, lang)
        
        # crear embed de confirmacion
        embed = discord.Embed(
            title=t.t('language.title'),
            description=t.t('language.description', language=language_name),
            color=discord.Color.green()
        )
        embed.add_field(
            name=t.t('language.current'),
            value=f"**{language_name}**",
            inline=False
        )
        embed.set_footer(text=t.t('language.footer', language=language_name))
        embed.timestamp = discord.utils.utcnow()
        
        await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(LanguageCog(bot))

