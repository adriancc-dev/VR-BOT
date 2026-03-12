#!/usr/bin/env python3
"""
Script para verificar si hay múltiples instancias del bot corriendo
"""
import subprocess
import sys
import os

def check_bot_processes():
    """Verifica cuántas instancias de bot.py están corriendo"""
    try:
        # Buscar procesos de bot.py
        result = subprocess.run(
            ['ps', 'aux'],
            capture_output=True,
            text=True
        )
        
        bot_processes = []
        for line in result.stdout.split('\n'):
            if 'bot.py' in line and 'grep' not in line:
                bot_processes.append(line)
        
        return bot_processes
    except Exception as e:
        print(f"❌ Error al verificar procesos: {e}")
        return []

def check_python_processes():
    """Verifica todos los procesos de Python"""
    try:
        result = subprocess.run(
            ['ps', 'aux'],
            capture_output=True,
            text=True
        )
        
        python_processes = []
        for line in result.stdout.split('\n'):
            if 'python' in line.lower() and 'grep' not in line:
                python_processes.append(line)
        
        return python_processes
    except Exception as e:
        print(f"❌ Error al verificar procesos Python: {e}")
        return []

def main():
    print("=" * 70)
    print("🔍 VERIFICACIÓN DE INSTANCIAS DEL BOT")
    print("=" * 70)
    print()
    
    # Verificar procesos de bot.py
    bot_processes = check_bot_processes()
    
    print(f"📊 Instancias de bot.py encontradas: {len(bot_processes)}")
    print()
    
    if len(bot_processes) == 0:
        print("✅ No hay instancias de bot.py corriendo")
    elif len(bot_processes) == 1:
        print("✅ Hay 1 instancia de bot.py corriendo (normal)")
        print()
        print("Proceso:")
        for proc in bot_processes:
            print(f"  {proc}")
    else:
        print(f"⚠️  ADVERTENCIA: Hay {len(bot_processes)} instancias de bot.py corriendo")
        print("   Esto puede causar problemas:")
        print("   • Múltiples respuestas a comandos")
        print("   • Conflictos en la base de datos")
        print("   • Errores de 'Unknown interaction'")
        print()
        print("Procesos encontrados:")
        for i, proc in enumerate(bot_processes, 1):
            print(f"  {i}. {proc}")
        print()
        print("💡 SOLUCIÓN:")
        print("   1. Detén todas las instancias:")
        print("      pkill -f bot.py")
        print("   2. O detén manualmente cada proceso:")
        for proc in bot_processes:
            # Extraer PID
            parts = proc.split()
            if len(parts) > 1:
                pid = parts[1]
                print(f"      kill {pid}")
    
    print()
    print("=" * 70)
    print()
    
    # Verificar todos los procesos de Python
    python_processes = check_python_processes()
    print(f"📊 Total de procesos Python encontrados: {len(python_processes)}")
    
    if len(python_processes) > 0:
        print()
        print("Procesos Python activos:")
        for proc in python_processes[:10]:  # Mostrar solo los primeros 10
            print(f"  {proc}")
        if len(python_processes) > 10:
            print(f"  ... y {len(python_processes) - 10} más")
    
    print()
    print("=" * 70)

if __name__ == "__main__":
    main()

