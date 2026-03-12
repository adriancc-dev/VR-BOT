from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
from config import DATABASE_URL
from database.models import Base
import os
import sqlite3

# crear directorio data si no existe (solo para sqlite)
if DATABASE_URL.startswith('sqlite'):
    os.makedirs('data', exist_ok=True)

# configuracion optimizada segun el tipo de base de datos
connect_args = {}
pool_config = {
    'pool_pre_ping': True,  # verifica conexiones antes de usarlas
    'pool_recycle': 3600,  # recicla conexiones cada hora
}

if DATABASE_URL.startswith('sqlite'):
    # optimizaciones para sqlite
    connect_args = {
        'check_same_thread': False,  # permite multiples threads
        'timeout': 30,  # timeout de 30 segundos
    }
    pool_config.update({
        'pool_size': 10,
        'max_overflow': 20,
    })
elif DATABASE_URL.startswith('postgresql'):
    # optimizaciones para postgresql
    pool_config.update({
        'pool_size': 20,  # mas conexiones para postgresql
        'max_overflow': 40,  # mas overflow para alta carga
        'pool_timeout': 30,  # timeout de pool
    })

# pool de conexiones optimizado para alta carga
engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args=connect_args,
    **pool_config
)

# configurar sqlite para mejor rendimiento
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    """Configura SQLite para mejor rendimiento"""
    if isinstance(dbapi_conn, sqlite3.Connection):
        cursor = dbapi_conn.cursor()
        # WAL mode para mejor concurrencia
        cursor.execute("PRAGMA journal_mode=WAL")
        # mejor rendimiento en escrituras
        cursor.execute("PRAGMA synchronous=NORMAL")
        # cache mas grande para mejor rendimiento
        cursor.execute("PRAGMA cache_size=-64000")  # 64MB cache
        # mejor uso de memoria
        cursor.execute("PRAGMA temp_store=MEMORY")
        # optimizaciones adicionales
        cursor.execute("PRAGMA mmap_size=268435456")  # 256MB memory-mapped I/O
        cursor.execute("PRAGMA busy_timeout=30000")  # 30 segundos timeout
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    """Inicializa la base de datos creando todas las tablas"""
    Base.metadata.create_all(bind=engine)

@contextmanager
def get_db():
    """Context manager para obtener sesión de base de datos"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

