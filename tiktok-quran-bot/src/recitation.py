"""Recitation selection.

Reads the user-prepared ``metadata.json``, validates each entry, measures its
audio duration, keeps only entries that fit the configured max duration, and
rotates through them across days using a small JSON state file.

AMANAH: this module never creates or alters Qur'anic text or audio. It only
reads the user's verified files. Any entry missing its audio file or a non-empty
``text_ar`` is skipped so unverified content is never published.

The pure selection logic (`filter_eligible`, `choose`) has no side effects and is
unit-tested.
"""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import media

logger = logging.getLogger(__name__)


@dataclass
class Recitation:
    id: str
    file: Path
    text_ar: str
    reciter: str = ""
    surah: str = ""
    ayah_range: str = ""
    segments: List[Dict[str, Any]] = field(default_factory=list)
    duration: Optional[float] = None


class NoEligibleRecitationError(RuntimeError):
    """Raised when no recitation passes validation / the duration cap."""


def _valid_segments(raw: Any) -> List[Dict[str, Any]]:
    """Keep only well-formed segments (numeric start<=end, non-empty text)."""
    segments: List[Dict[str, Any]] = []
    if not isinstance(raw, list):
        return segments
    for seg in raw:
        if not isinstance(seg, dict):
            continue
        start, end, text = seg.get("start"), seg.get("end"), seg.get("text_ar")
        if not isinstance(text, str) or not text.strip():
            continue
        try:
            start_f, end_f = float(start), float(end)
        except (TypeError, ValueError):
            continue
        if end_f <= start_f:
            continue
        segments.append({"start": start_f, "end": end_f, "text_ar": text.strip()})
    segments.sort(key=lambda s: s["start"])
    return segments


def load_recitations(config: Dict[str, Any]) -> List[Recitation]:
    """Parse metadata.json into validated Recitation objects (durations not yet
    probed). Entries missing their audio file or verified text are skipped."""
    metadata_file = Path(config["paths"]["metadata_file"])
    recitations_dir = Path(config["paths"]["recitations_dir"])

    if not metadata_file.exists():
        raise FileNotFoundError(
            f"Recitation metadata not found: {metadata_file}. Copy "
            f"metadata.example.json to metadata.json and fill in your verified content."
        )

    with open(metadata_file, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    entries = data.get("recitations", [])
    result: List[Recitation] = []
    for entry in entries:
        rec_id = str(entry.get("id") or "").strip()
        file_name = str(entry.get("file") or "").strip()
        text_ar = str(entry.get("text_ar") or "").strip()

        if not rec_id or not file_name:
            logger.warning("Skipping recitation with missing id/file: %r", entry)
            continue
        if not text_ar:
            logger.warning("Skipping %s: empty text_ar (amanah: text must be verified)", rec_id)
            continue

        audio_path = Path(file_name)
        if not audio_path.is_absolute():
            audio_path = recitations_dir / audio_path
        if not audio_path.exists():
            logger.warning("Skipping %s: audio file not found at %s", rec_id, audio_path)
            continue

        result.append(
            Recitation(
                id=rec_id,
                file=audio_path,
                text_ar=text_ar,
                reciter=str(entry.get("reciter") or ""),
                surah=str(entry.get("surah") or ""),
                ayah_range=str(entry.get("ayah_range") or ""),
                segments=_valid_segments(entry.get("segments")),
            )
        )
    return result


def filter_eligible(recitations: Sequence[Recitation], max_seconds: float) -> List[Recitation]:
    """Return recitations whose measured duration is within the cap.

    Requires each recitation.duration to already be set.
    """
    eligible: List[Recitation] = []
    for rec in recitations:
        if rec.duration is None:
            continue
        if rec.duration <= max_seconds:
            eligible.append(rec)
        else:
            logger.info(
                "Skipping %s: duration %.1fs exceeds max %.1fs",
                rec.id, rec.duration, max_seconds,
            )
    return eligible


def choose(
    eligible_ids: Sequence[str],
    used_ids: Sequence[str],
    mode: str,
    rng: Optional[random.Random] = None,
) -> Tuple[str, List[str]]:
    """Pure selection. Returns (chosen_id, new_used_ids).

    - random_no_repeat: pick randomly among ids not used in the current cycle;
      when the cycle is exhausted it resets.
    - sequential: advance to the id after the last-used one (metadata order).
    """
    if not eligible_ids:
        raise NoEligibleRecitationError("No eligible recitations to choose from")

    rng = rng or random.Random()
    eligible = list(eligible_ids)

    if mode == "sequential":
        last = used_ids[-1] if used_ids else None
        if last in eligible:
            idx = (eligible.index(last) + 1) % len(eligible)
        else:
            idx = 0
        chosen = eligible[idx]
        return chosen, [chosen]

    # Default: random_no_repeat
    used_in_cycle = [i for i in used_ids if i in eligible]
    available = [i for i in eligible if i not in used_in_cycle]
    if not available:  # cycle complete -> reset
        used_in_cycle = []
        available = list(eligible)
    chosen = rng.choice(available)
    return chosen, used_in_cycle + [chosen]


def _read_state(state_file: Path) -> Dict[str, Any]:
    if not state_file.exists():
        return {"used": []}
    try:
        with open(state_file, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return {"used": []}
        data.setdefault("used", [])
        return data
    except (json.JSONDecodeError, OSError):
        logger.warning("State file %s unreadable; starting fresh", state_file)
        return {"used": []}


def _write_state(state_file: Path, used_ids: List[str]) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    with open(state_file, "w", encoding="utf-8") as fh:
        json.dump({"used": used_ids}, fh, ensure_ascii=False, indent=2)


def select_recitation(config: Dict[str, Any]) -> Recitation:
    """End-to-end selection: load, probe durations, filter, rotate, persist state."""
    recitations = load_recitations(config)
    if not recitations:
        raise NoEligibleRecitationError(
            "No valid recitations found. Add mp3 files and verified text_ar to metadata.json."
        )

    for rec in recitations:
        rec.duration = media.probe_duration_seconds(rec.file)

    max_seconds = float(config["duration"]["max_seconds"])
    eligible = filter_eligible(recitations, max_seconds)
    if not eligible:
        raise NoEligibleRecitationError(
            f"No recitation is within the {max_seconds:.0f}s cap. "
            f"Increase duration.max_seconds or add shorter recitations."
        )

    state_file = Path(config["paths"]["state_file"])
    state = _read_state(state_file)
    mode = config["recitation"].get("selection_mode", "random_no_repeat")

    eligible_by_id = {rec.id: rec for rec in eligible}
    chosen_id, new_used = choose(list(eligible_by_id.keys()), state.get("used", []), mode)
    _write_state(state_file, new_used)

    chosen = eligible_by_id[chosen_id]
    logger.info(
        "Selected recitation %s (%s %s, %.1fs)",
        chosen.id, chosen.surah, chosen.ayah_range, chosen.duration or 0.0,
    )
    return chosen
