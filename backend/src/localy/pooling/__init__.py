"""
Localy device pooling (Phase 3).

Orchestrates llama.cpp's RPC backend to run models too large for a single
device by splitting model layers across multiple machines on a LAN/hotspot.

Solo inference (llama-cpp-python) is unaffected — pooling is additive and
opt-in. This package only manages the *orchestration* layer: worker/coordinator
subprocess lifecycles, RAM-weighted shard planning, and peer discovery. All
distributed execution is delegated to proven llama.cpp binaries.
"""

from __future__ import annotations
