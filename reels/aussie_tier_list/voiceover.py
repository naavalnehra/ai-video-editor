"""Generate per-scene voiceover MP3s plus word timings with edge-tts."""

import asyncio
import json
import sys
from pathlib import Path

import edge_tts

from script import RATE, SCENES, VOICE

OUT = Path(__file__).resolve().parents[2] / "output" / "aussie_tier_list" / "vo"


async def synth(scene):
    comm = edge_tts.Communicate(scene["line"], VOICE, rate=RATE, boundary="WordBoundary")
    audio = bytearray()
    words = []
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            # offsets are in 100ns ticks
            words.append({
                "text": chunk["text"],
                "start": chunk["offset"] / 1e7,
                "end": (chunk["offset"] + chunk["duration"]) / 1e7,
            })
    (OUT / f"{scene['id']}.mp3").write_bytes(audio)
    (OUT / f"{scene['id']}.json").write_text(json.dumps(words, indent=1))
    print(f"{scene['id']}: {len(words)} words", file=sys.stderr)


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for scene in SCENES:
        if (OUT / f"{scene['id']}.json").exists():
            continue
        for attempt in range(4):
            try:
                await synth(scene)
                break
            except edge_tts.exceptions.NoAudioReceived:
                await asyncio.sleep(2 + attempt * 2)
        else:
            raise SystemExit(f"TTS failed for {scene['id']}")


if __name__ == "__main__":
    asyncio.run(main())
