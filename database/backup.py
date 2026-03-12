"""
Sistema de backups automáticos para la base de datos
"""
import os
import shutil
from datetime import datetime
from pathlib import Path
from config import DATABASE_URL
import sqlite3

# directorio de backups
BACKUP_DIR = Path('backups')
BACKUP_DIR.mkdir(exist_ok=True)

# numero maximo de backups a mantener
MAX_BACKUPS = 30  # mantener ultimos 30 backups

def get_db_path():
    """Obtiene la ruta de la base de datos desde DATABASE_URL"""
    if DATABASE_URL.startswith('sqlite:///'):
        # sqlite:///data/database.db -> data/database.db
        return DATABASE_URL.replace('sqlite:///', '')
    elif DATABASE_URL.startswith('sqlite://'):
        # sqlite://data/database.db -> data/database.db
        return DATABASE_URL.replace('sqlite://', '')
    return None

def create_backup():
    """Crea un backup de la base de datos"""
    db_path = get_db_path()
    if not db_path or not os.path.exists(db_path):
        print(f"❌ Base de datos no encontrada: {db_path}")
        return None
    
    # nombre del backup con timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_name = f"database_backup_{timestamp}.db"
    backup_path = BACKUP_DIR / backup_name
    
    try:
        # para sqlite, usar VACUUM INTO para crear backup limpio
        if db_path.endswith('.db'):
            conn = sqlite3.connect(db_path)
            conn.execute(f"VACUUM INTO '{backup_path}'")
            conn.close()
        else:
            # para otras bases de datos, copiar directamente
            shutil.copy2(db_path, backup_path)
        
        print(f"✅ Backup creado: {backup_name}")
        
        # limpiar backups antiguos
        cleanup_old_backups()
        
        return backup_path
    except Exception as e:
        print(f"❌ Error creando backup: {e}")
        # fallback, copia simple
        try:
            shutil.copy2(db_path, backup_path)
            print(f"✅ Backup creado (fallback): {backup_name}")
            return backup_path
        except Exception as e2:
            print(f"❌ Error en backup fallback: {e2}")
            return None

def cleanup_old_backups():
    """Elimina backups antiguos, manteniendo solo los más recientes"""
    try:
        backups = sorted(BACKUP_DIR.glob('database_backup_*.db'), key=os.path.getmtime, reverse=True)
        
        if len(backups) > MAX_BACKUPS:
            for old_backup in backups[MAX_BACKUPS:]:
                os.remove(old_backup)
                print(f"🗑️  Backup antiguo eliminado: {old_backup.name}")
    except Exception as e:
        print(f"⚠️  Error limpiando backups antiguos: {e}")

def restore_backup(backup_name):
    """Restaura la base de datos desde un backup"""
    backup_path = BACKUP_DIR / backup_name
    db_path = get_db_path()
    
    if not backup_path.exists():
        print(f"❌ Backup no encontrado: {backup_name}")
        return False
    
    if not db_path:
        print("❌ No se pudo determinar la ruta de la base de datos")
        return False
    
    try:
        # crear backup de la base de datos actual antes de restaurar
        current_backup = create_backup()
        if current_backup:
            print(f"✅ Backup de la base de datos actual creado antes de restaurar")
        
        # restaurar desde el backup
        shutil.copy2(backup_path, db_path)
        print(f"✅ Base de datos restaurada desde: {backup_name}")
        return True
    except Exception as e:
        print(f"❌ Error restaurando backup: {e}")
        return False

def list_backups():
    """Lista todos los backups disponibles"""
    backups = sorted(BACKUP_DIR.glob('database_backup_*.db'), key=os.path.getmtime, reverse=True)
    return [b.name for b in backups]

if __name__ == '__main__':
    # crear backup manual
    create_backup()
    print(f"\n📋 Backups disponibles: {len(list_backups())}")

