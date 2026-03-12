from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()

class Player(Base):
    __tablename__ = 'players'
    
    id = Column(Integer, primary_key=True)
    discord_id = Column(String, unique=True, nullable=False, index=True)
    username = Column(String, nullable=False)
    language = Column(String, default='es')  # idioma preferido: 'es', 'en', 'fr'
    elo = Column(Float, default=0)  # elo general (para compatibilidad)
    elo_1v1 = Column(Float, default=0)  # elo especifico para 1v1
    xp = Column(Integer, default=0)
    level = Column(Integer, default=1)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    draws = Column(Integer, default=0)
    win_streak = Column(Integer, default=0)
    best_win_streak = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # relaciones
    matches_as_player1 = relationship('Match', foreign_keys='Match.player1_id', back_populates='player1')
    matches_as_player2 = relationship('Match', foreign_keys='Match.player2_id', back_populates='player2')
    team_memberships = relationship('TeamMember', back_populates='player')
    tournament_participations = relationship('TournamentParticipant', back_populates='player')
    
    def win_rate(self):
        total = self.wins + self.losses
        return (self.wins / total * 100) if total > 0 else 0
    
    def prestige(self):
        """
        Calcula el prestigio del jugador usando la fórmula:
        Prestigio = (ELO x Winrate) x √(Partidas)
        
        Returns:
            float: Prestigio del jugador
        """
        import math
        
        # obtener elo 1v1 (o elo general si no existe)
        elo = self.elo_1v1 if self.elo_1v1 is not None else self.elo
        
        # calcular winrate como decimal
        total_matches = self.wins + self.losses + self.draws
        if total_matches == 0:
            return 0.0
        
        winrate_decimal = self.win_rate() / 100.0  # Convertir porcentaje a decimal
        
        # calcular prestigio
        prestige_value = (elo * winrate_decimal) * math.sqrt(total_matches)
        
        return prestige_value

class Team(Base):
    __tablename__ = 'teams'
    
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    tag = Column(String, unique=True)  # tag del equipo, prefijo
    logo_url = Column(String)  # url de la imagen/logo del equipo
    elo = Column(Float, default=0)  # elo del equipo = promedio de top 10 elo 1v1 + elo guerras de clanes
    team_war_elo = Column(Float, default=0)  # elo ganado/perdido en guerras de clanes
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    members = relationship('TeamMember', back_populates='team')
    matches = relationship('Match', back_populates='team1', foreign_keys='Match.team1_id')
    matches2 = relationship('Match', back_populates='team2', foreign_keys='Match.team2_id')
    
    def get_leader(self):
        """Obtiene el líder del equipo"""
        for member in self.members:
            if member.role == 'leader':
                return member
        return None
    
    def member_count(self):
        """Retorna el número de miembros"""
        return len(self.members)
    
    def win_rate(self):
        """Calcula el porcentaje de victorias"""
        total = self.wins + self.losses
        return (self.wins / total * 100) if total > 0 else 0
    
    def calculate_team_elo(self):
        """
        Calcula el ELO del equipo usando la nueva fórmula:
        ELO del equipo = (Suma de los 10 mejores ELO 1v1) / 10 + team_war_elo
        
        Solo cuenta el ELO 1v1 individual (matchmaking y score normal),
        NO incluye el ELO ganado en guerras de clanes.
        """
        # obtener todos los elo 1v1 de los miembros
        member_elos = []
        for member in self.members:
            if member.player:
                # usar elo 1v1 si existe, sino usar 0
                player_elo = member.player.elo_1v1 if member.player.elo_1v1 is not None else 0
                member_elos.append(player_elo)
        
        # ordenar de mayor a menor y tomar los 10 mejores
        member_elos.sort(reverse=True)
        top_10_elos = member_elos[:10]
        
        # calcular promedio de los top 10
        if len(top_10_elos) > 0:
            avg_top_10 = sum(top_10_elos) / len(top_10_elos)
        else:
            avg_top_10 = 0
        
        # sumar el elo de guerras de clanes
        team_war_elo = self.team_war_elo if self.team_war_elo is not None else 0
        
        return avg_top_10 + team_war_elo
    
    def update_team_elo(self):
        """
        Actualiza el ELO del equipo usando la nueva fórmula:
        (Promedio de top 10 ELO 1v1) + team_war_elo
        """
        self.elo = self.calculate_team_elo()

class TeamMember(Base):
    __tablename__ = 'team_members'
    
    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey('teams.id'), nullable=False)
    player_id = Column(Integer, ForeignKey('players.id'), nullable=False)
    role = Column(String, default='member')  # leader, coleader, staff, member
    joined_at = Column(DateTime, default=datetime.utcnow)
    
    team = relationship('Team', back_populates='members')
    player = relationship('Player', back_populates='team_memberships')
    
    def can_invite(self):
        """Verifica si el miembro puede invitar a otros"""
        return self.role in ['leader', 'co-leader', 'staff']
    
    def can_kick(self):
        """Verifica si el miembro puede expulsar a otros"""
        return self.role in ['leader', 'co-leader', 'staff']
    
    def can_manage_roles(self):
        """Verifica si el miembro puede cambiar roles"""
        return self.role in ['leader', 'co-leader']
    
    def can_disband(self):
        """Verifica si el miembro puede disolver el equipo"""
        return self.role == 'leader'

class Match(Base):
    __tablename__ = 'matches'
    
    id = Column(Integer, primary_key=True)
    match_type = Column(String, nullable=False)  # 1v1, 5v5
    status = Column(String, default='pending')  # pending, reported, confirmed, disputed, cancelled
    
    # para 1v1
    player1_id = Column(Integer, ForeignKey('players.id'))
    player2_id = Column(Integer, ForeignKey('players.id'))
    
    # para equipos
    team1_id = Column(Integer, ForeignKey('teams.id'))
    team2_id = Column(Integer, ForeignKey('teams.id'))
    
    # resultados
    score1 = Column(Integer)
    score2 = Column(Integer)
    reported_by = Column(Integer, ForeignKey('players.id'))
    confirmed_by = Column(Integer, ForeignKey('players.id'))
    
    # elo y xp
    elo_change1 = Column(Float, default=0)
    elo_change2 = Column(Float, default=0)
    xp_gained1 = Column(Integer, default=0)
    xp_gained2 = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    reported_at = Column(DateTime)
    confirmed_at = Column(DateTime)
    
    # relaciones
    player1 = relationship('Player', foreign_keys=[player1_id], back_populates='matches_as_player1')
    player2 = relationship('Player', foreign_keys=[player2_id], back_populates='matches_as_player2')
    team1 = relationship('Team', foreign_keys=[team1_id], back_populates='matches')
    team2 = relationship('Team', foreign_keys=[team2_id], back_populates='matches2')

class MatchmakingRequest(Base):
    __tablename__ = 'matchmaking_requests'
    
    id = Column(Integer, primary_key=True)
    player_id = Column(Integer, ForeignKey('players.id'), nullable=False)
    match_type = Column(String, nullable=False)  # 1v1, 5v5
    is_anonymous = Column(Boolean, default=False)
    is_global = Column(Boolean, default=False)  # para buscar en todo el servidor
    min_elo = Column(Integer)
    max_elo = Column(Integer)
    hint = Column(String)  # pista opcional
    status = Column(String, default='active')  # active, accepted, expired, cancelled
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)
    
    player = relationship('Player')

class TeamInvite(Base):
    __tablename__ = 'team_invites'
    
    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey('teams.id'), nullable=False)
    player_id = Column(Integer, ForeignKey('players.id'), nullable=False)
    invited_by = Column(Integer, ForeignKey('players.id'), nullable=False)
    status = Column(String, default='pending')  # pending, accepted, declined, expired
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)
    
    team = relationship('Team')

class TeamWar(Base):
    __tablename__ = 'team_wars'
    
    id = Column(Integer, primary_key=True)
    team1_id = Column(Integer, ForeignKey('teams.id'), nullable=False)
    team2_id = Column(Integer, ForeignKey('teams.id'), nullable=False)
    war_type = Column(String, default='amistoso')  # amistoso, competitivo
    status = Column(String, default='pending')  # pending, players_selected, matchmaking, in_progress, completed, cancelled
    team1_started = Column(Boolean, default=False)  # si el lider del equipo 1 confirmo el inicio
    team2_started = Column(Boolean, default=False)  # si el lider del equipo 2 confirmo el inicio
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    
    team1 = relationship('Team', foreign_keys=[team1_id])
    team2 = relationship('Team', foreign_keys=[team2_id])
    matches = relationship('TeamWarMatch', back_populates='war')

class TeamWarMatch(Base):
    __tablename__ = 'team_war_matches'
    
    id = Column(Integer, primary_key=True)
    war_id = Column(Integer, ForeignKey('team_wars.id'), nullable=False)
    team1_player_id = Column(Integer, ForeignKey('players.id'), nullable=True)  # puede ser none hasta que se asigne
    team2_player_id = Column(Integer, ForeignKey('players.id'), nullable=True)  # puede ser none hasta que se asigne
    match_number = Column(Integer)  # numero del enfrentamiento (1 al 5)
    status = Column(String, default='pending')  # pending, reported, confirmed
    score1 = Column(Integer)
    score2 = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # campos para asignacion manual de enfrentamientos
    assigned_by = Column(Integer, ForeignKey('players.id'), nullable=True)  # lider que propuso la asignacion
    assignment_status = Column(String, default='pending')  # pending, confirmed, rejected
    
    war = relationship('TeamWar', back_populates='matches')

class Tournament(Base):
    __tablename__ = 'tournaments'
    
    id = Column(Integer, primary_key=True)
    challonge_tournament_id = Column(Integer, nullable=False)
    challonge_url = Column(String, nullable=False, unique=True)
    name = Column(String, nullable=False)
    tournament_type = Column(String, default='single elimination')
    status = Column(String, default='pending')  # pending, open_signup, underway, complete, cancelled
    created_by = Column(Integer, ForeignKey('players.id'))
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # nuevos campos para el sistema mejorado
    game = Column(String)  # tipo de juego
    start_date = Column(DateTime)  # fecha de inicio del torneo
    advertise = Column(Boolean, default=True)  # si se debe anunciar el torneo
    participant_role_id = Column(String)  # rol de participantes
    organizer_role_id = Column(String)  # rol de organizadores
    inscription_channel_id = Column(String)  # canal de inscripcion
    panel_channel_id = Column(String)  # canal del panel/bracket
    result_channel_id = Column(String)  # canal de resultados
    inscription_message_id = Column(String)  # mensaje de inscripcion
    bracket_message_id = Column(String)  # mensaje del bracket
    
    participants = relationship('TournamentParticipant', back_populates='tournament')

class TournamentParticipant(Base):
    """Mapea Discord ID -> Nombre en Challonge para cada torneo"""
    __tablename__ = 'tournament_participants'
    
    id = Column(Integer, primary_key=True)
    tournament_id = Column(Integer, ForeignKey('tournaments.id'), nullable=False)
    player_id = Column(Integer, ForeignKey('players.id'), nullable=False)
    challonge_name = Column(String, nullable=False)  # nombre usado en challonge al inscribirse
    challonge_participant_id = Column(String)  # id del participante en challonge
    created_at = Column(DateTime, default=datetime.utcnow)
    
    tournament = relationship('Tournament', back_populates='participants')
    player = relationship('Player', back_populates='tournament_participations')
