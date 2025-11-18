# Análisis de Problemas con Archivos .lis

Fecha: 2025-11-18
Archivos analizados: 2

---

## 📋 Resumen Ejecutivo

Se identificaron **2 problemas críticos** con los archivos .lis de prueba:

1. **Archivo 1**: LIS corrupto/truncado (parcialmente procesable)
2. **Archivo 2**: DLIS con extensión .lis incorrecta (detección errónea)

---

## 🔴 Problema 1: `13_LOS-CEDROS-1_1469_LIS_8418.LIS`

### Información del Archivo
- **Tamaño**: 2.79 MB (2,927,074 bytes)
- **Formato Real**: LIS (Log Information Standard)
- **Compañía**: Schlumberger Well Services
- **Fecha**: 93/12/15 (15 de diciembre de 1993)
- **Tipo de herramienta**: LIMI

### Error Reportado por dlisio
```
Problem:      iodevice::read_physical_header: Too short record length (was 0 bytes)
Where:        dlisio.lis.load: file [...]/13_LOS-CEDROS-1_1469_LIS_8418.LIS
Severity:     critical
Action taken: Indexing stopped at physical tell 908 (dec)
```

### Análisis Técnico

**Estructura del archivo:**
```
Bytes 0-19:   00 00 00 00 00 00 00 00 90 00 00 00 00 84 80 00 84 00 20 20
              ^^^^^^^^^^^^^^^^^^^^^^^^^^ Headers/padding
                                          ^^^^^ Posible PRH

Bytes 20-119: Metadata en ASCII
              "00/00/00  CSU             00            SCHLUMBERGER WELL SERVICES CSU TAPE"

Bytes 900-920: 00 0b ef 14 00 00 00 00 00 00 9e 01 00 00 d2 04 00 00 01 3c
               ^^^^^ PRH con longitud posiblemente corrupta
```

**Causa raíz:**
- Al byte 908, el Physical Record Header (PRH) indica longitud = 0 bytes
- Esto viola el estándar LIS (longitud mínima 4 bytes)
- Posibles causas:
  1. Archivo truncado durante transferencia
  2. Corrupción de datos
  3. Registro de finalización malformado
  4. Conversión de formato incorrecta

**Resultado del fallback:**
- ✅ El método de extracción de strings ASCII **funcionó**
- ✅ Extraídas **482 curvas** exitosamente
- ✅ Metadata parcial recuperada (compañía, fecha, herramienta)

**Curvas extraídas (muestra):**
- EXP (PSIGEA)
- DUMMEA
- LIMI tool curves
- 480+ más...

### Recomendaciones
1. ✅ El fallback actual maneja este caso correctamente
2. ⚠️ Considerar validar archivos LIS antes de procesamiento completo
3. 📊 Agregar estadísticas sobre bytes procesados vs. tamaño total
4. 💡 Implementar recuperación progresiva de registros parciales

---

## 🔴 Problema 2: `13_TOCORAGUA-1_7658_83999_SEIS.lis`

### Información del Archivo
- **Tamaño**: 11.8 MB (12,393,816 bytes)
- **Formato Real**: **DLIS** (Digital Log Interchange Standard)
- **Extensión**: .lis (INCORRECTA)
- **Detección del script**: LIS ❌

### Error Reportado por dlisio
```
Problem:      iodevice::index_record: Missing next PRH. (iodevice::read_physical_header: end-of-file)
Where:        dlisio.lis.load: file [...]/13_TOCORAGUA-1_7658_83999_SEIS.lis
Severity:     critical
Action taken: Indexing stopped at physical tell 116 (dec)
```

### Análisis Técnico

**Estructura del archivo (primeros 120 bytes):**
```
Hex:
01 00 00 00 00 00 00 00 0c 00 00 00 00 00 00 00
00 00 00 00 68 00 00 00 20 20 20 31 56 31 2e 30
30 52 45 43 4f 52 44 20 38 31 39 32 44 65 66 61
75 6c 74 20 53 74 6f 72 61 67 65 20 53 65 74 20
                        ^^^^^^^^^^^^^^^^^^^^
                        "Default Storage Set"

ASCII equivalente:
..................h...   1V1.00RECORD 8192Default Storage Set
                         ^^^^^                 ^^^^^^^^^^^^^^^
                         DLIS Version         DLIS terminology
```

**Evidencia de que es DLIS, NO LIS:**

| Indicador | Valor | Significado |
|-----------|-------|-------------|
| Bytes 24-29 | `20 20 20 31 56 31` | "   1V1" = DLIS sequence |
| Bytes 30-34 | `2e 30 30 52 45` | ".00RE" = Version 1.00 |
| Bytes 35-40 | `43 4f 52 44 20` | "CORD " = RECORD keyword |
| Bytes 41-46 | `38 31 39 32` | "8192" = Record size |
| Bytes 47-66 | "Default Storage Set" | Terminología DLIS estándar |

**Causa raíz:**
- ❌ El archivo tiene extensión `.lis` pero es formato **DLIS**
- ❌ El script prioriza extensión sobre contenido
- ❌ dlisio.lis falla porque intenta leer DLIS como LIS
- ❌ El fallback de strings ASCII no encuentra metadata porque la estructura es DLIS

**Resultado del fallback:**
- ❌ **0 curvas** extraídas
- ❌ **Sin metadata** de pozo
- ❌ Solo información básica del archivo

### Detección Incorrecta

**Código actual (líneas 231-244):**
```python
if file_ext_lower.startswith('.lis'):
    logging.info(f"Extensión '{file_ext_lower}' sugiere formato LIS. Priorizando detección binaria LIS.")
    # Verifica estructura LIS...
```

**Problema:**
El script verifica la extensión ANTES de verificar firmas DLIS, causando falsos positivos.

**Orden actual de detección:**
1. ✅ Extensión .las → Detecta como LAS
2. ⚠️ Extensión .lis → Prioriza detección LIS (ERROR)
3. ✅ Firma DLIS → Detecta DLIS
4. ✅ Fallback a estructura LIS

**Orden correcto debería ser:**
1. ✅ Verificar firmas binarias (DLIS, LIS) primero
2. ✅ Verificar extensión como sugerencia secundaria
3. ✅ Usar extensión solo como último recurso

### Recomendaciones

#### 🔧 Fix Inmediato (Alta Prioridad)

**Modificar detección para verificar DLIS antes que extensión:**

```python
def detect_file_format(path: Path) -> str:
    # 1. Verificar corrupción primero
    if is_corrupted_or_wrong_format(path):
        return 'unknown'

    file_ext_lower = path.suffix.lower()

    # 2. Leer header binario
    with path.open("rb") as f:
        header = f.read(512)

    # 3. PRIMERO verificar firmas DLIS (antes de extensión)
    if len(header) >= 80:
        # Buscar firma "V1.00" o "V2.00"
        if b'V1.00' in header[:80] or b'V2.00' in header[:80]:
            logging.info(f"'{path.name}' detectado como DLIS por firma de versión")
            return 'dlis'

        # Buscar "RECORD" keyword
        if b'RECORD' in header[:80]:
            logging.info(f"'{path.name}' detectado como DLIS por keyword RECORD")
            return 'dlis'

    # 4. DESPUÉS verificar estructura LIS
    if _detect_lis_prh(header):
        logging.info(f"'{path.name}' detectado como LIS por estructura PRH")
        return 'lis'

    # 5. Extensión como último recurso
    # ... resto del código
```

#### 📊 Mejoras Adicionales

1. **Agregar detección de DLIS con extensión .lis:**
   ```python
   if file_ext_lower.endswith('.lis') and is_actually_dlis(header):
       logging.warning(f"'{path.name}' tiene extensión .lis pero es formato DLIS")
       return 'dlis'
   ```

2. **Validar formato después de detección:**
   ```python
   detected_format = detect_file_format(path)
   if not validate_format(path, detected_format):
       logging.error(f"Formato {detected_format} no válido, reintentando detección...")
   ```

3. **Agregar estadísticas de confianza:**
   ```python
   return {
       'format': 'dlis',
       'confidence': 0.95,
       'method': 'binary_signature',
       'note': 'Extension mismatch: .lis'
   }
   ```

---

## 📊 Resumen de Resultados

| Archivo | Formato Real | Extensión | Detección | Curvas | Estado |
|---------|-------------|-----------|-----------|--------|--------|
| 13_LOS-CEDROS-1_1469_LIS_8418.LIS | LIS | .LIS | ✅ Correcto | 482 | ⚠️ Corrupto parcial |
| 13_TOCORAGUA-1_7658_83999_SEIS.lis | DLIS | .lis | ❌ Incorrecto | 0 | ❌ Mal detectado |

---

## 🎯 Plan de Acción

### Prioridad Alta (Implementar YA)
- [ ] Reordenar lógica de detección: firmas binarias ANTES que extensión
- [ ] Agregar detección específica de DLIS con extensión .lis
- [ ] Agregar warning cuando extensión no coincide con formato

### Prioridad Media (Siguiente Sprint)
- [ ] Agregar validación de formato post-detección
- [ ] Implementar recuperación progresiva de archivos LIS parciales
- [ ] Agregar métricas de confianza en detección

### Prioridad Baja (Futuro)
- [ ] Crear tests unitarios con estos archivos
- [ ] Documentar casos edge conocidos
- [ ] Agregar telemetría de errores comunes

---

## 🧪 Archivos de Prueba Generados

```
test_output/test_input/
├── 13_LOS-CEDROS-1_1469_LIS_8418.json              38 KB  ✅
├── 13_LOS-CEDROS-1_1469_LIS_8418_metadata.md       39 KB  ✅
├── 13_LOS-CEDROS-1_1469_LIS_8418_osdu.json         13 KB  ✅
├── 13_TOCORAGUA-1_7658_83999_SEIS.json            680 B  ⚠️ (sin curvas)
├── 13_TOCORAGUA-1_7658_83999_SEIS_metadata.md     1.4 KB ⚠️ (sin curvas)
└── 13_TOCORAGUA-1_7658_83999_SEIS_osdu.json       643 B  ⚠️ (sin curvas)
```

---

## 💡 Conclusiones

1. **El fallback de extracción de strings ASCII funciona bien** para archivos LIS corruptos parcialmente
2. **La detección basada en extensión causa falsos positivos** cuando archivos tienen extensiones incorrectas
3. **Se necesita priorizar firmas binarias sobre extensión de archivo**
4. **El archivo TOCORAGUA-1 necesita ser reprocesado como DLIS** para extraer sus datos correctamente

---

## 📝 Próximos Pasos

1. Implementar el fix de detección de formato
2. Reprocesar `13_TOCORAGUA-1_7658_83999_SEIS.lis` como DLIS
3. Crear tests automatizados con estos casos
4. Actualizar documentación con casos edge conocidos
