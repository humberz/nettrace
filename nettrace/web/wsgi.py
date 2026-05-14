#!/usr/bin/env python3
"""
WSGI entry point for gunicorn.
Starts the collector threads when gunicorn loads this module.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector.collector import start_collector
from web.app import app

# Start collector threads once on first worker load
start_collector()

# Gunicorn looks for `application` or the name you pass (wsgi:app)
application = app
