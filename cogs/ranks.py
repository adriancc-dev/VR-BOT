import discord
from discord import app_commands
from discord.ext import commands
from database.database import get_db
from database.models import Player
from utils.elo import get_rank_emoji
from utils.i18n import get_player_translator, get_translator, translate_rank

class RanksCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="ranks", description="Muestra todas las ligas y el ELO necesario para alcanzarlas")
    async def ranks(self, interaction: discord.Interaction):
        """Muestra todos los rangos disponibles y el ELO necesario para cada uno"""
        # responder inmediatamente para evitar timeout
        await interaction.response.defer()
        
        with get_db() as db:
            player = db.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
            t = get_player_translator(player) if player else get_translator('es')
        
        # definir todos los rangos con sus rangos de elo
        ranks_data = [
            {"rank": "Principiante", "min_elo": 0, "max_elo": 99},
            {"rank": "Hierro III", "min_elo": 100, "max_elo": 199},
            {"rank": "Hierro II", "min_elo": 200, "max_elo": 299},
            {"rank": "Hierro I", "min_elo": 300, "max_elo": 399},
            {"rank": "Bronce III", "min_elo": 400, "max_elo": 499},
            {"rank": "Bronce II", "min_elo": 500, "max_elo": 599},
            {"rank": "Bronce I", "min_elo": 600, "max_elo": 699},
            {"rank": "Plata III", "min_elo": 700, "max_elo": 799},
            {"rank": "Plata II", "min_elo": 800, "max_elo": 899},
            {"rank": "Plata I", "min_elo": 900, "max_elo": 999},
            {"rank": "Oro III", "min_elo": 1000, "max_elo": 1149},
            {"rank": "Oro II", "min_elo": 1150, "max_elo": 1299},
            {"rank": "Oro I", "min_elo": 1300, "max_elo": 1449},
            {"rank": "Platino III", "min_elo": 1450, "max_elo": 1599},
            {"rank": "Platino II", "min_elo": 1600, "max_elo": 1749},
            {"rank": "Platino I", "min_elo": 1750, "max_elo": 1899},
            {"rank": "Esmeralda III", "min_elo": 1900, "max_elo": 2099},
            {"rank": "Esmeralda II", "min_elo": 2100, "max_elo": 2299},
            {"rank": "Esmeralda I", "min_elo": 2300, "max_elo": 2499},
            {"rank": "Diamante III", "min_elo": 2500, "max_elo": 2799},
            {"rank": "Diamante II", "min_elo": 2800, "max_elo": 3099},
            {"rank": "Diamante I", "min_elo": 3100, "max_elo": 3399},
            {"rank": "Promesa", "min_elo": 3400, "max_elo": 3899},
            {"rank": "Predator", "min_elo": 3900, "max_elo": 4499},
            {"rank": "Leyenda", "min_elo": 4500, "max_elo": 5000},
        ]
        
        # crear embed
        embed = discord.Embed(
            title=t.t('ranks.title'),
            description=t.t('ranks.description'),
            color=discord.Color.gold()
        )
        
        # mostrar todos los rangos en una sola lista
        # dividir en partes si es muy extenso
        ranks_list = ""
        previous_rank_base = None  # para detectar cambios de rango
        
        for rank_info in ranks_data:

            # extraer el nombre base del rango
            
            rank_name = rank_info["rank"]
            rank_base = rank_name.split()[0]  # primera palabra (Hierro, Bronce, etc.)
            
            # si cambio de rango base, añadir linea en blanco
            if previous_rank_base is not None and rank_base != previous_rank_base:
                ranks_list += "\n"
            
            # traducir el nombre del rango segun el idioma del usuario
            rank_translated = translate_rank(rank_info["rank"], t.language)
            emoji = get_rank_emoji(rank_info["rank"])  # Emoji usa el nombre base en español
            if rank_info["max_elo"] == 5000:
                line = t.t('ranks.rank_format_plus', emoji=emoji, rank=rank_translated, min_elo=rank_info['min_elo']) + "\n"
            else:
                line = t.t('ranks.rank_format', emoji=emoji, rank=rank_translated, min_elo=rank_info['min_elo'], max_elo=rank_info['max_elo']) + "\n"
            ranks_list += line
            
            previous_rank_base = rank_base
        
    
        # si excede el limite de caracteres, dividir en varios campos

        if len(ranks_list) > 1024:
            # dividir en campos de maximo 1000 caracteres y dejar margen
            chunk_size = 1000
            chunks = []
            current_chunk = ""
            
            for line in ranks_list.split('\n'):
                if len(current_chunk) + len(line) + 1 > chunk_size and current_chunk:
                    chunks.append(current_chunk)
                    current_chunk = line + "\n"
                else:
                    current_chunk += line + "\n"
            
            if current_chunk:
                chunks.append(current_chunk)
            
            # añadir cada chunk como un campo separado
            for i, chunk in enumerate(chunks):
                field_name = "" if i == 0 else ""
                embed.add_field(name=field_name, value=chunk.strip(), inline=False)
        else:
            embed.add_field(name="", value=ranks_list, inline=False)
        
        embed.set_footer(text=t.t('ranks.footer'))
        embed.timestamp = discord.utils.utcnow()
        
        await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(RanksCog(bot))

