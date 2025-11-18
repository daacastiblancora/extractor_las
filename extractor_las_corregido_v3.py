# ==================================================================================================
# SCRIPT DE EXTRACCIÓN DE METADATOS DE ARCHIVOS DE REGISTROS DE POZOS (LAS, LIS, DLIS)
# Versión Corregida - Manejo apropiado de cada formato
# ==================================================================================================

from __future__ import annotations
import os, sys, json, re, hashlib, logging, shutil, signal
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from threading import Event
from collections import Counter
import struct

# --- Configuración de Logging ---
log_formatter = logging.Formatter("%(asctime)s - %(levelname)s: %(message)s")
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Log a archivo - SOLO ERRORES Y WARNINGS
file_handler = logging.FileHandler("pipeline_las_informacion_QC_1.log", mode='a', encoding='utf-8')
file_handler.setFormatter(log_formatter)
file_handler.setLevel(logging.WARNING)  # Solo guardar WARNING y ERROR en archivo
logger.addHandler(file_handler)

# Log a consola - Configurado para UTF-8
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
console_handler.setLevel(logging.INFO)  # Mostrar INFO, WARNING y ERROR en consola
# Configurar encoding UTF-8 para la consola
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
logger.addHandler(console_handler)

# --- Verificación de Dependencias ---
try:
    import pandas as pd
except ImportError:
    pd = None
    logging.warning("Librería 'pandas' no instalada. El reporteo a CSV/XLSX estará desactivado.")

try:
    import lasio
    # Suprimir warnings excesivos de lasio
    import warnings
    warnings.filterwarnings('ignore', module='lasio')
    warnings.filterwarnings('ignore', message='.*wrapped files.*')
    warnings.filterwarnings('ignore', message='.*HeaderItem.*')
    # Suprimir warnings de dlisio también
    warnings.filterwarnings('ignore', category=UserWarning)
except ImportError:
    lasio = None
    logging.error("Librería 'lasio' no instalada. La extracción de archivos .las no será posible.")

try:
    import dlisio
except ImportError:
    dlisio = None
    logging.warning("Librería 'dlisio' no instalada. La extracción de archivos .dlis/.lis será limitada.")

# --- Manejo de Señales para Parada Segura ---
stop_event = Event()
def _signal_handler(signum, frame):
    logging.warning(f"Señal ({signum}) recibida. Finalizando de forma ordenada...")
    stop_event.set()
signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)

# --- Configuración de Rutas ---
# --- Configuración de Rutas ---
INPUT_DIR = r"C:\temp\ANH_OCR\1_INFORMACION_QC 1.txt" # Directorio con archivos
OUT_DIR = r"C:\temp\ANH_OCR\salida_las_INFORMACION_QC 1.txt"  # Directorio de salida
STATE_FILE = r"C:\temp\ANH_OCR\last_processed_informacion_QC_1.txt"
UNPROCESSED_STATE_FILE = r"C:\temp\ANH_OCR\unprocessed_file_infomracion_QC_1.txt"
BASE_EXTENSIONS = [".las", ".lis", ".dlis", ".dlas"] # Extensiones base para la detección
ENCODINGS_TO_TRY = ["utf-8", "latin-1", "cp1252", "ascii"] # Codificaciones a intentar

# --- Mapeo de Mnemónicos (Alias) ---
FIELD_ALIASES = {
    "COMPANY": ["COMP", "COMPANY", "CMPY"],
    "WELL": ["WELL", "WELL NAME", "WELLNAME"],
    "FIELD": ["FLD", "FIELD"],
    "PROVINCE": ["PROV", "PROVINCE", "STATE", "STAT"],
    "COUNTRY": ["CTRY", "COUNTRY"],
    "LOCATION": ["LOC", "LOCATION"],
    "SERVICE_COMPANY": ["SRVC", "SERVICE COMPANY"],
    "DATE": ["DATE", "LOG DATE", "DAT"],
    "UWI": ["UWI", "API", "UNIQUE WELL ID"],
    "LATITUDE": ["LATI", "LAT", "LATITUDE"],
    "LONGITUDE": ["LONG", "LON", "LONGITUDE"],
    "START_MD": ["STRT", "START DEPTH", "START"],
    "STOP_MD": ["STOP", "STOP DEPTH"],
    "STEP": ["STEP", "INCREMENT", "INC"],
    "NULL_VALUE": ["NULL", "NULL VALUE"],
}

# =========================
# Utilidades
# =========================
def safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    """Safely converts a value to a float, returning a default if not possible."""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default

def append_to_unprocessed_log(file_path: Path):
    """Appends a file path to the unprocessed files log."""
    try:
        unprocessed_log_path = Path(UNPROCESSED_STATE_FILE)
        unprocessed_log_path.parent.mkdir(parents=True, exist_ok=True)
        with unprocessed_log_path.open("a", encoding="utf-8") as f:
            f.write(str(file_path.resolve()) + "\n")
    except Exception as e:
        logging.error(f"No se pudo escribir en el log de no procesados '{UNPROCESSED_STATE_FILE}': {e}")
def safe_str(s: Any, max_length: int = 200) -> str:
    """
    Convierte cualquier valor a string seguro para logging,
    eliminando caracteres no imprimibles y limitando longitud.
    """
    try:
        if s is None:
            return ""

        # Convertir a string
        text = str(s)

        # Filtrar solo caracteres imprimibles y espacios
        text = ''.join(c for c in text if c.isprintable() or c in '\n\r\t ')

        # Limitar longitud
        if len(text) > max_length:
            text = text[:max_length] + "..."

        return text
    except Exception:
        return "<unprintable>"

def ensure_dir(p: Path):
    if not p.exists():
        p.mkdir(parents=True, exist_ok=True)

def write_json_atomic(path: Path, obj: Any):
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        with tmp_path.open("w", encoding="utf-8", errors='replace') as f:
            json.dump(obj, f, ensure_ascii=False, indent=2, default=str)
        shutil.move(tmp_path, path)
    except Exception as e:
        logging.error(f"Error al escribir JSON en {safe_str(path.name)}: {safe_str(str(e))}")
        if tmp_path.exists():
            tmp_path.unlink()

def get_header_value(well_info: Dict, canonical_name: str, default: Any = "") -> Tuple[Any, str]:
    """Busca un valor en el encabezado usando una lista de alias."""
    aliases = FIELD_ALIASES.get(canonical_name.upper(), [canonical_name])
    for alias in aliases:
        if alias in well_info:
            item = well_info[alias]
            return item.get("value", default), item.get("unit", "")
    return default, ""

def is_corrupted_or_wrong_format(path: Path) -> bool:
    """
    Detecta si un archivo tiene un formato completamente incorrecto
    (como Excel con extensión .las, archivos corruptos, etc.)
    """
    try:
        with path.open('rb') as f:
            header = f.read(512)

            # Detectar archivos Microsoft Office (Excel, Word, etc.) con extensión incorrecta
            # Firma: D0 CF 11 E0 (Microsoft Compound File Binary)
            if header.startswith(b'\xD0\xCF\x11\xE0'):
                logging.error(f"Archivo '{safe_str(path.name)}' es un archivo Microsoft Office (Excel/Word) con extensión incorrecta")
                return True

            # Detectar archivos ZIP (que a veces se renombran incorrectamente)
            if header.startswith(b'PK\x03\x04') or header.startswith(b'PK\x05\x06'):
                logging.error(f"Archivo '{safe_str(path.name)}' es un archivo ZIP con extensión incorrecta")
                return True

            # Detectar archivos PDF
            if header.startswith(b'%PDF'):
                logging.error(f"Archivo '{safe_str(path.name)}' es un archivo PDF con extensión incorrecta")
                return True

            # Detectar archivos completamente binarios (>90% bytes no imprimibles)
            if len(header) > 100:
                printable_count = sum(1 for b in header[:100] if 32 <= b <= 126 or b in (9, 10, 13))
                if printable_count < 10:  # Menos del 10% imprimible
                    logging.error(f"Archivo '{safe_str(path.name)}' parece ser completamente binario o corrupto")
                    return True

    except Exception as e:
        logging.error(f"Error verificando formato de archivo '{safe_str(path.name)}': {safe_str(str(e))}")
        return True

    return False

def detect_file_format(path: Path) -> str:
    """
    Detecta el formato real del archivo basándose en su contenido, no solo en la extensión.
    Retorna: 'las', 'dlis', 'lis', 'unknown'

    NUEVO ORDEN DE PRIORIDAD (arreglado):
    1. Verificar archivos corruptos/incorrectos
    2. Detectar LAS por extensión + contenido texto
    3. Leer header binario
    4. PRIMERO: Verificar firmas DLIS (antes que extensión)
    5. SEGUNDO: Verificar estructura LIS
    6. ÚLTIMO: Usar extensión como fallback
    """
    try:
        # Primero verificar si es un archivo con formato completamente incorrecto
        if is_corrupted_or_wrong_format(path):
            return 'unknown'

        file_ext_lower = path.suffix.lower()

        # --- Prioridad 1: Detección de LAS basada en extensión y contenido de texto ---
        # Si la extensión sugiere que es un LAS, intentamos leerlo como texto primero.
        # Esto evita falsos positivos donde el contenido binario de un LAS se confunde con DLIS.
        if file_ext_lower.startswith('.las') or file_ext_lower.startswith('.dlas'):
            for encoding in ENCODINGS_TO_TRY:
                try:
                    with path.open("r", encoding=encoding, errors='ignore') as f:
                        # Un archivo LAS válido debe tener secciones ~V y ~W al principio.
                        content_start = f.read(2048)
                        if re.search(r'^\s*~V.*\n\s*~W', content_start, re.IGNORECASE | re.DOTALL):
                            logging.info(f"'{path.name}' detectado como formato LAS (extensión y contenido de texto verificados).")
                            return 'las'
                except (UnicodeDecodeError, PermissionError):
                    continue

        # --- Prioridad 2: Leer header binario para detectar DLIS/LIS ---
        with path.open("rb") as f:
            header = f.read(512)

            # --- CRÍTICO: Verificar DLIS PRIMERO (antes de considerar extensión) ---
            # Esto evita que archivos DLIS con extensión .lis sean mal detectados
            if len(header) >= 80:
                # Buscar patrones típicos de DLIS
                sul_patterns = [
                    b'\x00\x00\x00\x01',  # Sequence number común
                    b'   1',  # Sequence number en texto
                    b'V1.00',  # DLIS Version
                    b'V2.00',  # DLIS Version
                ]

                # Verificar patrones en el SUL
                for pattern in sul_patterns:
                    if pattern in header[:80]:
                        if file_ext_lower.startswith('.lis'):
                            logging.warning(f"'{path.name}' tiene extensión .lis pero es formato DLIS (extensión incorrecta)")
                        else:
                            logging.info(f"'{path.name}' detectado como formato DLIS (patrón SUL encontrado)")
                        return 'dlis'

                # Buscar palabras clave DLIS más adelante en el header
                dlis_keywords = [b'RECORD', b'FILE-HEADER', b'ORIGIN', b'CHANNEL', b'FRAME', b'EFLR', b'IFLR']
                for keyword in dlis_keywords:
                    if keyword in header:
                        if file_ext_lower.startswith('.lis'):
                            logging.warning(f"'{path.name}' tiene extensión .lis pero es formato DLIS (keyword: {keyword.decode('ascii', errors='ignore')})")
                        else:
                            logging.info(f"'{path.name}' detectado como formato DLIS (palabra clave: {keyword})")
                        return 'dlis'

            # --- AHORA SÍ: Verificar LIS (después de descartar DLIS) ---
            if len(header) >= 4:
                try:
                    # Intentar detectar estructura LIS
                    # Physical Record Header: Length(2 bytes) + Attributes(1 byte) + Type(1 byte)
                    prh_length = struct.unpack('>H', header[0:2])[0]
                    prh_attributes = header[2]
                    prh_type = header[3]

                    # Los archivos LIS típicamente tienen longitudes de registro razonables (< 32KB)
                    # y tipos de registro específicos
                    if 4 <= prh_length <= 32768 and prh_type in range(0, 128):
                        # Verificar si hay patrones LIS típicos
                        if b'\x00\x00' in header[4:20] or b'\xFF' in header[4:20]:
                            logging.info(f"'{path.name}' detectado como formato LIS (estructura PRH válida)")
                            return 'lis'
                except Exception:
                    pass # Si falla el unpack, no es LIS

                # Patrones adicionales para LIS
                lis_markers = [b'\x00\x00', b'\xFF\x00', b'\xFF\x01', b'\x01\x00']
                if any(header.startswith(marker) for marker in lis_markers):
                    # Verificar que no es solo ceros o relleno
                    if len(set(header[:100])) > 5:  # Debe tener algo de variedad en los bytes
                        logging.info(f"'{path.name}' detectado como formato LIS (marcador de inicio)")
                        return 'lis'

        # Si no es binario, intentar leer como texto para verificar si es LAS
        for encoding in ENCODINGS_TO_TRY:
            try:
                with path.open("r", encoding=encoding) as f:
                    content = f.read(4096)  # Leer solo el inicio

                    # Los archivos LAS tienen secciones que comienzan con ~
                    if re.search(r'^\s*~[VWCPAO]', content, re.IGNORECASE | re.MULTILINE):
                        logging.info(f"'{path.name}' detectado como formato LAS")
                        return 'las'

                    # DLAS podría ser una variante de LAS
                    if path.suffix.lower() == '.dlas' and '~' in content:
                        logging.info(f"'{path.name}' detectado como formato DLAS (variante de LAS)")
                        return 'las'  # Tratar DLAS como LAS

            except (UnicodeDecodeError, PermissionError):
                continue

    except Exception as e:
        logging.error(f"Error detectando formato de '{path.name}': {e}")

    return 'unknown'

def preprocess_las_content(file_path: Path, encoding: str) -> Optional[str]:
    """
    Lee un archivo LAS y lo limpia en memoria para insertar un encabezado ~A si falta.
    """
    try:
        content = file_path.read_text(encoding=encoding, errors='replace')
    except Exception as e:
        logging.error(f"Error al leer el archivo {file_path}: {e}")
        return None

    # Si ya tiene sección ~A, no hacer nada
    if re.search(r'^\s*~A', content, re.IGNORECASE | re.MULTILINE):
        return content

    # Buscar la sección de datos
    match = re.search(r'(~C(?:.|\n)*?\n)(\s*[-+]?\d)', content, re.IGNORECASE)

    if match:
        insert_point = match.start(2)
        pre_data_content = content[:insert_point]
        data_content = content[insert_point:]
        
        # Eliminar líneas de encabezado no estándar
        lines_before_data = pre_data_content.split('\n')
        cleaned_lines_before_data = []
        for line in lines_before_data:
            if not (line.strip().startswith('"') and line.strip().endswith('"')):
                cleaned_lines_before_data.append(line)
            else:
                logging.warning(f"'{file_path.name}': Eliminando línea de encabezado no estándar: {line.strip()}")

        cleaned_pre_data = "\n".join(cleaned_lines_before_data)
        
        logging.info(f"'{file_path.name}': Insertando encabezado de sección ~A faltante.")
        return cleaned_pre_data + '\n~A\n' + data_content
    
    return content

def preprocess_las_vers_param(content: str) -> str:
    """
    Renames the VERS mnemonic in the Parameter section to P_VERS to avoid
    conflicts with the main version block during lasio parsing.
    """
    param_section_pattern = re.compile(r'(^\s*~P[^\n]*\n)((?:.|\n)*?)(?=\s*~|\Z)', re.IGNORECASE | re.MULTILINE)
    
    match = param_section_pattern.search(content)
    if not match:
        return content

    param_header = match.group(1)
    param_content = match.group(2)
    end_of_section = match.end(2)

    # Replace VERS. with P_VERS. only within the Parameter section
    # This avoids KeyError in lasio for non-standard version values in this section
    modified_param_content = re.sub(r'^(\s*VERS\s*\.)', r' P_VERS.', param_content, flags=re.MULTILINE | re.IGNORECASE)

    if modified_param_content == param_content:
        return content # No changes were made
    
    logging.info("Renamed 'VERS' mnemonic in ~P section to avoid parsing conflict.")
    # Reconstruct the full content
    return content[:match.start(2)] + modified_param_content + content[end_of_section:]

def preprocess_las_curve_vers(content: str) -> str:
    """
    Renames the VERS mnemonic in the Curve section to C_VERS to avoid
    conflicts with the main version block during lasio parsing.
    """
    curve_section_pattern = re.compile(r'(^\s*~C[^\n]*\n)((?:.|\n)*?)(?=\s*~|\Z)', re.IGNORECASE | re.MULTILINE)
    
    match = curve_section_pattern.search(content)
    if not match:
        return content

    curve_header = match.group(1)
    curve_content = match.group(2)
    end_of_section = match.end(2)

    # Replace VERS. with C_VERS. only within the Curve section
    modified_curve_content = re.sub(r'^(\s*VERS\s*\.)', r' C_VERS.', curve_content, flags=re.MULTILINE | re.IGNORECASE)

    if modified_curve_content == curve_content:
        return content # No changes were made
    
    logging.info("Renamed 'VERS' mnemonic in ~C section to avoid parsing conflict.")
    # Reconstruct the full content
    return content[:match.start(2)] + modified_curve_content + content[end_of_section:]

# =========================
# Extractores Específicos por Formato
# =========================

def extract_metadata_from_las(path: Path) -> Optional[Dict[str, Any]]:
    """
    Extrae metadatos de archivos LAS/DLAS usando lasio, con un fallback a extracción de texto.
    """
    if not lasio:
        logging.error("lasio no está disponible para procesar archivos LAS")
        return None

    las_file = None
    successful_encoding = "autodetect"
    has_corrupt_data = False

    try:
        # El preprocesamiento puede ayudar a corregir archivos LAS con secciones ~A faltantes.
        # Se intenta con una codificación común, si falla, lasio lo manejará.
        processed_content = preprocess_las_content(path, ENCODINGS_TO_TRY[0])

        if processed_content:
            processed_content = preprocess_las_vers_param(processed_content)
            processed_content = preprocess_las_curve_vers(processed_content)

        file_ref = processed_content if processed_content else str(path)

        # Suprimir warnings verbose de lasio durante la lectura
        import sys
        import io
        old_stderr = sys.stderr
        sys.stderr = io.StringIO()

        try:
            las_file = lasio.read(
                file_ref,
                ignore_data=False,
                ignore_header_errors=True,
                autodetect_encoding=True
            )
            successful_encoding = las_file.encoding
        finally:
            captured_warnings = sys.stderr.getvalue()
            sys.stderr = old_stderr

            # Detectar si hay líneas corruptas pero no mostrar todas
            if "Line" in captured_warnings and len(captured_warnings) > 500:
                has_corrupt_data = True
                logging.warning(f"⚠️ Archivo LAS '{path.name}' contiene líneas con datos corruptos o caracteres inválidos (omitiendo detalles)")
            elif captured_warnings.strip():
                # Solo mostrar warnings si son cortos/relevantes
                for line in captured_warnings.split('\n')[:3]:  # Máximo 3 líneas
                    if line.strip() and 'wrapped' not in line.lower():
                        logging.debug(line.strip())

        logging.info(f"Archivo LAS '{path.name}' leído exitosamente con lasio y codificación '{successful_encoding}'.")
    except Exception as e:
        error_msg = str(e)
        if "wrapped" in error_msg.lower():
            logging.warning(f"⚠️ Archivo LAS '{path.name}' usa formato wrapped - reintentando con engine='normal'")
        else:
            logging.warning(f"⚠️ Error inicial leyendo '{path.name}' - intentando modo alternativo")

        # --- INICIO: Lógica de Reintento ---
        try:
            logging.info(f"Reintentando '{path.name}' con lasio, ignorando datos de curvas")
            las_file = lasio.read(
                str(path),
                ignore_data=True,  # Ignorar la sección de datos (~A) que causa el error
                ignore_header_errors=True,
                autodetect_encoding=True
            )
            successful_encoding = las_file.encoding
            logging.info(f"Lectura de encabezado exitosa para '{path.name}' en el reintento")
        except Exception as e_retry:
            logging.error(f"⚠️ No se pudo leer '{path.name}' con lasio - usando fallback de texto")
            # Si el reintento falla, las_file sigue siendo None y se pasará al fallback de texto
            pass
        # --- FIN: Lógica de Reintento ---

    # --- Si lasio tiene éxito, extraer metadatos detallados ---
    if las_file:
        try:
            header_dict = {}
            for section in las_file.sections:
                valid_items = [item for item in las_file.sections[section] if hasattr(item, 'mnemonic')]
                header_dict[section] = {
                    item.mnemonic: {"value": str(item.value), "descr": str(item.descr), "unit": str(item.unit)}
                    for item in valid_items
                }

            curves_with_data = [c for c in las_file.curves if c.data is not None and len(c.data) > 0]
            curves = [{"mnemonic": c.mnemonic, "unit": str(c.unit), "descr": str(c.descr)} for c in las_file.curves]

            start_val, end_val, md_unit = None, None, None
            if curves_with_data and pd:
                try:
                    # Usar el índice del DataFrame de lasio que es más robusto
                    valid_index = las_file.index[~pd.isna(las_file.index)]
                    if len(valid_index) > 0:
                        start_val = float(valid_index[0])
                        end_val = float(valid_index[-1])
                        # Corregir la obtención de la unidad
                        if hasattr(las_file.index, 'unit'):
                            md_unit = las_file.index.unit
                        elif las_file.curves:
                            md_unit = las_file.curves[0].unit
                except Exception as e:
                    logging.warning(f"No se pudo determinar el rango de profundidad de las curvas: {e}")

            # Si los valores de las curvas no son válidos, intentar desde el header
            if start_val is None and 'STRT' in las_file.well:
                start_val = las_file.well['STRT'].value
                md_unit = las_file.well['STRT'].unit
            if end_val is None and 'STOP' in las_file.well:
                end_val = las_file.well['STOP'].value

            # Construir el contenido raw de forma segura, sin usar to_json() que puede ser problemático
            raw_content_dict = {
                "Version": {item.mnemonic: {"value": str(item.value), "descr": str(item.descr)} for item in las_file.version},
                "Well": {item.mnemonic: {"value": str(item.value), "descr": str(item.descr), "unit": str(item.unit)} for item in las_file.well},
                "Curves": {item.mnemonic: {"unit": str(item.unit), "descr": str(item.descr), "value": str(item.value)} for item in las_file.curves},
                "Parameter": {item.mnemonic: {"value": str(item.value), "descr": str(item.descr), "unit": str(item.unit)} for item in las_file.params},
                "Other": las_file.other
            }

            return {
                "format": "LAS",
                "header": header_dict,
                "curves": curves,
                "raw_las_content": raw_content_dict,
                "actual_start_md": start_val,
                "actual_end_md": end_val,
                "actual_md_unit": md_unit,
                "note": f"Procesado con lasio (codificación: {successful_encoding})."
            }
        except Exception as e:
            logging.error(f"Error extrayendo metadatos con lasio después de leer el archivo: {e}", exc_info=True)
            # Continuar al fallback si la extracción de metadatos falla
            pass

    # --- Fallback: Si lasio falla, intentar extracción de texto básica ---
    logging.warning(f"lasio no pudo procesar '{path.name}'. Realizando extracción de texto básica del encabezado.")
    try:
        content = path.read_text(encoding=ENCODINGS_TO_TRY[0], errors='ignore')
        
        def parse_header_section(section_char, text):
            """Helper to parse ~W, ~P sections."""
            pattern = re.compile(rf'^\s*~{section_char}[^\n]*\n((?:.|\n)*?)(?=\s*~|\Z)', re.IGNORECASE)
            match = pattern.search(text)
            if not match:
                return {}
            
            section_content = match.group(1)
            header_items = {}
            # Regex for "MNEM.UNIT  VALUE: DESCRIPTION"
            line_pattern = re.compile(r'^\s*#?\s*([^.\s]+)\.([^\s]*)\s+([^:]+?)\s*:\s*(.*)', re.MULTILINE)
            for line_match in line_pattern.finditer(section_content):
                mnemonic = line_match.group(1).strip()
                if not mnemonic: continue
                
                value_str = line_match.group(3).strip()
                # Attempt to convert to number if possible
                try:
                    value = float(value_str)
                except ValueError:
                    value = value_str

                header_items[mnemonic] = {
                    "value": value,
                    "unit": line_match.group(2).strip(),
                    "descr": line_match.group(4).strip()
                }
            return header_items

        well_info = parse_header_section('W', content)
        params = parse_header_section('P', content)
        
        # Para las curvas, solo extraer la lista de mnemónicos y descripciones
        curves_section_content = re.search(r'^\s*~C[^\n]*\n((?:.|\n)*?)(?=\s*~|\Z)', content, re.IGNORECASE)
        curves = []
        if curves_section_content:
            # Regex for "MNEM.UNIT  API_CODE: DESCRIPTION"
            line_pattern = re.compile(r'^\s*#?\s*([^.\s]+)\.([^\s]*)\s+[^:]*:\s*(.*)', re.MULTILINE)
            for line_match in line_pattern.finditer(curves_section_content.group(1)):
                mnemonic = line_match.group(1).strip()
                if not mnemonic: continue
                curves.append({
                    "mnemonic": mnemonic,
                    "unit": line_match.group(2).strip(),
                    "descr": line_match.group(3).strip()
                })

        if not well_info and not params and not curves:
            logging.error(f"La extracción de texto básica no encontró secciones de encabezado en '{path.name}'.")
            return None

        start_md_val, start_md_unit = get_header_value(well_info, "START_MD")
        end_md_val, _ = get_header_value(well_info, "STOP_MD")

        return {
            "format": "LAS (Fallback)",
            "header": {
                "Well": well_info,
                "Parameter": params
            },
            "curves": curves,
            "raw_las_content": "No disponible (extracción de texto)",
            "actual_start_md": start_md_val,
            "actual_end_md": end_md_val,
            "actual_md_unit": start_md_unit,
            "note": "Metadatos extraídos usando un método de fallback basado en texto. El archivo puede estar corrupto o tener un formato no estándar."
        }
    except Exception as e:
        logging.error(f"La extracción de texto básica para '{path.name}' falló: {e}", exc_info=True)
        return None

def extract_metadata_from_dlis(path: Path) -> Optional[Dict[str, Any]]:
    """
    Extrae metadatos de archivos DLIS usando dlisio.
    """
    if not dlisio:
        logging.warning(f"dlisio no está disponible. Se intentará extracción básica para '{path.name}'")
        return extract_basic_binary_info(path, "DLIS")

    try:
        logging.info(f"Procesando archivo DLIS: {path.name}")

        # dlisio.dlis.load retorna una lista de archivos lógicos
        try:
            with dlisio.dlis.load(str(path)) as files:
                metadata = {
                    "format": "DLIS",
                    "header": {},
                    "curves": [],
                    "logical_files_count": len(files)
                }

                # Procesar cada archivo lógico
                for lf_index, logical_file in enumerate(files):
                    try:
                        logging.info(f"  Procesando archivo lógico {lf_index + 1}/{len(files)}")

                        # Extraer información del ORIGIN (encabezado)
                        try:
                            origins = logical_file.origins
                            if origins and len(origins) > 0:
                                origin = origins[0]
                                metadata["header"]["Origin"] = {
                                    "file_id": str(getattr(origin, 'file_id', '')),
                                    "file_set_name": str(getattr(origin, 'file_set_name', '')),
                                    "file_set_number": str(getattr(origin, 'file_set_number', '')),
                                    "file_number": str(getattr(origin, 'file_number', '')),
                                    "field_name": str(getattr(origin, 'field_name', '')),
                                    "well_name": str(getattr(origin, 'well_name', '')),
                                    "producer_name": str(getattr(origin, 'producer_name', '')),
                                    "creation_time": str(getattr(origin, 'creation_time', ''))
                                }
                        except Exception as e:
                            logging.warning(f"  No se pudo extraer información de ORIGIN: {e}")

                        # Extraer información de los parámetros
                        try:
                            parameters = logical_file.parameters
                            if parameters and len(parameters) > 0:
                                params = {}
                                for param in parameters:
                                    try:
                                        param_name = str(getattr(param, 'name', 'unknown'))
                                        param_values = getattr(param, 'values', [])
                                        param_value = str(param_values[0]) if param_values and len(param_values) > 0 else ''
                                        param_units = str(getattr(param, 'units', ''))

                                        params[param_name] = {
                                            "value": param_value,
                                            "unit": param_units
                                        }
                                    except Exception as e:
                                        logging.debug(f"  Error procesando parámetro: {e}")
                                        continue

                                if params:
                                    metadata["header"]["Parameters"] = params
                        except Exception as e:
                            logging.warning(f"  No se pudieron extraer parámetros: {e}")

                        # Extraer información de las curvas/canales
                        try:
                            frames = logical_file.frames
                            for frame in frames:
                                channels = frame.channels
                                for channel in channels:
                                    try:
                                        curve_info = {
                                            "mnemonic": str(channel.name),
                                            "unit": str(getattr(channel, 'units', '')),
                                            "descr": str(getattr(channel, 'long_name', ''))
                                        }
                                        metadata["curves"].append(curve_info)
                                    except Exception as e:
                                        logging.debug(f"  Error procesando canal: {e}")
                                        continue
                        except Exception as e:
                            logging.warning(f"  No se pudieron extraer canales: {e}")

                    except Exception as e:
                        logging.warning(f"  Error procesando archivo lógico {lf_index + 1}: {e}")
                        continue

                # Información del pozo desde el header
                if "Origin" in metadata["header"]:
                    origin = metadata["header"]["Origin"]
                    metadata["header"]["Well"] = {
                        "WELL": {"value": origin.get("well_name", ""), "unit": "", "descr": "Well Name"},
                        "FIELD": {"value": origin.get("field_name", ""), "unit": "", "descr": "Field Name"},
                        "COMPANY": {"value": origin.get("producer_name", ""), "unit": "", "descr": "Company"},
                        "DATE": {"value": origin.get("creation_time", ""), "unit": "", "descr": "Creation Date"}
                    }

                logging.info(f"  Extracción exitosa: {len(metadata['curves'])} curvas encontradas")
                return metadata

        except Exception as e:
            logging.error(f"Error al cargar archivo DLIS con dlisio: {e}")
            raise

    except Exception as e:
        logging.error(f"Error procesando DLIS '{path.name}': {e}", exc_info=True)
        return extract_basic_binary_info(path, "DLIS")

def extract_metadata_from_lis(path: Path) -> Optional[Dict[str, Any]]:
    """
    Extrae metadatos de archivos LIS.
    Nota: LIS es un formato más antiguo que DLIS, dlisio tiene soporte limitado.
    """
    if not dlisio:
        logging.warning(f"dlisio no está disponible. Se intentará extracción básica para '{path.name}'")
        return extract_basic_binary_info(path, "LIS")

    try:
        logging.info(f"Intentando procesar archivo LIS con dlisio: {path.name}")

        # Intentar leer el archivo LIS con dlisio.lis
        try:
            # Suprimir output verbose de dlisio durante carga
            import sys
            import io
            old_stderr = sys.stderr
            sys.stderr = io.StringIO()

            try:
                files_context = dlisio.lis.load(str(path))
            finally:
                captured_errors = sys.stderr.getvalue()
                sys.stderr = old_stderr

                # Solo mostrar si hay error crítico que impida lectura
                if "critical" in captured_errors.lower() and "stopped" in captured_errors.lower():
                    logging.warning(f"⚠️ Archivo LIS '{path.name}' tiene registros corruptos o incompletos (dlisio se detuvo prematuramente)")

            with files_context as files:
                metadata = {
                    "format": "LIS",
                    "header": {},
                    "curves": [],
                    "logical_files_count": len(files)
                }

                # Procesar cada archivo lógico
                for lf_index, lis_file in enumerate(files):
                    try:
                        logging.info(f"  Procesando archivo lógico LIS {lf_index + 1}/{len(files)}")

                        # Extraer información del header
                        try:
                            # LIS tiene diferentes tipos de registros
                            # Intentar extraer información básica del pozo
                            well_info = {}

                            # Buscar información en los registros de información del pozo
                            if hasattr(lis_file, 'wellsite_data'):
                                for record in lis_file.wellsite_data():
                                    try:
                                        # Extraer pares clave-valor del registro
                                        if hasattr(record, 'info'):
                                            for key, value in record.info.items():
                                                well_info[key] = {"value": str(value), "unit": "", "descr": ""}
                                    except Exception as e:
                                        logging.debug(f"  Error extrayendo wellsite data: {e}")

                            if well_info:
                                metadata["header"]["Well"] = well_info

                        except Exception as e:
                            logging.warning(f"  No se pudo extraer información del header LIS: {e}")

                        # Extraer información de las curvas
                        try:
                            curves_set = set()  # Para evitar duplicados

                            # En LIS, las curvas están en los registros de datos
                            if hasattr(lis_file, 'data_format_specs'):
                                for spec in lis_file.data_format_specs():
                                    try:
                                        # Cada especificación de formato contiene información sobre las curvas
                                        if hasattr(spec, 'specs'):
                                            for curve_spec in spec.specs:
                                                try:
                                                    mnemonic = str(getattr(curve_spec, 'mnemonic', 'unknown'))
                                                    if mnemonic not in curves_set:
                                                        curve_info = {
                                                            "mnemonic": mnemonic,
                                                            "unit": str(getattr(curve_spec, 'units', '')),
                                                            "descr": str(getattr(curve_spec, 'long_name', ''))
                                                        }
                                                        metadata["curves"].append(curve_info)
                                                        curves_set.add(mnemonic)
                                                except Exception as e:
                                                    logging.debug(f"  Error procesando especificación de curva: {e}")
                                    except Exception as e:
                                        logging.debug(f"  Error procesando formato de datos: {e}")

                        except Exception as e:
                            logging.warning(f"  No se pudieron extraer curvas LIS: {e}")

                    except Exception as e:
                        logging.warning(f"  Error procesando archivo lógico LIS {lf_index + 1}: {e}")
                        continue

                logging.info(f"  Extracción exitosa: {len(metadata['curves'])} curvas encontradas")
                return metadata

        except Exception as e:
            # Si dlisio.lis no puede leerlo, intentar extracción básica
            error_msg = str(e)

            # Determinar si es corrupción o formato incorrecto
            if "Too short" in error_msg or "Missing next PRH" in error_msg or "end-of-file" in error_msg:
                logging.warning(f"⚠️ Archivo LIS '{path.name}' está corrupto o truncado - usando extracción parcial")
            else:
                logging.warning(f"⚠️ No se pudo procesar '{path.name}' como LIS - probando otros métodos")

            # Verificar si el archivo podría ser un LAS de texto con extensión incorrecta
            try:
                with path.open('r', encoding='utf-8', errors='ignore') as f:
                    content_sample = f.read(1024)
                    # Si contiene marcadores LAS válidos, intentar procesarlo como LAS
                    if '~V' in content_sample and '~W' in content_sample:
                        logging.info(f"El archivo '{path.name}' parece tener formato LAS. Intentando fallback a LAS.")
                        return extract_metadata_from_las(path)
            except Exception:
                pass

            # Si no es LAS de texto, usar extracción básica
            logging.info(f"Usando extracción parcial de strings para '{path.name}'")
            return extract_basic_binary_info(path, "LIS")

    except Exception as e:
        logging.error(f"Error procesando LIS '{path.name}': {e}")

    # Si todo falla, usar extracción básica
    return extract_basic_binary_info(path, "LIS")

def extract_basic_binary_info(path: Path, format_type: str) -> Dict[str, Any]:
    """
    Extracción mejorada de información para archivos binarios LIS cuando dlisio falla.
    Intenta extraer strings ASCII y estructura básica del formato LIS.
    """
    try:
        file_stats = path.stat()

        metadata = {
            "format": format_type,
            "header": {
                "FileInfo": {
                    "FILENAME": {"value": path.name, "unit": "", "descr": "File Name"},
                    "SIZE": {"value": f"{file_stats.st_size:,} bytes", "unit": "bytes", "descr": "File Size"},
                    "MODIFIED": {"value": datetime.fromtimestamp(file_stats.st_mtime).isoformat(), "unit": "", "descr": "Last Modified"}
                },
                "Well": {}
            },
            "curves": [],
            "note": f"Extracción básica de archivo {format_type}"
        }

        # Intentar extraer información adicional para archivos LIS
        if format_type == "LIS":
            logging.info(f"Intentando extracción avanzada de strings ASCII para archivo LIS: {path.name}")
            lis_info = extract_lis_strings(path)

            if lis_info:
                # Agregar información de compañía/servicio si se encuentra
                if lis_info.get("company"):
                    metadata["header"]["Well"]["COMPANY"] = {
                        "value": lis_info["company"],
                        "unit": "",
                        "descr": "Service Company"
                    }

                # Agregar información de fecha si se encuentra
                if lis_info.get("date"):
                    metadata["header"]["Well"]["DATE"] = {
                        "value": lis_info["date"],
                        "unit": "",
                        "descr": "Recording Date"
                    }

                # Agregar curvas encontradas
                if lis_info.get("curves"):
                    metadata["curves"] = lis_info["curves"]
                    logging.info(f"Extraídas {len(lis_info['curves'])} curvas del archivo LIS")

                # Agregar parámetros si se encuentran
                if lis_info.get("parameters"):
                    metadata["header"]["Parameters"] = lis_info["parameters"]

                metadata["note"] = f"Extracción parcial de archivo LIS mediante análisis de strings ASCII. {len(metadata['curves'])} curvas identificadas."

        if not metadata["curves"]:
            logging.warning(f"No se pudieron extraer curvas del archivo {format_type}: {path.name}")
        else:
            logging.info(f"Extracción exitosa de {len(metadata['curves'])} curvas")

        return metadata

    except Exception as e:
        logging.error(f"Error en extracción básica: {e}")
        return None

def extract_lis_strings(path: Path) -> Dict[str, Any]:
    """
    Extrae información de archivos LIS analizando strings ASCII embebidos.
    Los archivos LIS contienen información en formato de texto mezclada con datos binarios.
    """
    info = {
        "company": None,
        "date": None,
        "curves": [],
        "parameters": {}
    }

    try:
        with path.open('rb') as f:
            # Leer los primeros 100KB donde suele estar la metadata
            data = f.read(100000)

            # Buscar strings ASCII imprimibles de más de 4 caracteres
            strings = []
            current_string = ""
            start_pos = 0

            for i, byte in enumerate(data):
                try:
                    if 32 <= byte <= 126:  # ASCII imprimible
                        if not current_string:
                            start_pos = i
                        current_string += chr(byte)
                    else:
                        if len(current_string) >= 4:
                            # Sanitizar el string para evitar caracteres problemáticos
                            clean_string = current_string.strip()
                            # Filtrar caracteres de control residuales
                            clean_string = ''.join(c for c in clean_string if c.isprintable() or c.isspace())
                            if clean_string:
                                strings.append((start_pos, clean_string))
                        current_string = ""
                except Exception:
                    # Si hay algún error procesando un byte, continuar
                    current_string = ""
                    continue

            # Buscar información específica en los strings
            curve_mnemonics = []
            curve_info = {}
            current_mnem = None

            for pos, s in strings:
                try:
                    # Detectar compañía
                    if 'SCHLUMBERGER' in s or 'HALLIBURTON' in s or 'BAKER' in s or 'WEATHERFORD' in s:
                        info["company"] = s

                    # Detectar fechas en formato YY/MM/DD o similar
                    date_match = re.search(r'\d{2}/\d{2}/\d{2,4}', s)
                    if date_match:
                        info["date"] = date_match.group()

                    # Detectar mnemónicos de curvas (patrón: MNEM seguido de nombre)
                    if s.startswith('MNEM'):
                        # Extraer el mnemónico (generalmente después de espacios)
                        mnem_match = re.search(r'MNEM\s+(\w+)', s)
                        if mnem_match:
                            current_mnem = mnem_match.group(1).strip()
                            if current_mnem not in curve_info:
                                curve_info[current_mnem] = {"mnemonic": current_mnem, "unit": "", "descr": ""}

                    # Detectar unidades (PUNI = Processing Unit, TUNI = Tool Unit)
                    if current_mnem and ('PUNI' in s or 'TUNI' in s):
                        unit_match = re.search(r'(?:PUNI|TUNI)\s+(\w+)', s)
                        if unit_match:
                            unit = unit_match.group(1).strip()
                            if unit and unit not in ['EA', 'EO', 'ED']:  # Ignorar marcadores de fin
                                curve_info[current_mnem]["unit"] = unit

                    # Detectar valores (VALU)
                    if current_mnem and 'VALU' in s:
                        val_match = re.search(r'VALU\s+(.+)', s)
                        if val_match:
                            value = val_match.group(1).strip()
                            if value:
                                curve_info[current_mnem]["descr"] = f"Value: {value}"

                    # Detectar tipo de herramienta (TYPE)
                    if 'TYPE' in s:
                        type_match = re.search(r'TYPE\s+(\w+)', s)
                        if type_match:
                            tool_type = type_match.group(1).strip()
                            info["parameters"]["TOOL_TYPE"] = {
                                "value": tool_type,
                                "unit": "",
                                "descr": "Tool Type"
                            }
                except Exception:
                    # Si hay error procesando un string individual, continuar con el siguiente
                    continue

            # Convertir curve_info a lista
            info["curves"] = [v for v in curve_info.values() if v["mnemonic"]]

            # Log de información extraída
            if info["curves"]:
                logging.info(f"Strings extraídos: {len(info['curves'])} mnemónicos de curvas encontrados")

    except Exception as e:
        logging.debug(f"Error extrayendo strings de LIS: {e}")

    return info

# =========================
# Procesamiento Principal
# =========================

def extract_metadata(path: Path) -> Optional[Dict[str, Any]]:
    """
    Función principal que determina el formato y llama al extractor apropiado.
    """
    file_format = detect_file_format(path)
    ext_lower = path.suffix.lower()

    # Prioridad 1: Usar el formato detectado si es confiable
    if file_format != 'unknown':
        logging.info(f"Formato detectado por contenido: '{file_format.upper()}'. Usando el extractor correspondiente.")
        if file_format == 'las':
            return extract_metadata_from_las(path)
        elif file_format == 'dlis':
            return extract_metadata_from_dlis(path)
        elif file_format == 'lis':
            return extract_metadata_from_lis(path)

    # Prioridad 2: Si la detección de contenido falla, usar la extensión como fallback
    logging.warning(f"Formato no reconocido por contenido para '{path.name}'. Intentando fallback basado en extensión '{ext_lower}'.")
    if any(ext_lower.startswith(e) for e in ['.las', '.dlas']):
        return extract_metadata_from_las(path)
    elif ext_lower.startswith('.lis'):
        return extract_metadata_from_lis(path)
    elif ext_lower.startswith('.dlis'):
        return extract_metadata_from_dlis(path)

    logging.error(f"No se pudo determinar un extractor de fallback para la extensión '{ext_lower}'.")
    return None

def process_file(file_path: Path, out_dir: Path) -> bool:
    """Procesa un único archivo, extrayendo y guardando metadatos."""
    try:
        # Validar que el archivo existe y es accesible
        if not file_path.exists():
            logging.error(f"El archivo no existe: {safe_str(file_path.name)}")
            return False

        if not file_path.is_file():
            logging.error(f"La ruta no es un archivo: {safe_str(file_path.name)}")
            return False

        # 1. Extraer Metadata usando el método apropiado
        metadata = extract_metadata(file_path)
        if not metadata:
            logging.warning(f"Se omitió el archivo {safe_str(file_path.name)} (no se pudieron extraer metadatos)")
            return False

        format_type = metadata.get("format", "UNKNOWN")
        well_info = metadata.get("header", {}).get("Well", {})
        parameter_info = metadata.get("header", {}).get("Parameter", {})
        curves = metadata.get("curves", [])

        # Añadir ruta original a los metadatos
        metadata["original_file_path"] = str(file_path.resolve())

        # Guardar JSON en bruto
        raw_json_out_path = out_dir / (file_path.stem + ".json")
        write_json_atomic(raw_json_out_path, metadata)
        logging.info(f"Archivo JSON en bruto generado: {safe_str(raw_json_out_path.name)}")

        # 2. Construir JSON OSDU
        log_id = file_path.stem.replace(" ", "-")
        wellbore_id, _ = get_header_value(well_info, "WELL", "unknown")
        
        start_md_val, start_md_unit = get_header_value(well_info, "START_MD")
        end_md_val, end_md_unit = get_header_value(well_info, "STOP_MD")

        # Usar valores de la curva si están disponibles
        if metadata.get("actual_start_md") is not None:
            start_md_val = metadata["actual_start_md"]
            start_md_unit = metadata.get("actual_md_unit", "")
        if metadata.get("actual_end_md") is not None:
            end_md_val = metadata["actual_end_md"]
            end_md_unit = metadata.get("actual_md_unit", "")

        step_val, step_unit = get_header_value(well_info, "STEP")
        service_co, _ = get_header_value(well_info, "SERVICE_COMPANY")
        null_val, _ = get_header_value(well_info, "NULL_VALUE")

        # Determinar tipo de log basado en las curvas
        log_type = "UNKNOWN"
        if curves:
            curve_mnemonics = [c.get("mnemonic", "").upper() for c in curves]
            if any("GR" in m for m in curve_mnemonics):
                log_type = "Gamma Ray"
            elif any("DEN" in m or "RHOB" in m for m in curve_mnemonics):
                log_type = "Density"
            elif any("DT" in m or "AC" in m for m in curve_mnemonics):
                log_type = "Sonic"
            elif any("RES" in m or "RT" in m or "RXO" in m for m in curve_mnemonics):
                log_type = "Resistivity"

        osdu_data = {
            "kind": "osdu:wks:work-product-component--WellLog:1.0.0",
            "data": {
                "LogID": log_id,
                "WellboreID": wellbore_id,
                "LogType": log_type,
                "FileFormat": format_type,
                "StartMD": {"value": safe_float(start_md_val), "unit": start_md_unit},
                "EndMD": {"value": safe_float(end_md_val), "unit": end_md_unit},
                "ServiceCompany": service_co,
                "Mnemonics": [c.get("mnemonic", "") for c in curves],
                "UOM": [c.get("unit", "") for c in curves],
                "SampleRate": {"value": safe_float(step_val), "unit": step_unit},
                "NullValue": safe_float(null_val),
                "FileRefs": [file_path.name],
                "OriginalFilePath": str(file_path.resolve())
            }
        }
        
        osdu_json_out_path = out_dir / (file_path.stem + "_osdu.json")
        write_json_atomic(osdu_json_out_path, osdu_data)
        logging.info(f"Archivo OSDU JSON generado: {osdu_json_out_path}")

        # 3. Construir Markdown de Metadatos
        md_content = f"# Metadatos del Pozo: {wellbore_id}\n\n"
        md_content += f"## Información General\n"
        md_content += f"* **Formato Detectado:** {format_type}\n"
        md_content += f"* **Ruta Original:** {file_path.resolve()}\n"
        md_content += f"* **Compañía:** {get_header_value(well_info, 'COMPANY')[0]}\n"
        md_content += f"* **Pozo:** {wellbore_id}\n"
        md_content += f"* **Campo:** {get_header_value(well_info, 'FIELD')[0]}\n"
        md_content += f"* **Provincia:** {get_header_value(well_info, 'PROVINCE')[0]}\n"
        md_content += f"* **País:** {get_header_value(well_info, 'COUNTRY')[0]}\n"
        md_content += f"* **Localización:** {get_header_value(well_info, 'LOCATION')[0]}\n"
        md_content += f"* **Compañía de Servicio:** {service_co}\n"
        md_content += f"* **Fecha de Registro:** {get_header_value(well_info, 'DATE')[0]}\n"
        md_content += f"* **ID Único de Pozo (UWI):** {get_header_value(well_info, 'UWI')[0]}\n"
        md_content += f"* **Latitud:** {get_header_value(well_info, 'LATITUDE')[0]}\n"
        md_content += f"* **Longitud:** {get_header_value(well_info, 'LONGITUDE')[0]}\n"
        md_content += f"* **MD Inicio:** {start_md_val} {start_md_unit}\n"
        md_content += f"* **MD Fin:** {end_md_val} {end_md_unit}\n"
        md_content += f"* **Paso de Muestreo:** {step_val} {step_unit}\n"
        md_content += f"* **Valor Nulo:** {null_val}\n\n"

        md_content += "## Curvas Registradas\n"
        if curves:
            md_content += f"**Total de curvas:** {len(curves)}\n\n"
            for curve in curves[:50]:  # Limitar a las primeras 50 curvas en el markdown
                md_content += f"* **{curve.get('mnemonic', '')}:** {curve.get('descr', '')} ({curve.get('unit', '')})\n"
            if len(curves) > 50:
                md_content += f"\n*... y {len(curves) - 50} curvas más*\n"
        else:
            md_content += "*No se encontraron curvas o no se pudieron extraer*\n"
        md_content += "\n"

        # Si hay una nota (extracción limitada), incluirla
        if metadata.get("note"):
            md_content += f"## Nota\n{metadata['note']}\n\n"

        md_content += "## JSON en Bruto Extraído del Archivo\n\n"
        md_content += "```json\n"
        md_content += json.dumps(metadata, indent=2, default=str)
        md_content += "\n```"

        md_out_path = out_dir / (file_path.stem + "_metadata.md")
        with md_out_path.open("w", encoding="utf-8", errors='replace') as f:
            f.write(md_content)
        logging.info(f"Archivo Markdown de metadatos generado: {safe_str(md_out_path.name)}")

        return True

    except Exception as e:
        logging.error(f"Error fatal procesando {safe_str(file_path.name)}: {safe_str(str(e))}")
        return False

# =========================
# Reporte de Ejecución  
# =========================
def generate_report(stats: Dict):
    report = "\n" + "="*80 + "\n"
    report += "INFORME FINAL DE EJECUCIÓN\n" + "="*80 + "\n"
    report += f"Total de archivos encontrados con extensiones {BASE_EXTENSIONS}: {stats['total_files_found']}\n"
    report += f"Archivos procesados con éxito en esta sesión: {stats['files_processed_this_run']}\n"
    report += f"Archivos omitidos por procesamiento previo: {stats['files_skipped']}\n"
    report += f"Archivos con errores u omitidos en esta sesión: {stats['files_with_errors_this_run']}\n\n"
    
    if stats['extensions_count']:
        report += "Desglose por extensión (en esta sesión):\n"
        for ext, count in stats['extensions_count'].items():
            report += f"  - {ext}: {count} archivos\n"
    
    if stats.get('format_detection'):
        report += "\nFormatos detectados:\n"
        for format_name, count in stats['format_detection'].items():
            report += f"  - {format_name}: {count} archivos\n"
    
    report += "\n" + "="*80 + "\n"
    
    logging.info(report)

# =========================
# Punto de Entrada Principal
# =========================
def main():
    # Limpiar log si es muy grande (> 50 MB)
    log_file = Path("pipeline_las_informacion_QC_1.log")
    if log_file.exists():
        try:
            log_size = log_file.stat().st_size
            if log_size > 50 * 1024 * 1024:  # 50 MB
                # Respaldar el log antiguo
                backup_log = log_file.with_suffix('.log.old')
                if backup_log.exists():
                    backup_log.unlink()
                log_file.rename(backup_log)
                print(f"Log anterior era muy grande ({log_size / (1024*1024):.1f} MB), se respaldó a {backup_log.name}")
        except Exception as e:
            print(f"No se pudo limpiar el log: {e}")

    start_time = datetime.now()
    logging.info(f"\n\n{'='*30} INICIANDO NUEVA EJECUCIÓN DEL SCRIPT (v2 - Multiformat) {'='*30}")

    # Verificar disponibilidad de librerías
    if not lasio:
        logging.error("CRÍTICO: lasio no está instalado. No se pueden procesar archivos LAS.")
        logging.error("Para instalar lasio, ejecute: pip install lasio")
        logging.warning("Continuando con soporte limitado. Solo se procesarán archivos DLIS/LIS.")

    if not dlisio:
        logging.warning("ADVERTENCIA: dlisio no está instalado. El soporte para DLIS/LIS será limitado.")
        logging.warning("Para soporte completo, instale con: pip install dlisio")
        logging.warning("Continuando con soporte limitado para DLIS/LIS.")

    if not lasio and not dlisio:
        logging.error("CRÍTICO: Ni lasio ni dlisio están instalados. No se puede procesar ningún archivo.")
        logging.error("Instale las librerías con: pip install lasio dlisio")
        sys.exit(1)

    stats = {
        "total_files_found": 0,
        "files_processed_this_run": 0,
        "files_with_errors_this_run": 0,
        "files_skipped": 0,
        "extensions_count": Counter(),
        "format_detection": Counter(),
    }

    input_path = Path(INPUT_DIR).expanduser()
    base_out_dir = Path(OUT_DIR).expanduser()
    state_file = Path(STATE_FILE)
    ensure_dir(base_out_dir)

    # --- Leer la lista de directorios a escanear ---
    dirs_to_scan_str = []
    if input_path.is_file():
        logging.info(f"Leyendo directorios desde el archivo: {input_path}")
        try:
            with input_path.open("r", encoding="utf-8") as f:
                dirs_to_scan_str = [line.strip() for line in f if line.strip()]
        except Exception as e:
            logging.error(f"No se pudo leer el archivo de entrada '{input_path}': {e}")
            sys.exit(1)
    elif input_path.is_dir():
        dirs_to_scan_str.append(str(input_path))
    else:
        logging.error(f"La ruta de entrada no es un archivo o directorio válido: {input_path}")
        sys.exit(1)

    if not dirs_to_scan_str:
        logging.warning(f"No se encontraron directorios para procesar en {input_path}")
        sys.exit(0)

    # --- Lógica de Reanudación ---
    last_processed_file_path = None
    if state_file.exists():
        content = state_file.read_text(encoding="utf-8").strip()
        if content:
            last_processed_file_path = Path(content)
            logging.info(f"Reanudando sesión. El último archivo procesado fue: {last_processed_file_path}")

    start_dir_index = 0
    if last_processed_file_path:
        found_dir = False
        for i, dir_str in enumerate(dirs_to_scan_str):
            if Path(dir_str) in last_processed_file_path.parents:
                start_dir_index = i
                found_dir = True
                logging.info(f"Reanudando desde el directorio: '{dir_str}'")
                break
        if not found_dir:
            logging.warning(f"No se pudo encontrar el directorio para reanudar. Iniciando desde el principio.")

    dirs_to_process_now = dirs_to_scan_str[start_dir_index:]
    logging.info(f"Resultados se guardarán en: {base_out_dir}")

    # --- Bucle principal de procesamiento ---
    for dir_index, dir_str in enumerate(dirs_to_process_now):
        if stop_event.is_set():
            break

        input_dir = Path(dir_str)
        if not input_dir.is_dir():
            logging.warning(f"La ruta '{dir_str}' no es un directorio válido, se omitirá.")
            continue

        logging.info(f"\n{'='*20} Escaneando directorio: {input_dir} {'='*20}")
        
        # Lógica mejorada para encontrar archivos que COMIENCEN con las extensiones base
        all_files = [p for p in input_dir.rglob("*") if p.is_file()]
        files_in_dir = sorted([
            p for p in all_files 
            if any(p.suffix.lower().startswith(ext) for ext in BASE_EXTENSIONS)
        ])

        if not files_in_dir:
            logging.info("No se encontraron archivos con las extensiones requeridas en este directorio.")
            continue
        
        stats['total_files_found'] += len(files_in_dir)
        
        start_file_index = 0
        if dir_index == 0 and last_processed_file_path:
            try:
                start_file_index = files_in_dir.index(last_processed_file_path) + 1
                stats['files_skipped'] += start_file_index
                logging.info(f"Se omitirán {start_file_index} archivos ya procesados.")
            except ValueError:
                logging.warning(f"El archivo de reanudación no se encontró. Procesando todo el directorio.")
        
        files_to_process_in_dir = files_in_dir[start_file_index:]
        
        if not files_to_process_in_dir:
            logging.info("No hay más archivos que procesar en este directorio.")
            continue

        total_in_dir = len(files_to_process_in_dir)
        for i, file_path in enumerate(files_to_process_in_dir):
            if stop_event.is_set():
                logging.info("Proceso interrumpido por el usuario.")
                break
            
            logging.info(f"\n--- (Archivo {i+1}/{total_in_dir}) Procesando: {file_path.name} ---")
            stats['extensions_count'][file_path.suffix.lower()] += 1
            
            # Detectar formato antes de procesar
            detected_format = detect_file_format(file_path)
            if detected_format != 'unknown':
                stats['format_detection'][detected_format.upper()] += 1
            
            try:
                source_root_dir = None
                for root_dir_str_lookup in dirs_to_scan_str:
                    root_dir = Path(root_dir_str_lookup)
                    if root_dir in file_path.parents:
                        source_root_dir = root_dir
                        break
                
                if not source_root_dir:
                    logging.error(f"No se pudo determinar el directorio raíz para {file_path}")
                    mirrored_out_dir = base_out_dir
                else:
                    relative_path = file_path.relative_to(source_root_dir)
                    root_folder_name = source_root_dir.name
                    mirrored_out_dir = base_out_dir / root_folder_name / relative_path.parent

                ensure_dir(mirrored_out_dir)

                if process_file(file_path, mirrored_out_dir):
                    stats['files_processed_this_run'] += 1
                    try:
                        state_file.write_text(str(file_path), encoding="utf-8")
                    except Exception as e:
                        logging.error(f"No se pudo guardar el estado: {e}")
                else:
                    stats['files_with_errors_this_run'] += 1
                    append_to_unprocessed_log(file_path)

            except Exception as e:
                logging.error(f"Error inesperado procesando {file_path}: {e}", exc_info=True)
                stats['files_with_errors_this_run'] += 1
                continue
        
        if stop_event.is_set():
            break

    if stats['total_files_found'] == 0:
        logging.warning(f"No se encontraron archivos con las extensiones {BASE_EXTENSIONS}")

    logging.info("Proceso completado.")
    
    end_time = datetime.now()
    logging.info(f"Duración total: {end_time - start_time}")
    
    generate_report(stats)

if __name__ == "__main__":
    main()
