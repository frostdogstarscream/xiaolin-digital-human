"""UE4 editor entrypoint. Imports to a fresh folder; never registers a live avatar."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ue_import_character import import_character

if __name__ == '__main__':
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    import_character(os.path.join(root, 'assets', 'girl008-preview.json'), preview=True)
