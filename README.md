# AI Video Editor

Scripted vertical reels (1080x1920, 30fps). Each reel is generated from code:
edge-tts voices the script, Pillow draws every frame, and ffmpeg encodes the video.

## Requirements

- Windows (render scripts load fonts from `C:/Windows/Fonts`: Impact, Segoe UI Black,
  Segoe UI Bold, Segoe UI Emoji)
- Python 3 (developed on 3.15)
- [ffmpeg](https://www.gyan.dev/ffmpeg/builds/) on `PATH`
- Internet access for voiceover generation (edge-tts uses Microsoft's online voices)

## Setup

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
```

## Making a reel

Each folder in `reels/` is one reel:

| File | Purpose |
| --- | --- |
| `script.py` | Voice, speaking rate and the scene lines, with cue words that sync visuals to speech |
| `voiceover.py` | Generates one MP3 plus word timings per scene into `output/<reel>/vo/` (skips scenes already done) |
| `render.py` | Mixes audio, draws the frames and writes the MP4 to `output/<reel>/` |

Run them from the reel's folder, voiceover first:

```bash
cd reels/daintree_night
../../.venv/Scripts/python voiceover.py
../../.venv/Scripts/python render.py
```

`render.py --preview 3 12.5` writes PNG stills at those timestamps instead of the full video.
To redo a scene's voiceover after editing its line, delete its `.json` in `output/<reel>/vo/`.

## Reels

| Folder | Reel |
| --- | --- |
| `airplane_food` | Why airplane food tastes bland |
| `raccoon_vs_spider` | Your raccoon vs our spider (USA vs Australia) |
| `daintree_night` | $1 million to spend one night in the Daintree |

Generated media in `output/` is git-ignored.
