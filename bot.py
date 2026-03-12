import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import os
from dotenv import load_dotenv

# Cargar variables de entorno PRIMERO (prioridad: .env.local para desarrollo, luego .env)
if os.path.exists('.env.local'):
    load_dotenv('.env.local')
    print("📝 Usando .env.local (modo desarrollo)")
else:
    load_dotenv()
    print("📝 Usando .env (modo producción)")

# Importar config DESPUÉS de cargar .env
from config import DISCORD_TOKEN, DISCORD_GUILD_ID, ALLOWED_GUILD_IDS
from database.database import init_db

# Inicializar base de datos
init_db()

# Configurar intents
# Usamos solo intents básicos necesarios para comandos slash
# Si necesitas intents privilegiados (message_content, members), 
# debes habilitarlos en: https://discord.com/developers/applications
intents = discord.Intents.default()
# intents.message_content = True  # Descomenta si necesitas leer contenido de mensajes
# intents.members = True  # Descomenta si necesitas acceder a la lista de miembros

# Crear bot
bot = commands.Bot(command_prefix='!', intents=intents)

# Check global para verificar servidores permitidos
async def check_allowed_guild(interaction: discord.Interaction) -> bool:
    """Verifica que el servidor esté en la lista blanca"""
    try:
        # Si no hay lista blanca configurada, permitir todos
        if not ALLOWED_GUILD_IDS or len(ALLOWED_GUILD_IDS) == 0:
            return True
        
        # Si es un DM, permitir (opcional, puedes cambiar esto)
        if not interaction.guild:
            return True
        
        # Verificar si el servidor está en la lista blanca
        if interaction.guild.id in ALLOWED_GUILD_IDS:
            return True
        
        # Servidor no permitido - enviar mensaje de error de forma segura
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ Este bot solo está disponible en servidores autorizados.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "❌ Este bot solo está disponible en servidores autorizados.",
                    ephemeral=True
                )
        except Exception as e:
            # Si hay un error al enviar el mensaje, solo loguearlo pero no fallar
            print(f"⚠️ Error al enviar mensaje de servidor no permitido: {e}")
        
        return False
    except Exception as e:
        # Si hay cualquier error en el check, loguearlo pero permitir la interacción
        # para evitar que se rompan todos los comandos
        print(f"⚠️ Error en check_allowed_guild: {e}")
        import traceback
        traceback.print_exc()
        # En caso de error, permitir la interacción para no romper todo
        return True

# Aplicar el check a todos los comandos
bot.tree.interaction_check = check_allowed_guild

@bot.event
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """Maneja errores de comandos slash"""
    if interaction.response.is_done():
        await interaction.followup.send(f"❌ Error: {str(error)}", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ Error: {str(error)}", ephemeral=True)
    print(f"❌ Error en comando {interaction.command.name if interaction.command else 'desconocido'}: {error}")
    import traceback
    traceback.print_exc()

@bot.event
async def on_ready():
    print(f'{bot.user} ha iniciado sesión!')
    print(f'Bot ID: {bot.user.id}')
    
    # Esperar un momento para asegurar que todo esté listo
    await asyncio.sleep(1)
    
    # Sincronizar comandos slash
    try:
        # Si hay servidores permitidos configurados, sincronizar para cada uno
        if ALLOWED_GUILD_IDS and len(ALLOWED_GUILD_IDS) > 0:
            print(f'📋 Sincronizando comandos para {len(ALLOWED_GUILD_IDS)} servidor(es) permitido(s)')
            total_synced = 0
            for guild_id in ALLOWED_GUILD_IDS:
                guild = discord.Object(id=guild_id)
                # Limpiar comandos obsoletos del servidor primero
                bot.tree.clear_commands(guild=guild)
                # IMPORTANTE: Copiar comandos globales al servidor antes de sincronizar
                bot.tree.copy_global_to(guild=guild)
                # Sincronizar
                synced = await bot.tree.sync(guild=guild)
                total_synced += len(synced)
                print(f'✅ Sincronizados {len(synced)} comandos para el servidor {guild_id}')
            print(f'✅ Total: {total_synced} comandos sincronizados en {len(ALLOWED_GUILD_IDS)} servidor(es)')
        # Si hay un GUILD_ID específico (legacy), sincronizar solo para ese servidor
        elif DISCORD_GUILD_ID and DISCORD_GUILD_ID != 0:
            guild = discord.Object(id=DISCORD_GUILD_ID)
            # Limpiar comandos obsoletos del servidor primero
            bot.tree.clear_commands(guild=guild)
            # IMPORTANTE: Copiar comandos globales al servidor antes de sincronizar
            bot.tree.copy_global_to(guild=guild)
            # Sincronizar
            synced = await bot.tree.sync(guild=guild)
            print(f'✅ Sincronizados {len(synced)} comandos para el servidor {DISCORD_GUILD_ID}')
            if len(synced) > 0:
                print(f'   Comandos: {", ".join([cmd.name for cmd in synced])}')
        else:
            # Sincronizar globalmente (puede tardar hasta 1 hora en propagarse)
            # Limpiar comandos globales primero
            bot.tree.clear_commands(guild=None)
            synced = await bot.tree.sync()
            print(f'✅ Sincronizados {len(synced)} comandos globalmente')
            print('⚠️  Nota: Los comandos globales pueden tardar hasta 1 hora en aparecer')
    except Exception as e:
        print(f'❌ Error sincronizando comandos: {e}')
        import traceback
        traceback.print_exc()

# Cargar cogs
async def load_cogs():
    for filename in os.listdir('./cogs'):
        if filename.endswith('.py') and filename != '__init__.py':
            try:
                await bot.load_extension(f'cogs.{filename[:-3]}')
                print(f'✅ Cargado: {filename}')
            except Exception as e:
                print(f'❌ Error cargando {filename}: {e}')
                import traceback
                traceback.print_exc()

async def main():
    async with bot:
        # Primero cargar los cogs
        await load_cogs()
        # Luego iniciar el bot (on_ready se llamará y sincronizará comandos)
        await bot.start(DISCORD_TOKEN)

if __name__ == '__main__':
    asyncio.run(main())

