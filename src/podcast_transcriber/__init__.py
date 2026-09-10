"""Automated podcast transcriber + summarizer.

Stage 1 (this checkpoint): Spotify trigger — authorize, then fetch recently
played podcast episodes and track which have already been processed.

Later stages (fetch audio, transcribe, summarize, deliver) will hang off the
episode records this stage produces.
"""

__version__ = "0.1.0"
