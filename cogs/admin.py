import discord
from discord import app_commands
from discord.ext import commands
from database.database import get_db
from database.models import Player
from config import DISCORD_GUILD_ID, ADMIN_IDS, MIN_ELO, MAX_ELO
from utils.i18n import get_player_translator, get_translator
from utils.elo import get_rank_from_elo
from utils.rank_roles import update_member_rank_roles
import asyncio


class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _has_admin_permission(self, interaction: discord.Interaction) -> bool:
        """Comprueba si el usuario es admin (permiso de Discord o listado en ADMIN_IDS)."""
        return (
            interaction.user.guild_permissions.administrator
            or interaction.user.id in ADMIN_IDS
        )
    
    @app_commands.command(name="sync", description="Sincroniza los comandos del bot (solo administradores)")
    @app_commands.describe(
        global_sync="Sincronizar globalmente (por defecto: solo este servidor)",
        clear_global="Limpiar comandos globales primero (útil para eliminar duplicados)"
    )
    async def sync(self, interaction: discord.Interaction, global_sync: bool = False, clear_global: bool = False):
        with get_db() as db:
            player = db.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
            t = get_player_translator(player) if player else get_translator('es')
        
        # verificar que el usuario sea administrador
        if not self._has_admin_permission(interaction):
            await interaction.response.send_message(t.t('admin.sync.no_permission'), ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            if global_sync:
                # sincronizar globalmente
                if clear_global:
                    self.bot.tree.clear_commands(guild=None)
                synced = await self.bot.tree.sync()
                await interaction.followup.send(t.t('admin.sync.global_synced', count=len(synced)))
            else:
                # sincronizar solo para este servidor (mas rapido)
                guild = interaction.guild
                
                # limpiar comandos obsoletos primero
                self.bot.tree.clear_commands(guild=guild)
                
                # si se solicita limpiar comandos globales
                if clear_global:
                    self.bot.tree.clear_commands(guild=None)
                    await self.bot.tree.sync()
                
                # copiar comandos globales al servidor antes de sincronizar
                self.bot.tree.copy_global_to(guild=guild)
                
                # sincronizar
                synced = await self.bot.tree.sync(guild=guild)
                message = t.t('admin.sync.guild_synced', count=len(synced))
                if clear_global:
                    message += t.t('admin.sync.global_cleared')
                await interaction.followup.send(message)
        except Exception as e:
            await interaction.followup.send(t.t('admin.sync.error', error=str(e)))
    
    @app_commands.command(name="server-id", description="Muestra el ID del servidor actual")
    async def server_id(self, interaction: discord.Interaction):
        with get_db() as db:
            player = db.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
            t = get_player_translator(player) if player else get_translator('es')
        
        await interaction.response.send_message(
            t.t('admin.server_id.message', id=interaction.guild.id),
            ephemeral=True
        )

    @app_commands.command(
        name="elo-add",
        description="Añade puntos de ELO 1v1 a un jugador (solo administradores)",
    )
    @app_commands.describe(
        user="Usuario al que quieres añadir ELO",
        amount="Cantidad de ELO a añadir (positivo)",
    )
    async def elo_add(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        amount: int,
    ):
        with get_db() as db:
            invoker_player = db.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
            t = get_player_translator(invoker_player) if invoker_player else get_translator('es')

        if not self._has_admin_permission(interaction):
            await interaction.response.send_message(
                t.t('admin.sync.no_permission'),
                ephemeral=True,
            )
            return

        if amount == 0:
            await interaction.response.send_message(
                "La cantidad de ELO no puede ser 0.",
                ephemeral=True,
            )
            return

        # mensaje publico en el canal
        await interaction.response.defer(ephemeral=False)

        try:
            with get_db() as db:
                player = db.query(Player).filter(Player.discord_id == str(user.id)).first()
                if not player:
                    player = Player(
                        discord_id=str(user.id),
                        username=user.name,
                    )
                    db.add(player)
                    db.commit()
                    db.refresh(player)

                old_elo = player.elo_1v1 if player.elo_1v1 is not None else 0
                new_elo = old_elo + amount
                
                # clamp al rango permitido globalmente
                new_elo = max(MIN_ELO, min(MAX_ELO, new_elo))

                player.elo_1v1 = new_elo
                
                # mantener elo general alineado con el 1v1 para compatibilidad
                player.elo = new_elo
                db.commit()

            # actualizar roles de discord segun el nuevo rango
            if interaction.guild:
                try:
                    await update_member_rank_roles(user, get_rank_from_elo(new_elo), interaction.guild)
                except Exception:
                    pass

            await interaction.followup.send(
                f"✅ ELO actualizado para {user.mention}: **{old_elo:.0f} ➜ {new_elo:.0f}** "
                f"(+{amount} puntos solicitados).",
                ephemeral=False,
            )
        except Exception as e:
            await interaction.followup.send(
                f"❌ Ocurrió un error al actualizar el ELO: {e}",
                ephemeral=True,
            )

    @app_commands.command(
        name="elo-remove",
        description="Resta puntos de ELO 1v1 a un jugador (solo administradores)",
    )
    @app_commands.describe(
        user="Usuario al que quieres quitar ELO",
        amount="Cantidad de ELO a quitar (positivo)",
    )
    async def elo_remove(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        amount: int,
    ):
        with get_db() as db:
            invoker_player = db.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
            t = get_player_translator(invoker_player) if invoker_player else get_translator('es')

        if not self._has_admin_permission(interaction):
            await interaction.response.send_message(
                t.t('admin.sync.no_permission'),
                ephemeral=True,
            )
            return

        if amount == 0:
            await interaction.response.send_message(
                "La cantidad de ELO no puede ser 0.",
                ephemeral=True,
            )
            return

        # mensaje en el canal
        await interaction.response.defer(ephemeral=False)

        try:
            with get_db() as db:
                player = db.query(Player).filter(Player.discord_id == str(user.id)).first()
                if not player:
                    player = Player(
                        discord_id=str(user.id),
                        username=user.name,
                    )
                    db.add(player)
                    db.commit()
                    db.refresh(player)

                old_elo = player.elo_1v1 if player.elo_1v1 is not None else 0
                new_elo = old_elo - amount
                # clamp al rango permitido globalmente
                new_elo = max(MIN_ELO, min(MAX_ELO, new_elo))

                player.elo_1v1 = new_elo
                player.elo = new_elo
                db.commit()

            # actualizar roles de discord segun el nuevo rango
            if interaction.guild:
                try:
                    await update_member_rank_roles(user, get_rank_from_elo(new_elo), interaction.guild)
                except Exception:
                    pass

            await interaction.followup.send(
                f"✅ ELO actualizado para {user.mention}: **{old_elo:.0f} ➜ {new_elo:.0f}** "
                f"(-{amount} puntos solicitados).",
                ephemeral=False,
            )
        except Exception as e:
            await interaction.followup.send(
                f"❌ Ocurrió un error al actualizar el ELO: {e}",
                ephemeral=True,
            )

    @app_commands.command(
        name="resync-ranks",
        description="Re-sincroniza los roles de rango ELO de todos los jugadores del servidor (solo administradores)",
    )
    async def resync_ranks(self, interaction: discord.Interaction):
        """
        Recalcula el rango ELO de todos los jugadores en la base de datos y
        vuelve a aplicar los roles de Discord correspondientes en este servidor.
        Solo para administradores / ADMIN_IDS.
        """
        # obtener traductor del que ejecuto el comando
        with get_db() as db:
            invoker_player = db.query(Player).filter(Player.discord_id == str(interaction.user.id)).first()
            t = get_player_translator(invoker_player) if invoker_player else get_translator('es')

        if not self._has_admin_permission(interaction):
            await interaction.response.send_message(
                t.t('admin.sync.no_permission'),
                ephemeral=True,
            )
            return

        if not interaction.guild:
            await interaction.response.send_message(
                "Este comando solo puede usarse dentro de un servidor.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        total_players = 0
        updated = 0
        already_ok = 0
        skipped_no_member = 0
        permission_denied = 0
        skipped_error = 0

        try:
            with get_db() as db:
                players = db.query(Player).all()
                # copiar el discord id y elo a datos planos para no depender de la sesion fuera del with
                player_data = []
                for p in players:
                    elo_val = p.elo_1v1 if p.elo_1v1 is not None else (p.elo or 0)
                    player_data.append((str(p.discord_id), elo_val))

            for discord_id, elo_value in player_data:
                total_players += 1
                
                # obtener el miembro desde la api
                member = None
                for attempt in range(3):
                    try:
                        member = await guild.fetch_member(int(discord_id))
                        break
                    except (TypeError, ValueError):
                        break
                    except discord.NotFound:
                        skipped_no_member += 1
                        break
                    except discord.Forbidden:
                        skipped_error += 1
                        break
                    except discord.HTTPException as e:
                        if e.status == 429 and attempt < 2:
                            wait = (e.retry_after or 2) + 0.5
                            await asyncio.sleep(wait)
                        else:
                            skipped_error += 1
                            break

                if member is None:
                    continue

                rank_name = get_rank_from_elo(elo_value)
                update_attempt = 0
                max_update_attempts = 2
                while update_attempt < max_update_attempts:
                    try:
                        changed = await update_member_rank_roles(member, rank_name, guild)
                        if changed:
                            updated += 1
                        else:
                            already_ok += 1
                        break
                    except discord.Forbidden:
                        permission_denied += 1
                        break
                    except discord.HTTPException as e:
                        if e.status == 429 and update_attempt < max_update_attempts - 1:
                            wait = (e.retry_after or 2) + 0.5
                            await asyncio.sleep(wait)
                            update_attempt += 1
                        else:
                            skipped_error += 1
                            break
                    except Exception:
                        skipped_error += 1
                        break

                # pequeña pausa para evitar rate limits con muchos miembros
                await asyncio.sleep(0.1)

            msg = (
                f"✅ Re-sincronización de roles de rango completada.\n"
                f"- Jugadores en BD: **{total_players}**\n"
                f"- Roles actualizados: **{updated}**\n"
                f"- Ya tenían el rol correcto: **{already_ok}**\n"
                f"- No están en el servidor: **{skipped_no_member}**\n"
                f"- Permiso denegado (jerarquía de roles): **{permission_denied}**\n"
                f"- Otros errores: **{skipped_error}**"
            )
            if permission_denied > 0:
                msg += "\n\n💡 *Si hay «Permiso denegado», sube el rol del bot por encima de los roles de rango en Configuración del servidor > Roles.*"
            await interaction.followup.send(msg, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(
                f"❌ Ocurrió un error durante la re-sincronización de rangos: {e}",
                ephemeral=True,
            )


async def setup(bot):
    await bot.add_cog(AdminCog(bot))

