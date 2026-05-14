#!/usr/bin/env python3
"""
NetTrace — entry point.
Starts the collector threads + Flask web server.
"""
import sys
import os

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from web.app import main

if __name__ == "__main__":
    main()
