"""
SnapMem: Snapchat Memories downloader.

The executable entrypoint remains `Downloader.py` at the repo root, which
imports and calls `sc_memories_downloader.main:main`.
"""

from ._version import __version__

__all__ = ["__version__"]
