#!/usr/bin/env python3
"""
Hermes Switch — standalone launcher
Usage: python run.py [port]
Delegates to the hermes_switch package.
"""
import sys, os
sys.dont_write_bytecode = True

# Ensure package is importable
sys.path.insert(0, os.path.dirname(__file__))

from hermes_switch.server import run_server
from hermes_switch import _cmd_web

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else None
    _cmd_web(port)
