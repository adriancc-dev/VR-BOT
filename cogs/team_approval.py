import discord
from discord.ext import commands
from database.database import get_db
from database.models import Player, Team, TeamMember
from datetime import datetime
from sqlalchemy import or_

class TeamApprovalView(discord.ui.View):
    def __init__(self, team_id: int, bot):
        super().__init__(timeout=None)
        self.team_id = team_id
        self.bot = bot
    
    @discord.ui.button(label="✅ Aprobar", style=discord.ButtonStyle.success, emoji="✅")
    async def approve_team(self, interaction: discord.Interaction, button: discord.ui.Button):

        # verificar que sea administrador
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Solo los administradores pueden aprobar equipos.", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        with get_db() as db:
            team = db.query(Team).filter(Team.id == self.team_id).first()
            
            if not team:
                await interaction.followup.send("❌ Este equipo ya no existe.", ephemeral=True)
                return
            
            # actualizar el mensaje
            embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
            embed.color = discord.Color.green()
            embed.add_field(name="✅ Estado", value=f"Aprobado por {interaction.user.mention}", inline=False)
            embed.timestamp = datetime.utcnow()
            
            # deshabilitar botones
            for item in self.children:
                item.disabled = True
            
            await interaction.followup.edit_message(interaction.message.id, embed=embed, view=self)
            await interaction.followup.send("✅ Equipo aprobado exitosamente.", ephemeral=True)
    
    @discord.ui.button(label="❌ Rechazar", style=discord.ButtonStyle.danger, emoji="❌")
    async def reject_team(self, interaction: discord.Interaction, button: discord.ui.Button):
        # verificar que sea administrador
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Solo los administradores pueden rechazar equipos.", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        with get_db() as db:
            team = db.query(Team).filter(Team.id == self.team_id).first()
            
            if not team:
                await interaction.followup.send("❌ Este equipo ya no existe.", ephemeral=True)
                return
            
            # guardar info antes de eliminar para notificar
            team_name = team.name
            leader = team.get_leader()
            
            # notificar al lider antes de eliminar
            if leader:
                player = db.query(Player).filter(Player.id == leader.player_id).first()
                if player:
                    try:
                        user = await self.bot.fetch_user(int(player.discord_id))
                        if user:
                            embed = discord.Embed(
                                title="❌ Equipo Rechazado",
                                description=f"Tu equipo **{team_name}** ha sido **rechazado** por un administrador.",
                                color=discord.Color.red()
                            )
                            embed.set_footer(text="Puedes crear un nuevo equipo con /team-create")
                            try:
                                await user.send(embed=embed)
                            except discord.Forbidden:
                                pass
                    except:
                        pass
            
            # eliminar todas las referencias del equipo
            from database.models import TeamInvite, TeamWar, TeamWarMatch, Match
            
            # eliminar TeamWarMatch
            db.query(TeamWarMatch).filter(
                or_(
                    TeamWarMatch.team1_id == team.id,
                    TeamWarMatch.team2_id == team.id
                )
            ).delete(synchronize_session=False)
            
            # eliminar TeamWar
            db.query(TeamWar).filter(
                or_(
                    TeamWar.team1_id == team.id,
                    TeamWar.team2_id == team.id
                )
            ).delete(synchronize_session=False)
            
            # eliminar TeamInvite
            db.query(TeamInvite).filter(TeamInvite.team_id == team.id).delete(synchronize_session=False)
            
            # eliminar TeamMember
            db.query(TeamMember).filter(TeamMember.team_id == team.id).delete(synchronize_session=False)
            
            # actualizar referencias en Match
            db.query(Match).filter(Match.team1_id == team.id).update({Match.team1_id: None}, synchronize_session=False)
            db.query(Match).filter(Match.team2_id == team.id).update({Match.team2_id: None}, synchronize_session=False)
            
            # eliminar el equipo
            db.delete(team)
            db.commit()
            
            # actualizar el mensaje
            embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
            embed.color = discord.Color.red()
            embed.add_field(name="❌ Estado", value=f"Rechazado y eliminado por {interaction.user.mention}", inline=False)
            embed.timestamp = datetime.utcnow()
            
            # deshabilitar botones
            for item in self.children:
                item.disabled = True
            
            await interaction.followup.edit_message(interaction.message.id, embed=embed, view=self)
            await interaction.followup.send(f"❌ Equipo **{team_name}** rechazado y eliminado.", ephemeral=True)

async def setup(bot):
    # este cog solo exporta la vista
    pass
