"""
Asignación automática de roles de Discord según el rango ELO del jugador.
Cuando un jugador sube o baja de rango, se le quita el rol anterior y se le asigna el actual.

Requisitos: bot con permiso Gestionar roles; rol del bot por encima de los roles de rango.
Crea roles con nombres exactos (Principiante, Hierro III, Bronce III, etc.)
o configura RANK_ROLE_IDS en .env (JSON: nombre_rango -> ID del rol).
"""
import discord
import json
import os

# lista de todos los nombres de rango (debe coincidir con get_rank_from_elo en utils/elo.py)
ALL_RANK_NAMES = [
    "Principiante",
    "Hierro III", "Hierro II", "Hierro I",
    "Bronce III", "Bronce II", "Bronce I",
    "Plata III", "Plata II", "Plata I",
    "Oro III", "Oro II", "Oro I",
    "Platino III", "Platino II", "Platino I",
    "Esmeralda III", "Esmeralda II", "Esmeralda I",
    "Diamante III", "Diamante II", "Diamante I",
    "Promesa", "Predator", "Leyenda",
]


def _get_rank_role_ids() -> dict:
    """Carga el mapeo nombre_rango -> role_id desde RANK_ROLE_IDS (JSON en .env)."""
    raw = os.getenv("RANK_ROLE_IDS", "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return {str(k): int(v) for k, v in data.items()}
    except (json.JSONDecodeError, ValueError):
        return {}


def _find_role_by_name(guild, rank_name: str):
    """
    Busca un rol en el servidor por nombre.
    Primero coincidencia exacta, luego insensible a mayúsculas y espacios.
    """
    if not guild or not getattr(guild, 'roles', None):
        return None
    rank_clean = (rank_name or "").strip()
    for r in guild.roles:
        if r.name == rank_clean:
            return r
    for r in guild.roles:
        if (r.name or "").strip().lower() == rank_clean.lower():
            return r
    return None


def get_role_for_rank(guild, rank: str):
    """
    Obtiene el rol de Discord correspondiente a un rango.
    Si RANK_ROLE_IDS está configurado, busca por ID; si no, busca por nombre (exacto o case-insensitive).
    """
    role_ids = _get_rank_role_ids()
    if rank in role_ids:
        role = guild.get_role(role_ids[rank])
        if role:
            return role
    # buscar por nombre exacto o insensible a mayusculas
    return _find_role_by_name(guild, rank)


async def update_member_rank_roles(member, new_rank: str, guild) -> bool:
    """
    Actualiza los roles de rango del miembro: quita todos los roles de rango
    que tenga y le asigna el rol correspondiente a new_rank.

    Args:
        member: discord.Member (debe estar en guild).
        new_rank: Nombre del rango actual (ej. "Bronce III").
        guild: discord.Guild.

    Returns:
        True si se modificó al menos un rol, False si no hubo cambios o hubo error.
    """
    if not member or not guild or member.guild.id != guild.id:
        return False
    try:
        role_ids = _get_rank_role_ids()
        
        # roles de rango a considerar: los que tenemos por ID o por nombre
        rank_roles_to_remove = []
        for rank_name in ALL_RANK_NAMES:
            if rank_name == new_rank:
                continue
            if rank_name in role_ids:
                r = guild.get_role(role_ids[rank_name])
            else:
                r = _find_role_by_name(guild, rank_name)
            if r and r in member.roles:
                rank_roles_to_remove.append(r)
        new_role = get_role_for_rank(guild, new_rank)
        changed = False
        if rank_roles_to_remove:
            await member.remove_roles(*rank_roles_to_remove)
            changed = True
        if new_role and new_role not in member.roles:
            await member.add_roles(new_role)
            changed = True
        return changed
    except discord.Forbidden:
        # Re-lanzar para que el caller pueda contar "permiso denegado" (ej. jerarquía de roles)
        raise
    except Exception:
        return False
