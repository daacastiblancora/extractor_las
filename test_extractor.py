#!/usr/bin/env python3
"""
Script de prueba para procesar los archivos .lis específicos
"""
import sys
import os

# Modificar las rutas de configuración para testing
test_dir = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(test_dir, "test_input")
OUT_DIR = os.path.join(test_dir, "test_output")
STATE_FILE = os.path.join(test_dir, "test_state.txt")
UNPROCESSED_STATE_FILE = os.path.join(test_dir, "test_unprocessed.txt")

# Actualizar las variables en el módulo principal
import extractor_las_corregido_v3 as extractor

# Sobrescribir las configuraciones
extractor.INPUT_DIR = INPUT_DIR
extractor.OUT_DIR = OUT_DIR
extractor.STATE_FILE = STATE_FILE
extractor.UNPROCESSED_STATE_FILE = UNPROCESSED_STATE_FILE

print(f"[TEST CONFIG]")
print(f"  Input:  {INPUT_DIR}")
print(f"  Output: {OUT_DIR}")
print(f"  State:  {STATE_FILE}")
print()

# Ejecutar el main
if __name__ == "__main__":
    extractor.main()
