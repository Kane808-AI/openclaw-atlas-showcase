#!/usr/bin/env python3
"""DEPRECATED: Use reauth_personal.py instead.

This script previously only requested gmail.modify scope, producing tokens
that broke Calendar/Drive/Sheets/Docs access. It now redirects to
reauth_personal.py which requests all 7 required scopes.
"""

import subprocess
import sys
from pathlib import Path

print("This script is deprecated. Redirecting to reauth_personal.py (all scopes)...\n")
sys.exit(subprocess.call([
    sys.executable,
    str(Path(__file__).parent / "reauth_personal.py"),
]))
