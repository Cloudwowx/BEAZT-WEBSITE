import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

INTERP = os.path.expanduser("~/virtualenv/site/3.10/bin/python")
if sys.executable != INTERP:
    import subprocess
    subprocess.call([INTERP, __file__] + sys.argv[1:])
    sys.exit(0)

from app import app as application
