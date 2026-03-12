#!/usr/bin/env python3
"""
Script para configurar la URL de la imagen del estadio
"""
import os
from pathlib import Path

def configurar_imagen_estadio():
    """Configura la URL de la imagen del estadio en el archivo .env"""
    env_path = Path('.env')
    
    print("=" * 60)
    print("⚽ CONFIGURAR IMAGEN DE ESTADIO")
    print("=" * 60)
    print()
    
    # Leer .env si existe
    env_vars = {}
    if env_path.exists():
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    env_vars[key.strip()] = value.strip()
    
    # Mostrar URL actual si existe
    url_actual = env_vars.get('STADIUM_IMAGE_URL', '')
    if url_actual:
        print(f"URL actual: {url_actual}")
        print()
        respuesta = input("¿Quieres cambiar la URL? (s/n): ").lower()
        if respuesta != 's':
            print("✅ Manteniendo la URL actual.")
            return
    else:
        print("No hay URL configurada actualmente.")
        print()
    
    # Solicitar nueva URL
    print("Ingresa la URL de la imagen del estadio:")
    print("(Debe ser una URL pública, ej: https://i.imgur.com/abc123.png)")
    print()
    nueva_url = input("URL: ").strip()
    
    if not nueva_url:
        print("❌ No se ingresó ninguna URL.")
        return
    
    # Validar que sea una URL válida
    if not nueva_url.startswith(('http://', 'https://')):
        print("❌ La URL debe comenzar con http:// o https://")
        return
    
    # Actualizar o agregar la variable
    env_vars['STADIUM_IMAGE_URL'] = nueva_url
    
    # Escribir .env
    lines = []
    if env_path.exists():
        with open(env_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    
    # Buscar si ya existe STADIUM_IMAGE_URL
    encontrado = False
    nuevas_lineas = []
    for line in lines:
        if line.strip().startswith('STADIUM_IMAGE_URL='):
            nuevas_lineas.append(f"STADIUM_IMAGE_URL={nueva_url}\n")
            encontrado = True
        else:
            nuevas_lineas.append(line)
    
    # Si no existe, agregarlo al final
    if not encontrado:
        nuevas_lineas.append(f"\n# Imagen de estadio para resultados de partidas\n")
        nuevas_lineas.append(f"STADIUM_IMAGE_URL={nueva_url}\n")
    
    # Escribir archivo
    with open(env_path, 'w', encoding='utf-8') as f:
        f.writelines(nuevas_lineas)
    
    print()
    print("✅ URL configurada correctamente!")
    print(f"   {nueva_url}")
    print()
    print("📝 Próximos pasos:")
    print("   1. Reinicia el bot para aplicar los cambios")
    print("   2. La imagen aparecerá en los resultados confirmados")

if __name__ == '__main__':
    try:
        configurar_imagen_estadio()
    except KeyboardInterrupt:
        print("\n\n❌ Operación cancelada.")
    except Exception as e:
        print(f"\n❌ Error: {e}")

