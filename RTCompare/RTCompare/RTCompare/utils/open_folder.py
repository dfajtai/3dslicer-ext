import subprocess
import sys
import os

def open_folder(path):
    if sys.platform == "win32":
        # Windows
        os.startfile(path)
    elif sys.platform == "darwin":
        # macOS
        subprocess.Popen(["open", path])
    else:
        # Linux/Unix
        subprocess.Popen(["xdg-open", path])