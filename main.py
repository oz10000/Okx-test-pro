#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
main.py - Punto de entrada principal del bot OKX.
Delega completamente la ejecución en el módulo runner/main.py.
Elimina duplicación y resuelve errores de importación.
"""

import os
import sys
import logging

# Asegurar que el directorio raíz esté en el path de Python
root_dir = os.path.dirname(os.path.abspath(__file__))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

# Importar y ejecutar el runner principal
try:
    from runner.main import main
except ImportError as e:
    logging.error(f"❌ Error al importar runner.main: {e}")
    logging.error("Asegúrate de que el directorio 'runner/' existe y contiene main.py")
    sys.exit(1)

if __name__ == "__main__":
    main()
