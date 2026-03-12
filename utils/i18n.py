"""
Sistema de traducción multiidioma para el bot
Soporta: Español (es), Inglés (en), Francés (fr), Italiano (it)
"""
import json
import os
from typing import Optional, Dict, Any

class Translator:
    """Clase para manejar traducciones multiidioma"""
    
    def __init__(self, language: str = 'es'):
        """
        Inicializa el traductor con un idioma específico
        
        Args:
            language: Código de idioma ('es', 'en', 'fr', 'it')
        """
        self.language = language if language in ['es', 'en', 'fr', 'it'] else 'es'
        self.translations = self._load_translations()
    
    def _load_translations(self) -> Dict[str, Any]:
        """Carga las traducciones desde el archivo JSON correspondiente"""
        locales_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'locales')
        file_path = os.path.join(locales_dir, f'{self.language}.json')
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            # Si no existe el archivo, cargar español como fallback
            if self.language != 'es':
                fallback_path = os.path.join(locales_dir, 'es.json')
                try:
                    with open(fallback_path, 'r', encoding='utf-8') as f:
                        return json.load(f)
                except FileNotFoundError:
                    return {}
            return {}
        except Exception as e:
            print(f"❌ Error cargando traducciones: {e}")
            return {}
    
    def t(self, key: str, **kwargs) -> str:
        """
        Traduce una clave con parámetros opcionales
        
        Args:
            key: Clave de traducción (ej: 'match.accepted.title')
            **kwargs: Parámetros para formatear el string
        
        Returns:
            String traducido o la clave si no se encuentra
        """
        keys = key.split('.')
        value = self.translations
        
        # Navegar por el diccionario anidado
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                # Si no se encuentra, devolver la clave original
                return key
        
        # Si el valor es un string, formatearlo con kwargs si existen
        if isinstance(value, str):
            try:
                return value.format(**kwargs) if kwargs else value
            except KeyError:
                # Si faltan parámetros, devolver el string sin formatear
                return value
        
        return str(value) if value is not None else key
    
    def get_language_name(self) -> str:
        """Retorna el nombre del idioma actual"""
        names = {
            'es': 'Español',
            'en': 'English',
            'fr': 'Français',
            'it': 'Italiano'
        }
        return names.get(self.language, 'Español')

def get_translator(language: Optional[str] = None) -> Translator:
    """
    Función helper para obtener un traductor
    
    Args:
        language: Código de idioma ('es', 'en', 'fr', 'it'). Si es None, usa 'es'
    
    Returns:
        Instancia de Translator
    """
    return Translator(language or 'es')

def get_player_translator(player) -> Translator:
    """
    Obtiene el traductor basado en el idioma del jugador
    
    Args:
        player: Instancia de Player con atributo language
    
    Returns:
        Instancia de Translator con el idioma del jugador
    """
    language = getattr(player, 'language', None) or 'es'
    return Translator(language)

def translate_rank(rank: str, language: str = 'es') -> str:
    """
    Traduce el nombre de un rango al idioma especificado
    
    Args:
        rank: Nombre del rango en español (ej: "Hierro III", "Promesa")
        language: Código de idioma ('es', 'en', 'fr', 'it')
    
    Returns:
        Nombre del rango traducido
    """
    # Si ya está en el idioma correcto, devolverlo
    if language == 'es':
        return rank
    
    translator = Translator(language)
    # Normalizar el nombre del rango para la clave (ej: "Hierro III" -> "hierro_iii")
    rank_normalized = rank.lower().replace(' ', '_')
    rank_key = f"ranks.names.{rank_normalized}"
    translated = translator.t(rank_key)
    
    # Si no se encuentra la traducción, devolver el original
    if translated == rank_key:
        return rank
    
    return translated

