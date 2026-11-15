"""
WSGI config for Ticketmitra project.

Exposes the WSGI callable as module-level variable named ``application`` and ``app``.
"""

import logging
import os
import sys
from pathlib import Path

# Ensure the project root is in sys.path so Ticketmitra and apps can be imported on Vercel
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Ticketmitra.settings')

try:
    from django.core.wsgi import get_wsgi_application
    application = get_wsgi_application()
    app = application
except Exception as exc:
    import traceback
    traceback.print_exc()
    raise exc
