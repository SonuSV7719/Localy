# Localy — Fast, Accessible Local LLM Platform
# https://github.com/localy-ai/localy

"""
Localy: Auto-tuned local LLM inference with honest hardware-fit advising.

This is the orchestration layer on top of llama.cpp — it does not reimplement
inference kernels. Value comes from automatic per-machine optimization, a
friendly interface, and seamless device pooling.
"""

from localy.version import __version__

__all__ = ["__version__"]
