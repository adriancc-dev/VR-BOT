"""
Utilidades para generar imágenes con texto superpuesto
"""
import io
import requests
from PIL import Image, ImageDraw, ImageFont
from typing import Optional
import os
import tempfile
import logging

# configurar logger
logger = logging.getLogger(__name__)

def generate_stadium_image_with_score(
    stadium_image_url: str, 
    score1: int, 
    score2: int,
    player1_avatar_url: Optional[str] = None,
    player2_avatar_url: Optional[str] = None,
    player1_name: Optional[str] = None,
    player2_name: Optional[str] = None,
    elo_change1: float = 0,
    elo_change2: float = 0,
    xp_gained1: int = 0,
    xp_gained2: int = 0,
    player1_elo: float = 0,
    player2_elo: float = 0
) -> Optional[io.BytesIO]:
    """
    Genera una imagen del estadio con el marcador, fotos de perfil, nombres y estadísticas
    
    Args:
        stadium_image_url: URL de la imagen del estadio
        score1: Puntuación del jugador 1
        score2: Puntuación del jugador 2
        player1_avatar_url: URL del avatar del jugador 1 (opcional)
        player2_avatar_url: URL del avatar del jugador 2 (opcional)
        player1_name: Nombre del jugador 1 (opcional)
        player2_name: Nombre del jugador 2 (opcional)
        elo_change1: Cambio de ELO del jugador 1
        elo_change2: Cambio de ELO del jugador 2
        xp_gained1: XP ganada por el jugador 1
        xp_gained2: XP ganada por el jugador 2
        player1_elo: ELO actual del jugador 1
        player2_elo: ELO actual del jugador 2
    
    Returns:
        BytesIO object con la imagen generada, o None si hay error
    """
    try:
        # descargar la imagen del estadio con headers para evitar rate limiting
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Cache-Control': 'no-cache'
        }
        if 'imgur.com' in stadium_image_url:
            headers['Referer'] = 'https://imgur.com/'
        
        # solo loguear en modo debug para evitar spam en logs
        logger.debug(f"📥 Descargando imagen del estadio desde: {stadium_image_url}")
        response = requests.get(stadium_image_url, timeout=5, headers=headers)  # Timeout más corto
        if response.status_code != 200:
            # solo loguear errores 404 una vez cada cierto tiempo o en modo debug
            if response.status_code == 404:
                logger.debug(f"⚠️ Imagen no encontrada (404). URL puede haber expirado: {stadium_image_url[:50]}...")
            else:
                logger.debug(f"⚠️ Error descargando imagen. Status code: {response.status_code}")
            
            # si es rate limiting, intentar solo una vez con delay corto
            if response.status_code == 429:
                import time
                logger.debug("⚠️ Rate limit detectado, esperando 2 segundos antes de reintentar...")
                time.sleep(2)
                response = requests.get(stadium_image_url, timeout=5, headers=headers)
                if response.status_code != 200:
                    logger.debug(f"⚠️ Rate limit persistente. Status code: {response.status_code}")
                    return None
            elif response.status_code != 404:
                # para otros errores (no 404), intentar una vez más rápidamente
                import time
                time.sleep(1)
                response = requests.get(stadium_image_url, timeout=5, headers=headers)
                if response.status_code != 200:
                    logger.debug(f"⚠️ Error persistente. Status code: {response.status_code}")
                    return None
            else:
                # para 404, no reintentar
                return None
        
        # abrir la imagen
        stadium_img = Image.open(io.BytesIO(response.content))
        
        # Convertir a RGB si es necesario (para PNG con transparencia)
        if stadium_img.mode in ('RGBA', 'LA', 'P'):
            # Crear fondo negro para imágenes con transparencia
            background = Image.new('RGB', stadium_img.size, (0, 0, 0))
            if stadium_img.mode == 'P':
                stadium_img = stadium_img.convert('RGBA')
            if stadium_img.mode == 'RGBA':
                background.paste(stadium_img, mask=stadium_img.split()[-1])
            else:
                background.paste(stadium_img)
            stadium_img = background
        else:
            stadium_img = stadium_img.convert('RGB')
        
        # Crear un objeto Draw para dibujar sobre la imagen
        draw = ImageDraw.Draw(stadium_img)
        
        # Obtener dimensiones de la imagen
        width, height = stadium_img.size
        
        # Importar función para obtener rango
        from utils.elo import get_rank_from_elo
        
        # Escalar overlay para que siempre quepa en la imagen (diseño base: ~1800x700)
        ref_width = 2000
        ref_height_block = 800
        scale_w = width / ref_width if width < ref_width else 1.0
        scale_h = height / ref_height_block if height < ref_height_block else 1.0
        base_scale = min(scale_w, scale_h, 1.0)
        # Avatares y marcador más grandes; multiplicador para que no se salgan
        avatar_score_mult = 0.72
        scale = base_scale * avatar_score_mult
        
        # Tamaño de las fotos de perfil (cuadradas) - más grandes
        avatar_size = max(80, int(680 * scale))
        
        # Espaciado entre elementos
        spacing = max(14, int(40 * scale), int(width * 0.018))
        
        # Espaciado vertical
        vertical_spacing = max(15, int(30 * scale), int(height * 0.025))
        
        # Texto del marcador - más grande
        score_text = f"{score1} - {score2}"
        score_font_size = max(28, int(300 * scale))
        
        # Intentar cargar fuente elegante y gruesa para score (bold pero elegante)
        score_font = None
        # Priorizar fuentes bold y elegantes (Bold, Medium, pero elegantes)
        bold_elegant_font_paths = [
            # macOS - Fuentes bold elegantes
            "/System/Library/Fonts/Supplemental/HelveticaNeue-Bold.otf",
            "/System/Library/Fonts/Supplemental/HelveticaNeue-Medium.otf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/System/Library/Fonts/Supplemental/Helvetica-Bold.ttf",
            "/System/Library/Fonts/Supplemental/HelveticaNeue.ttc",  # Puede contener Bold
            "/System/Library/Fonts/Helvetica.ttc",
            # Linux - Fuentes bold
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            # Fallback a fuentes normales si no hay Bold
            "/System/Library/Fonts/Supplemental/Helvetica.ttc",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
        
        for font_path in bold_elegant_font_paths:
            try:
                if os.path.exists(font_path):
                    # Intentar cargar la fuente
                    score_font = ImageFont.truetype(font_path, score_font_size)
                    break
            except Exception as e:
                # Si es un archivo .ttc, intentar cargar con índice específico
                if font_path.endswith('.ttc'):
                    try:
                        score_font = ImageFont.truetype(font_path, score_font_size, index=0)
                        break
                    except:
                        continue
                continue
        
        if score_font is None:
            score_font = ImageFont.load_default()
            logger.warning("⚠️ Usando fuente por defecto para score (no se encontraron fuentes del sistema)")
        
        # Obtener tamaño del score
        try:
            if hasattr(draw, 'textbbox'):
                score_bbox = draw.textbbox((0, 0), score_text, font=score_font)
                score_width = score_bbox[2] - score_bbox[0]
                score_height = score_bbox[3] - score_bbox[1]
            else:
                score_width, score_height = draw.textsize(score_text, font=score_font)
        except:
            score_width = len(score_text) * int(score_font_size * 0.6)
            score_height = int(score_font_size * 1.2)
        
        # Calcular ancho total: foto1 + espacio + score + espacio + foto2
        total_width = avatar_size + spacing + score_width + spacing + avatar_size
        
        # Calcular posición central del conjunto completo
        center_x = width // 2
        start_x = center_x - (total_width // 2)
        
        # Centrar el bloque (avatares + marcador) verticalmente en la imagen
        block_height = avatar_size + 4  # avatar + borde 2px cada lado
        top_margin = max(20, (height // 2) - (block_height // 2))
        
        avatar1_x = start_x
        avatar1_y = top_margin
        
        score_x = avatar1_x + avatar_size + spacing
        score_y = top_margin + (avatar_size - score_height) // 2  # Centrado verticalmente con las fotos
        
        avatar2_x = score_x + score_width + spacing
        avatar2_y = top_margin
        
        # Descargar y colocar avatares si están disponibles
        avatar1_img = None
        avatar2_img = None
        
        # Descargar y procesar avatares (cuadrados con borde dorado)
        border_width = 2  # Grosor del borde
        border_color = (210, 130, 45, 255)  # Dorado oscuro tirando a naranja
        
        if player1_avatar_url:
            try:
                avatar_response = requests.get(player1_avatar_url, timeout=10, headers=headers)
                if avatar_response.status_code == 200:
                    avatar1_img = Image.open(io.BytesIO(avatar_response.content))
                    if avatar1_img.mode != 'RGBA':
                        avatar1_img = avatar1_img.convert('RGBA')
                    # Redimensionar a cuadrado
                    avatar1_img = avatar1_img.resize((avatar_size, avatar_size), Image.Resampling.LANCZOS)
                    
                    # Crear imagen con borde dorado
                    avatar1_with_border = Image.new('RGBA', (avatar_size + border_width * 2, avatar_size + border_width * 2), border_color)
                    avatar1_with_border.paste(avatar1_img, (border_width, border_width), avatar1_img)
                    avatar1_img = avatar1_with_border
            except Exception as e:
                logger.warning(f"⚠️ No se pudo cargar avatar jugador 1: {e}")
        
        if player2_avatar_url:
            try:
                avatar_response = requests.get(player2_avatar_url, timeout=10, headers=headers)
                if avatar_response.status_code == 200:
                    avatar2_img = Image.open(io.BytesIO(avatar_response.content))
                    if avatar2_img.mode != 'RGBA':
                        avatar2_img = avatar2_img.convert('RGBA')
                    # Redimensionar a cuadrado
                    avatar2_img = avatar2_img.resize((avatar_size, avatar_size), Image.Resampling.LANCZOS)
                    
                    # Crear imagen con borde dorado
                    avatar2_with_border = Image.new('RGBA', (avatar_size + border_width * 2, avatar_size + border_width * 2), border_color)
                    avatar2_with_border.paste(avatar2_img, (border_width, border_width), avatar2_img)
                    avatar2_img = avatar2_with_border
            except Exception as e:
                logger.warning(f"⚠️ No se pudo cargar avatar jugador 2: {e}")
        
        # Ajustar posiciones para tener en cuenta el borde
        avatar1_x_adjusted = avatar1_x - border_width
        avatar1_y_adjusted = avatar1_y - border_width
        avatar2_x_adjusted = avatar2_x - border_width
        avatar2_y_adjusted = avatar2_y - border_width
        
        # Pegar avatares cuadrados con borde
        if avatar1_img:
            stadium_img.paste(avatar1_img, (avatar1_x_adjusted, avatar1_y_adjusted), avatar1_img)
        
        if avatar2_img:
            stadium_img.paste(avatar2_img, (avatar2_x_adjusted, avatar2_y_adjusted), avatar2_img)
        
        # Dibujar score con efecto elegante (borde dorado y números gruesos)
        score_border_width = max(3, int(score_font_size * 0.05))
        border_color_gold = (210, 130, 45)  # Dorado oscuro tirando a naranja
        
        # Dibujar borde dorado (múltiples capas para hacer los números más gruesos)
        for adj_x in range(-score_border_width, score_border_width + 1):
            for adj_y in range(-score_border_width, score_border_width + 1):
                if adj_x != 0 or adj_y != 0:
                    try:
                        draw.text((score_x + adj_x, score_y + adj_y), score_text, fill=border_color_gold, font=score_font)
                    except:
                        pass
        
        # Dibujar capa blanca de fondo para mejor contraste
        for i in range(1):
            draw.text((score_x, score_y), score_text, fill=(255, 255, 255), font=score_font)
        
        # Dibujar texto final en blanco brillante (números más gruesos)
        draw.text((score_x, score_y), score_text, fill=(255, 255, 255), font=score_font)
        
        # Nombres DENTRO de las fotos de perfil (esquina inferior) - mucho más pequeños
        name_font_size = min(18, max(11, int(avatar_size * 0.032)))  # Un poco más grandes
        name_font = None
        # Fuentes bold elegantes para nombres (bold con outline)
        bold_elegant_font_paths = [
            # macOS - Fuentes bold elegantes
            "/System/Library/Fonts/Supplemental/HelveticaNeue-Bold.otf",
            "/System/Library/Fonts/Supplemental/HelveticaNeue-Medium.otf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/System/Library/Fonts/Supplemental/Helvetica-Bold.ttf",
            "/System/Library/Fonts/Supplemental/HelveticaNeue.ttc",  # Puede contener Bold
            "/System/Library/Fonts/Helvetica.ttc",
            # Linux - Fuentes bold
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ]
        
        for font_path in bold_elegant_font_paths:
            try:
                if os.path.exists(font_path):
                    name_font = ImageFont.truetype(font_path, name_font_size)
                    break
            except Exception as e:
                # Si es un archivo .ttc, intentar cargar con índice específico
                if font_path.endswith('.ttc'):
                    try:
                        name_font = ImageFont.truetype(font_path, name_font_size, index=0)
                        break
                    except:
                        continue
                continue
        
        if name_font is None:
            name_font = ImageFont.load_default()
            logger.warning("⚠️ Usando fuente por defecto para nombres (no se encontraron fuentes del sistema)")
        
        # Dibujar nombres DENTRO de las fotos de perfil (esquinas inferiores)
        if player1_name and player2_name:
            try:
                name_padding = int(avatar_size * 0.04)  # Padding desde el borde de la foto
                # Truncar nombres muy largos para que quepan dentro del avatar
                max_name_len = 10
                name1_text = (player1_name.upper()[:max_name_len] + "…") if len(player1_name) > max_name_len else player1_name.upper()
                name2_text = (player2_name.upper()[:max_name_len] + "…") if len(player2_name) > max_name_len else player2_name.upper()

                # Nombre 1: esquina inferior izquierda dentro del avatar
                if hasattr(draw, 'textbbox'):
                    name1_bbox = draw.textbbox((0, 0), name1_text, font=name_font)
                    name1_height = name1_bbox[3] - name1_bbox[1]
                else:
                    _, name1_height = draw.textsize(name1_text, font=name_font)
                name1_x = avatar1_x_adjusted + name_padding
                name1_y = avatar1_y_adjusted + avatar_size + (border_width * 2) - name1_height - name_padding

                # Nombre 2: esquina inferior derecha dentro del avatar
                if hasattr(draw, 'textbbox'):
                    name2_bbox = draw.textbbox((0, 0), name2_text, font=name_font)
                    name2_width = name2_bbox[2] - name2_bbox[0]
                    name2_height = name2_bbox[3] - name2_bbox[1]
                else:
                    name2_width, name2_height = draw.textsize(name2_text, font=name_font)
                name2_x = avatar2_x_adjusted + avatar_size + (border_width * 2) - name2_width - name_padding
                name2_y = avatar2_y_adjusted + avatar_size + (border_width * 2) - name2_height - name_padding

                border_name = max(2, int(name_font_size * 0.08))
                name_border_color = (210, 130, 45)  # Dorado oscuro tirando a naranja
                # Nombre 1: borde dorado + texto blanco
                for adj_x in range(-border_name, border_name + 1):
                    for adj_y in range(-border_name, border_name + 1):
                        if adj_x != 0 or adj_y != 0:
                            draw.text((name1_x + adj_x, name1_y + adj_y), name1_text, fill=name_border_color, font=name_font)
                draw.text((name1_x, name1_y), name1_text, fill=(255, 255, 255), font=name_font)

                # Nombre 2: borde dorado + texto blanco
                for adj_x in range(-border_name, border_name + 1):
                    for adj_y in range(-border_name, border_name + 1):
                        if adj_x != 0 or adj_y != 0:
                            draw.text((name2_x + adj_x, name2_y + adj_y), name2_text, fill=name_border_color, font=name_font)
                draw.text((name2_x, name2_y), name2_text, fill=(255, 255, 255), font=name_font)
            except Exception as e:
                logger.warning(f"⚠️ Error al dibujar nombres: {e}")
        
        # No mostrar estadísticas en la imagen (ya están en el embed arriba)
        
        # Guardar la imagen en un BytesIO
        img_bytes = io.BytesIO()
        stadium_img.save(img_bytes, format='PNG')
        img_bytes.seek(0)
        
        logger.info("✅ Imagen generada correctamente")
        return img_bytes
    
    except Exception as e:
        import traceback
        logger.error(f"❌ Error al generar imagen: {e}")
        logger.error(traceback.format_exc())
        return None
