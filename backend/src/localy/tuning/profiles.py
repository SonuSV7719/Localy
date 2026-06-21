"""
Tuning profiles — conservative, balanced, aggressive presets.

Each profile adjusts how aggressively the auto-tuner uses system resources.
"""

from __future__ import annotations

from dataclasses import dataclass

from localy.core.config import TuningProfile


@dataclass(frozen=True)
class ProfileDescription:
    """Human-readable profile description for the UI."""

    name: str
    profile: TuningProfile
    description: str
    tradeoff: str
    recommended_for: str


PROFILE_DESCRIPTIONS: dict[TuningProfile, ProfileDescription] = {
    TuningProfile.CONSERVATIVE: ProfileDescription(
        name="Conservative",
        profile=TuningProfile.CONSERVATIVE,
        description="Maximum system responsiveness. Leaves headroom for other applications.",
        tradeoff="Slightly slower inference in exchange for smooth multitasking.",
        recommended_for="Users who chat while working in other apps.",
    ),
    TuningProfile.BALANCED: ProfileDescription(
        name="Balanced (Recommended)",
        profile=TuningProfile.BALANCED,
        description="Best tradeoff between inference speed and system responsiveness.",
        tradeoff="Good inference speed with reasonable system responsiveness.",
        recommended_for="Most users. Default setting.",
    ),
    TuningProfile.AGGRESSIVE: ProfileDescription(
        name="Aggressive",
        profile=TuningProfile.AGGRESSIVE,
        description="Maximum inference speed. Uses all available resources.",
        tradeoff="Fastest possible inference, but system may feel sluggish during generation.",
        recommended_for="Users who prioritize speed and aren't multitasking.",
    ),
}
