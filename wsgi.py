"""
WSGI configuration for PythonAnywhere.
Pegar este contenido en el WSGI configuration file de la pestana Web.
"""

import sys
import os

# Path al proyecto (ajustar si tu username es distinto)
project_home = '/home/hierronort/hierronort-webapp'
if project_home not in sys.path:
    sys.path.insert(0, project_home)

# Cargar la app Flask
from app import app as application
