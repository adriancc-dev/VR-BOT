# Logos de Divisiones

Esta carpeta contiene los logos personalizados para cada división del sistema de ranking.

## Estructura de Archivos

Cada logo debe tener el siguiente nombre de archivo (en minúsculas, con guiones bajos):

### Hierro
- `hierro_iii.png` - Hierro III
- `hierro_ii.png` - Hierro II
- `hierro_i.png` - Hierro I

### Bronze
- `bronze_iii.png` - Bronze III
- `bronze_ii.png` - Bronze II
- `bronze_i.png` - Bronze I

### Plata
- `plata_iii.png` - Plata III
- `plata_ii.png` - Plata II
- `plata_i.png` - Plata I

### Oro
- `oro_iii.png` - Oro III
- `oro_ii.png` - Oro II
- `oro_i.png` - Oro I

### Platino
- `platino_iii.png` - Platino III
- `platino_ii.png` - Platino II
- `platino_i.png` - Platino I

### Esmeralda
- `esmeralda_iii.png` - Esmeralda III
- `esmeralda_ii.png` - Esmeralda II
- `esmeralda_i.png` - Esmeralda I

### Diamante
- `diamante_iii.png` - Diamante III
- `diamante_ii.png` - Diamante II
- `diamante_i.png` - Diamante I

### Rangos Especiales
- `promesa.png` - Promesa
- `predator.png` - Predator
- `leyenda.png` - Leyenda

## Cómo Añadir los Logos

1. **Prepara tus imágenes:**
   - Formato recomendado: PNG (con transparencia si es necesario)
   - Tamaño recomendado: 64x64px o 128x128px (cuadrado)
   - Asegúrate de que las imágenes tengan buena calidad

2. **Nombra los archivos correctamente:**
   - Usa exactamente los nombres listados arriba
   - Todo en minúsculas
   - Usa guiones bajos (_) para separar palabras
   - Extensión: `.png`

3. **Coloca los archivos:**
   - Copia todas las imágenes a esta carpeta: `assets/ranks/`
   - Asegúrate de que todos los 24 archivos estén presentes

4. **Verifica:**
   - El bot usará automáticamente estos logos cuando estén disponibles
   - Si falta un logo, se usará un emoji por defecto

## Uso en el Código

Los logos se pueden usar de dos formas:

### 1. Archivos Locales (recomendado)
```python
from utils.elo import get_rank_logo_path

rank = "Oro III"
logo_path = get_rank_logo_path(rank)
if logo_path:
    # Usar el logo (ej: en un embed de Discord)
    file = discord.File(logo_path, filename="rank.png")
```

### 2. URLs (si los logos están en un servidor web)
```python
from utils.elo import get_rank_logo_url

rank = "Oro III"
logo_url = get_rank_logo_url(rank)
if logo_url:
    # Usar la URL del logo
    embed.set_thumbnail(url=logo_url)
```

## Notas

- Si un logo no existe, la función retornará `None`
- El bot seguirá funcionando sin los logos (usará emojis por defecto)
- Puedes añadir los logos gradualmente, no es necesario tenerlos todos de una vez

