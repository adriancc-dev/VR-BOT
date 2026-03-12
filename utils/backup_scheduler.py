"""
Programador de backups automáticos para la base de datos
"""
import asyncio
from datetime import datetime, time
from database.backup import create_backup

class BackupScheduler:
    """Programa backups automáticos de la base de datos"""
    
    def __init__(self, backup_interval_hours=6):
        """
        Args:
            backup_interval_hours: Intervalo entre backups en horas (default: 6)
        """
        self.backup_interval_hours = backup_interval_hours
        self.running = False
        self.task = None
    
    async def start(self):
        """Inicia el programador de backups"""
        if self.running:
            return
        
        self.running = True
        self.task = asyncio.create_task(self._backup_loop())
        print(f"✅ Sistema de backups automáticos iniciado (cada {self.backup_interval_hours} horas)")
    
    async def stop(self):
        """Detiene el programador de backups"""
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        print("🛑 Sistema de backups detenido")
    
    async def _backup_loop(self):
        """Loop principal de backups"""
        while self.running:
            try:
                # Crear backup
                create_backup()
                
                # Esperar hasta el siguiente backup
                await asyncio.sleep(self.backup_interval_hours * 3600)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"❌ Error en backup automático: {e}")
                # Esperar 1 hora antes de reintentar en caso de error
                await asyncio.sleep(3600)

