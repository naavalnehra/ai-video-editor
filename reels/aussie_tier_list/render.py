"""Render the 'Aussie animals ranked by how dead you'd be' reel (1080x1920, 30fps).

Brainrot layout: S-to-F tier board on top, an endless-runner "gameplay" clip on the
bottom (a kangaroo hopping across rooftops), big punchy captions across the seam.
Each animal gets a card with a "how dead" meter, then slams into its tier row.
Run voiceover.py first. Frames are drawn with Pillow and piped straight into ffmpeg.
Usage: python render.py [--preview SECONDS ...]   (preview writes PNG stills instead)
"""

import json
import math
import random
import re
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from script import SCENES, TIERS

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output" / "aussie_tier_list"
VO = OUT / "vo"

W, H, FPS = 1080, 1920, 30
SR = 48000
PAD = 0.25  # silence after each scene's line
SPLIT = 1060  # tier board above, gameplay below
FLY = 0.32  # card-to-slot flight, lands on the tier letter

FONTS = Path("C:/Windows/Fonts")
IMPACT = str(FONTS / "impact.ttf")
BOLD = str(FONTS / "seguibl.ttf")
SEMI = str(FONTS / "segoeuib.ttf")
EMOJI = str(FONTS / "seguiemj.ttf")

WHITE = (255, 255, 255)
INK = (10, 10, 16)
YELLOW = (255, 230, 0)
RED = (255, 60, 60)
TIER_COL = {
    "S": (255, 82, 82), "A": (255, 160, 64), "B": (255, 222, 90),
    "C": (126, 222, 112), "D": (96, 172, 255), "F": (186, 124, 255),
}
REACTION = {"S": "💀", "A": "☠", "B": "😰", "C": "😬", "D": "🤕", "F": "😂"}

# tier board geometry
BY0, RH, RGAP = 178, 138, 6
LX0, LX1 = 30, 180
CX0, CX1 = 190, 1050
TILE = 124

_font_cache = {}
_emoji_cache = {}


def font(path, size):
    key = (path, size)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(path, size)
    return _font_cache[key]


def fit_font(d, text, path, size, max_w, min_size=28):
    while size > min_size and d.textlength(text, font=font(path, size)) > max_w:
        size -= 2
    return font(path, size)


# ---------- easing ----------

def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def ease_out(x):
    x = clamp(x)
    return 1 - (1 - x) ** 3


def ease_in(x):
    x = clamp(x)
    return x ** 3


def ease_back(x):
    x = clamp(x)
    c = 1.70158
    return 1 + (c + 1) * (x - 1) ** 3 + c * (x - 1) ** 2


def prog(t, start, dur):
    return clamp((t - start) / dur)


# ---------- timeline ----------

def norm(word):
    return re.sub(r"[^a-z0-9]", "", word.lower())


def cue_time(words, cue):
    for w in words:
        if norm(w["text"]).startswith(cue):
            return w["start"]
    raise SystemExit(f"cue word {cue!r} not found in voiceover")


def tier_word_index(words):
    """Index of the tier letter: the word right before the last 'tier'."""
    idx = max(i for i, w in enumerate(words) if norm(w["text"]) == "tier")
    return idx - 1


def load_timeline():
    scenes, t = [], 0.0
    counts = {k: 0 for k in TIERS}
    for s in SCENES:
        audio = decode(VO / f"{s['id']}.mp3")
        words = json.loads((VO / f"{s['id']}.json").read_text())
        dur = len(audio) / SR + PAD
        cues = {}
        if "tier" in s:
            cues["land"] = words[tier_word_index(words)]["start"]
            cues["appear"] = cue_time(words, s["appear"]) - 0.1 if "appear" in s else 0.0
            s = {**s, "slot": (TIERS.index(s["tier"]), counts[s["tier"]])}
            counts[s["tier"]] += 1
        if s["id"] == "hook":
            for k in ("ranked", "dead", "last"):
                cues[k] = cue_time(words, k)
        if s["id"] == "jelly":
            cues["follow"] = cue_time(words, "follow")
        scenes.append({**s, "start": t, "dur": dur, "audio": audio, "words": words, "cue_t": cues})
        t += dur
    return scenes, t


def decode(path):
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
        check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def landings(scenes):
    """Absolute (time, scene) for every animal slamming into the board."""
    return [(s["start"] + s["cue_t"]["land"], s) for s in scenes if "tier" in s]


def chunk_words(words):
    """Brainrot captions: one or two words at a time, split at pauses."""
    chunks, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        pause = nxt is not None and nxt["start"] - w["end"] > 0.15
        long_word = len(w["text"]) > 7
        if len(cur) >= 2 or pause or long_word or nxt is None or norm(nxt["text"]) == "tier":
            chunks.append(cur)
            cur = []
    return chunks


# ---------- audio ----------

def tone_env(n, decay):
    return np.exp(-np.arange(n) / SR * decay)


def build_audio(scenes, total):
    n = int(total * SR) + SR
    voice = np.zeros(n, np.float32)
    for s in scenes:
        i = int(s["start"] * SR)
        voice[i:i + len(s["audio"])] += s["audio"]

    rng = np.random.default_rng(23)

    def add(buf, at, sig, gain):
        i = int(at * SR)
        if i >= n:
            return
        m = min(len(sig), n - i)
        buf[i:i + m] += gain * sig[:m]

    # Phonk loop at 130 bpm: kick + 808, snare on 2 and 4, cowbell riff in 16ths.
    music = np.zeros(n, np.float32)
    beat = 60 / 130
    six = beat / 4
    kl = int(0.35 * SR)
    kt = np.arange(kl) / SR
    kick = np.tanh(2.5 * np.sin(2 * np.pi * np.cumsum(48 + 110 * np.exp(-kt * 35)) / SR)) * tone_env(kl, 9)
    bl = int(0.9 * SR)
    bt = np.arange(bl) / SR
    sl = int(0.18 * SR)
    snare = (rng.standard_normal(sl) * 0.7 + np.sin(2 * np.pi * 190 * np.arange(sl) / SR)) * tone_env(sl, 22)
    cl = int(0.16 * SR)
    ct = np.arange(cl) / SR

    def cowbell(f):
        sq = np.sign(np.sin(2 * np.pi * f * ct)) + np.sign(np.sin(2 * np.pi * f * 1.48 * ct))
        sq = np.convolve(sq, np.ones(3) / 3, mode="same")
        return sq * tone_env(cl, 26)

    scale = [587.3, 659.3, 698.5, 784.0, 880.0, 1046.5]
    riff = [5, None, 4, 3, None, 3, 4, None, 2, None, 3, 2, 0, None, 1, None,
            5, None, 4, 3, None, 3, 4, 5, 4, None, 3, None, 2, 1, 0, None]
    bells = {f: cowbell(scale[f]) for f in set(r for r in riff if r is not None)}
    bass_notes = [55.0, 55.0, 49.0, 41.2]
    k = 0
    while k * six < total:
        at = k * six
        step16 = k % 16
        bar = (k // 16) % 4
        if step16 in (0, 6, 10):
            add(music, at, kick, 0.5)
        if step16 in (0, 10):
            f0 = bass_notes[bar]
            bass = np.tanh(1.8 * np.sin(2 * np.pi * f0 * bt)) * tone_env(bl, 3.2)
            add(music, at, bass, 0.32)
        if step16 in (4, 12):
            add(music, at, snare, 0.22)
        if step16 % 2 == 1:
            add(music, at, rng.standard_normal(int(0.03 * SR)) * tone_env(int(0.03 * SR), 120), 0.05)
        note = riff[k % len(riff)]
        if note is not None:
            add(music, at, bells[note], 0.075)
        k += 1

    fx = np.zeros(n, np.float32)
    # whoosh on each scene change and each card flight
    def whoosh(length):
        wl = int(length * SR)
        env = np.sin(np.linspace(0, np.pi, wl)) ** 2
        return np.convolve(rng.standard_normal(wl), np.ones(8) / 8, mode="same") * env
    for s in scenes[1:]:
        add(fx, s["start"] - 0.15, whoosh(0.4), 0.18)
    # vine-boom on every landing, a heavier distorted one for S tier
    vl = int(1.6 * SR)
    vt = np.arange(vl) / SR
    boom = np.sin(2 * np.pi * np.cumsum(46 + 70 * np.exp(-vt * 14)) / SR)
    boom += 0.5 * np.sin(2 * np.pi * np.cumsum(92 + 140 * np.exp(-vt * 14)) / SR)
    boom = np.tanh(3 * boom) * tone_env(vl, 2.6)
    boom += 0.3 * rng.standard_normal(vl) * tone_env(vl, 30)
    for lt, s in landings(scenes):
        add(fx, lt - FLY, whoosh(FLY + 0.05), 0.14)
        add(fx, lt, boom, 0.62 if s["tier"] == "S" else 0.42)
    # drumroll while the final card is still a mystery
    jelly = next(s for s in scenes if s["id"] == "jelly")
    r0, r1 = jelly["start"], jelly["start"] + jelly["cue_t"]["appear"]
    hit = rng.standard_normal(int(0.05 * SR)) * tone_env(int(0.05 * SR), 60)
    t = r0
    while t < r1:
        add(fx, t, hit, 0.05 + 0.12 * (t - r0) / max(0.1, r1 - r0))
        t += 0.045

    # duck music under the voice
    vol = np.convolve(np.abs(voice), np.ones(2400) / 2400, mode="same")
    duck = 1 - 0.6 * np.clip(vol / (vol.max() * 0.25 + 1e-9), 0, 1)

    mix = voice * 1.0 + music * duck + fx
    fade = int(0.8 * SR)
    end = int(total * SR)
    mix[end - fade:end] *= np.linspace(1, 0, fade)
    mix = mix[:end]
    mix /= max(1.0, np.abs(mix).max() / 0.95)

    pcm = (mix * 32767).astype(np.int16)
    stereo = np.repeat(pcm[:, None], 2, axis=1)
    path = OUT / "mix.wav"
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(stereo.tobytes())
    return path


# ---------- drawing helpers ----------

def with_alpha(layer, a):
    if a >= 1:
        return layer
    alpha = layer.getchannel("A").point(lambda v: int(v * clamp(a)))
    layer.putalpha(alpha)
    return layer


def text_center(d, cx, y, text, f, fill, stroke=0, stroke_fill=INK, anchor="mt"):
    d.text((cx, y), text, font=f, fill=fill, anchor=anchor,
           stroke_width=stroke, stroke_fill=stroke_fill)


def rrect(d, box, r, **kw):
    d.rounded_rectangle(box, radius=r, **kw)


def emoji_img(ch, size=280, mirror=False, tint=None, rings=False):
    key = (ch, size, mirror, tint, rings)
    if key not in _emoji_cache:
        f = font(EMOJI, size)
        probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        x0, y0, x1, y1 = probe.textbbox((0, 0), ch, font=f, embedded_color=True)
        im = Image.new("RGBA", (x1 - x0 + 8, y1 - y0 + 8), (0, 0, 0, 0))
        ImageDraw.Draw(im).text((4 - x0, 4 - y0), ch, font=f, embedded_color=True)
        if tint:  # recolour by luminance so one emoji can stand in for another species
            a = np.asarray(im).astype(np.float32)
            lum = (a[..., 0] * 0.3 + a[..., 1] * 0.59 + a[..., 2] * 0.11) / 255
            rgb = np.clip(np.array(tint)[None, None, :] * (0.45 + 1.1 * lum[..., None]), 0, 255)
            im = Image.fromarray(np.dstack([rgb, a[..., 3:]]).astype(np.uint8), "RGBA")
        if rings:  # electric-blue rings for the blue-ringed octopus
            d = ImageDraw.Draw(im)
            rnd = random.Random(4)
            for _ in range(9):
                cx = im.width * rnd.uniform(0.25, 0.75)
                cy = im.height * rnd.uniform(0.15, 0.6)
                r = im.width * rnd.uniform(0.035, 0.06)
                d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(20, 90, 255), width=max(3, int(r * 0.45)))
        if mirror:
            im = im.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        _emoji_cache[key] = im
    return _emoji_cache[key]


def animal_img(scene, size=280):
    return emoji_img(scene["emoji"], size, tint=scene.get("tint"), rings=scene.get("rings", False))


def paste_center(layer, im, cx, cy, scale=1.0, alpha=1.0, angle=0.0):
    if scale <= 0.01 or alpha <= 0:
        return
    if scale != 1:
        im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.LANCZOS)
    if angle:
        im = im.rotate(angle, resample=Image.BICUBIC, expand=True)
    if alpha < 1:
        im = with_alpha(im.copy(), alpha)
    x, y = int(cx - im.width / 2), int(cy - im.height / 2)
    if x >= 0 and y >= 0 and x + im.width <= layer.width and y + im.height <= layer.height:
        layer.alpha_composite(im, (x, y))
    else:
        tmp = Image.new("RGBA", layer.size, (0, 0, 0, 0))
        tmp.paste(im, (x, y))
        layer.alpha_composite(tmp)


EMOJI_RE = re.compile("[\u2300-\u23ff\u2600-\u27bf\U0001F000-\U0001FFFF]")


def text_with_emoji(layer, cx, cy, text, f, fill, stroke=0):
    """Centre a line mixing text and emoji (Pillow can't fall back between fonts)."""
    d = ImageDraw.Draw(layer)
    parts = [p for p in re.split(f"({EMOJI_RE.pattern})", text) if p]
    size = f.size
    widths = [size * 1.1 if EMOJI_RE.fullmatch(p) else d.textlength(p, font=f) for p in parts]
    x = cx - sum(widths) / 2
    for p, wd in zip(parts, widths):
        if EMOJI_RE.fullmatch(p):
            paste_center(layer, emoji_img(p, 120), x + wd / 2, cy, scale=size / 120 * 0.85)
        else:
            d.text((x, cy), p, font=f, fill=fill, anchor="lm", stroke_width=stroke, stroke_fill=INK)
        x += wd


def row_box(row):
    y0 = BY0 + row * (RH + RGAP)
    return y0, y0 + RH


def slot_center(slot):
    row, i = slot
    y0, y1 = row_box(row)
    return CX0 + 30 + TILE / 2 + i * (TILE + 26), (y0 + y1) / 2


# ---------- tier board (top half) ----------

def make_top_bg():
    y = np.linspace(0, 1, SPLIT)[:, None, None]
    img = np.array([22, 20, 34]) + (np.array([12, 10, 18]) - np.array([22, 20, 34])) * y
    img = np.broadcast_to(img, (SPLIT, W, 3)).copy()
    return Image.fromarray(img.astype(np.uint8)).convert("RGBA")


def make_board(placed):
    """Board with the given scenes already sitting in their rows (cached per state)."""
    img = Image.new("RGBA", (W, SPLIT), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    text_center(d, W / 2, 34, "AUSSIE ANIMALS RANKED BY", font(IMPACT, 56), WHITE, stroke=4)
    text_center(d, W / 2, 92, "HOW DEAD YOU'D BE", font(IMPACT, 74), RED, stroke=5)
    for row, tier in enumerate(TIERS):
        y0, y1 = row_box(row)
        rrect(d, [LX0, y0, LX1, y1], 18, fill=TIER_COL[tier])
        text_center(d, (LX0 + LX1) / 2, (y0 + y1) / 2, tier, font(IMPACT, 104), INK, anchor="mm")
        rrect(d, [CX0, y0, CX1, y1], 18, fill=(38, 36, 52), outline=(70, 66, 92), width=2)
    for s in placed:
        draw_tile(img, s, *slot_center(s["slot"]))
    return img


def draw_tile(layer, s, cx, cy, scale=1.0):
    d = ImageDraw.Draw(layer)
    r = TILE / 2 * scale
    rrect(d, [cx - r, cy - r, cx + r, cy + r], int(18 * scale), fill=(255, 255, 255, 60),
          outline=TIER_COL[s["tier"]] + (160,), width=3)
    im = animal_img(s)
    paste_center(layer, im, cx, cy, scale=TILE * 0.82 * scale / max(im.size))


_board_cache = {}


def board_at(lands, t):
    placed = [s for lt, s in lands if t >= lt]
    key = len(placed)
    if key not in _board_cache:
        _board_cache[key] = make_board(placed)
    return _board_cache[key], placed


def dead_meter(layer, s, lt):
    d = ImageDraw.Draw(layer)
    fill_p = ease_out(prog(lt, s["cue_t"]["appear"] + 0.35, max(0.6, s["cue_t"]["land"] - FLY - 0.6
                                                               - s["cue_t"]["appear"])))
    val = s["dead"] * fill_p
    x0, x1, y = 110, W - 110, 860
    d.text((x0, y - 44), "HOW DEAD:", font=font(IMPACT, 58), fill=WHITE, anchor="lm",
           stroke_width=4, stroke_fill=INK)
    pct = f"{round(val * 100)}%"
    shake = (random.Random(int(lt * 30)).uniform(-4, 4) if s["dead"] > 0.9 and fill_p > 0.8 else 0)
    d.text((x1 + shake, y - 44 + shake), pct, font=font(IMPACT, 70),
           fill=RED if val > 0.6 else YELLOW, anchor="rm", stroke_width=4, stroke_fill=INK)
    rrect(d, [x0, y, x1, y + 58], 29, fill=(0, 0, 0, 200), outline=WHITE, width=4)
    fw = (x1 - x0 - 12) * val
    if fw > 4:
        col = tuple(int(a + (b - a) * val) for a, b in zip((90, 220, 90), (255, 40, 40)))
        rrect(d, [x0 + 6, y + 6, x0 + 6 + max(46, fw), y + 52], 23, fill=col)
    paste_center(layer, emoji_img("💀", 120), x0 + 6 + max(46, fw), y + 29, scale=0.62,
                 angle=math.sin(lt * 9) * 12)


def card(layer, s, lt):
    """The featured animal: name, big emoji, note and the 'how dead' meter."""
    a0 = s["cue_t"]["appear"]
    if lt < a0:  # suspense card for the finale
        pulse = 1 + 0.08 * math.sin(lt * 10)
        d = ImageDraw.Draw(layer)
        text_center(d, W / 2, 230, "#1 DEADLIEST", font(IMPACT, 110), RED, stroke=6)
        text_center(d, W / 2, 540, "?", font(IMPACT, int(330 * pulse)), WHITE, stroke=8, anchor="mm")
        return
    p = ease_back(prog(lt, a0, 0.4))
    d = ImageDraw.Draw(layer)
    nf = fit_font(d, s["name"], IMPACT, 104, W - 100)
    text_center(d, W / 2, 200 - (1 - p) * 60, s["name"], nf, WHITE, stroke=6)
    bob = math.sin(lt * 4) * 12
    paste_center(layer, animal_img(s), W / 2, 500 + bob, scale=1.05 * max(0.0, p),
                 alpha=clamp(p * 2), angle=math.sin(lt * 3) * 5)
    if s.get("note"):
        text_with_emoji(layer, W / 2, 715, s["note"], font(SEMI, 40), (230, 230, 240))
    dead_meter(layer, s, lt)


def stamp(img, s, lt):
    """'X TIER' stamp + reaction emoji right after the slam."""
    land = s["cue_t"]["land"]
    if not land <= lt < land + 1.1:
        return
    sp = ease_back(prog(lt, land, 0.25))
    fade = 1 - prog(lt, land + 0.8, 0.3)
    st = Image.new("RGBA", (640, 230), (0, 0, 0, 0))
    sd = ImageDraw.Draw(st)
    col = TIER_COL[s["tier"]]
    rrect(sd, [8, 8, 632, 222], 40, fill=col, outline=INK, width=10)
    text_center(sd, 320, 115, f"{s['tier']} TIER", font(IMPACT, 150), INK, anchor="mm")
    y = row_box(s["slot"][0])[0] + RH / 2
    y = clamp(y, 200, SPLIT - 180)
    paste_center(img, st, W / 2 + 140, y, scale=0.8 * (2.0 - sp), alpha=clamp(sp * 2) * fade, angle=-6)
    paste_center(img, emoji_img(REACTION[s["tier"]], 200), W / 2 + 470, y - 80,
                 scale=0.8 * ease_back(prog(lt, land + 0.1, 0.3)), alpha=fade, angle=12)


def top_half(lands, scenes, scene, lt, t):
    img = make_top_bg.cache.copy()
    board, placed = board_at(lands, t)
    img.alpha_composite(board)

    # glow on the tile that just landed
    if placed:
        last_t, last = max(((lt_, s) for lt_, s in lands if t >= lt_), key=lambda x: x[0])
        g = 1 - prog(t, last_t, 1.2)
        if g > 0:
            cx, cy = slot_center(last["slot"])
            glow = Image.new("RGBA", (W, SPLIT), (0, 0, 0, 0))
            r = TILE / 2 + 14
            rrect(ImageDraw.Draw(glow), [cx - r, cy - r, cx + r, cy + r], 26,
                  outline=TIER_COL[last["tier"]] + (int(255 * g),), width=14)
            img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(10)))
            y0, y1 = row_box(last["slot"][0])
            flash = Image.new("RGBA", (W, SPLIT), (0, 0, 0, 0))
            rrect(ImageDraw.Draw(flash), [LX0, y0, CX1, y1], 18,
                  fill=TIER_COL[last["tier"]] + (int(110 * g * g),))
            img.alpha_composite(flash)

    if scene["id"] == "hook":
        hook(img, scene, lt)
    elif "tier" in scene:
        land = scene["cue_t"]["land"]
        fly0 = land - FLY
        if lt < land + 0.25:  # dim the board under the card
            a = ease_out(prog(lt, 0, 0.25)) * (1 - ease_out(prog(lt, fly0, FLY + 0.25)))
            img.alpha_composite(Image.new("RGBA", (W, SPLIT), (8, 6, 14, int(215 * a))))
        if lt < fly0:
            layer = Image.new("RGBA", (W, SPLIT), (0, 0, 0, 0))
            card(layer, scene, lt)
            img.alpha_composite(layer)
        elif lt < land:  # flying into its slot
            q = ease_in(prog(lt, fly0, FLY))
            tx, ty = slot_center(scene["slot"])
            im = animal_img(scene)
            s0 = 1.05
            s1 = TILE * 0.82 / max(im.size)
            paste_center(img, im, W / 2 + (tx - W / 2) * q, 500 + (ty - 500) * q,
                         scale=s0 + (s1 - s0) * q, angle=q * 360)
        stamp(img, scene, lt)
    return img


def hook(img, scene, lt):
    c = scene["cue_t"]
    img.alpha_composite(Image.new("RGBA", (W, SPLIT), (8, 6, 14, 200)))
    layer = Image.new("RGBA", (W, SPLIT), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    lines = [("AUSSIE ANIMALS", WHITE, 120, 0.0), ("RANKED BY", YELLOW, 100, c["ranked"] - 0.05),
             ("HOW DEAD", RED, 190, c["dead"] - 0.25), ("YOU'D BE", RED, 150, c["dead"] + 0.05)]
    y = 150
    for text, col, size, t0 in lines:
        p = ease_back(prog(lt, t0, 0.3))
        if p > 0:
            f = font(IMPACT, max(1, int(size * (1.6 - 0.6 * p))))
            text_center(d, W / 2, y + size / 2, text, f, col, stroke=8, anchor="mm")
        y += size * 1.05
    img.alpha_composite(layer)
    for i, (ch, x) in enumerate((("🐊", 150), ("🦈", 380), ("🕷", 700), ("🪼", 930))):
        p = ease_back(prog(lt, 0.3 + i * 0.12, 0.4))
        paste_center(img, emoji_img(ch, 120), x, 770 + math.sin(lt * 5 + i) * 18, scale=max(0.0, p),
                     angle=math.sin(lt * 4 + i) * 15)
    lp = ease_back(prog(lt, c["last"] - 0.05, 0.35))
    if lp > 0:
        b = Image.new("RGBA", (W, SPLIT), (0, 0, 0, 0))
        bd = ImageDraw.Draw(b)
        rrect(bd, [90, 860, W - 90, 950], 45, fill=YELLOW, outline=INK, width=6)
        text_with_emoji(b, W / 2, 905, "#1 KILLS YOU IN UNDER 5 MIN ⏱", font(IMPACT, 54), INK)
        paste_center(img, b, W / 2, SPLIT / 2, scale=1 + 0.3 * (1 - lp), alpha=clamp(lp * 2))


# ---------- gameplay (bottom half) ----------

GH = H - SPLIT
SPEED = 560  # world px per second
RUN_X = 300
GROUND_BASE = 600  # roof height within the gameplay strip


def make_sky():
    y = np.linspace(0, 1, GH)[:, None, None]
    top, mid, bot = np.array([30, 10, 70]), np.array([200, 40, 120]), np.array([255, 150, 70])
    img = np.where(y < 0.6, top + (mid - top) * (y / 0.6), mid + (bot - mid) * ((y - 0.6) / 0.4))
    img = np.broadcast_to(img, (GH, W, 3)).copy()
    sky = Image.fromarray(img.astype(np.uint8)).convert("RGBA")
    d = ImageDraw.Draw(sky)
    cx, cy, r = 760, 440, 230  # striped synthwave sun
    sun = Image.new("RGBA", (W, GH), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sun)
    sd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 210, 90))
    for k in range(7):
        yy = cy + 30 + k * 30
        sd.rectangle([cx - r, yy, cx + r, yy + 6 + k * 2], fill=(0, 0, 0, 0))
    sky.alpha_composite(sun.filter(ImageFilter.GaussianBlur(1)))
    rnd = random.Random(2)
    for _ in range(70):
        x, y0 = rnd.uniform(0, W), rnd.uniform(0, GH * 0.45)
        d.ellipse([x - 2, y0 - 2, x + 2, y0 + 2], fill=(255, 255, 255, rnd.randint(60, 200)))
    return sky


def make_skyline(seed, base, hmin, hmax, col, win_col, tile_w=2160):
    im = Image.new("RGBA", (tile_w, GH), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    rnd = random.Random(seed)
    x = 0
    while x < tile_w:
        bw = rnd.randint(90, 200)
        bh = rnd.randint(hmin, hmax)
        bw = min(bw, tile_w - x)
        d.rectangle([x, base - bh, x + bw, GH], fill=col)
        for wy in range(base - bh + 20, GH - 10, 34):
            for wx in range(x + 14, x + bw - 14, 28):
                if rnd.random() < 0.35:
                    d.rectangle([wx, wy, wx + 10, wy + 14], fill=win_col)
        x += bw + rnd.randint(4, 30)
    return im


def make_world():
    """Rooftops (x0, x1, roof_y) in world coordinates, plus coins along each jump."""
    rnd = random.Random(7)
    roofs, x = [], -400.0
    while x < SPEED * 200:
        w = rnd.uniform(650, 1100)
        roofs.append((x, x + w, GROUND_BASE + rnd.uniform(-70, 70)))
        x += w + rnd.uniform(170, 280)
    coins = []
    for a, b in zip(roofs, roofs[1:]):
        for k in range(1, 4):
            u = k / 4
            cx, cy = jump_pos(a, b, u)
            coins.append((cx, cy - 70))
        for k in range(3):  # a little row on the roof as well
            coins.append((b[0] + 260 + k * 80, b[2] - 90))
    return roofs, coins


def jump_pos(a, b, u):
    x0, y0 = a[1] - 70, a[2]
    x1, y1 = b[0] + 90, b[2]
    x = x0 + (x1 - x0) * u
    y = y0 + (y1 - y0) * u - 4 * 230 * u * (1 - u)
    return x, y


def runner_state(roofs, wx, t):
    """Kangaroo height and tilt at world x (jumps over gaps, little hops on roofs)."""
    for a, b in zip(roofs, roofs[1:]):
        if a[1] - 70 <= wx <= b[0] + 90:
            u = (wx - (a[1] - 70)) / ((b[0] + 90) - (a[1] - 70))
            _, y = jump_pos(a, b, u)
            return y, (u - 0.5) * 30, True
        if a[0] <= wx < a[1] - 70:
            hop = abs(math.sin(t * 2 * math.pi * 1.6)) * 46
            return a[2] - hop, 0.0, False
    return GROUND_BASE, 0.0, False


def bottom_half(world, t):
    roofs, coins = world
    img = make_sky.cache.copy()
    cam = t * SPEED
    for tile, par in ((make_skyline.far, 0.12), (make_skyline.mid, 0.35)):
        off = -int(cam * par) % tile.width
        for x in (off - tile.width, off):
            if x < W:
                img.paste(tile, (x, 0), tile)
    d = ImageDraw.Draw(img)
    for x0, x1, ry in roofs:
        sx0, sx1 = x0 - cam, x1 - cam
        if sx1 < 0 or sx0 > W:
            continue
        d.rectangle([sx0, ry, sx1, GH], fill=(40, 22, 60))
        d.rectangle([sx0, ry, sx1, ry + 16], fill=(255, 80, 180))
        d.rectangle([sx0, ry + 16, sx1, ry + 24], fill=(120, 40, 120))
        for wy in range(int(ry) + 60, GH, 70):
            for wx in range(int(x0) + 40, int(x1) - 60, 90):
                lit = (wx * 7 + wy * 13) % 5 < 2
                d.rectangle([wx - cam, wy, wx - cam + 36, wy + 40],
                            fill=(255, 220, 120) if lit else (60, 40, 90))
    wx = cam + RUN_X
    got = 0
    for cx, cy in coins:
        if cx < wx - 10:
            got += 1
            if cx > wx - 140:  # "+1" pops up as it's collected
                age = (wx - cx) / SPEED
                d.text((cx - cam, cy - 40 - age * 200), "+1", font=font(IMPACT, 46), fill=YELLOW,
                       anchor="mm", stroke_width=3, stroke_fill=INK)
            continue
        sx = cx - cam
        if -40 < sx < W + 40:
            squeeze = abs(math.cos(t * 6 + cx * 0.01))
            rw = 26 * squeeze + 4
            d.ellipse([sx - rw, cy - 26, sx + rw, cy + 26], fill=(255, 205, 40), outline=(200, 130, 0), width=4)
    # speed lines
    rnd = random.Random(int(t * 10))
    for _ in range(6):
        y = rnd.uniform(60, GH - 120)
        x = rnd.uniform(0, W)
        d.line([x, y, x + rnd.uniform(80, 220), y], fill=(255, 255, 255, 90), width=3)

    ry, tilt, airborne = runner_state(roofs, wx, t)
    roo = emoji_img("🦘", 180, mirror=True)
    paste_center(img, roo, RUN_X, ry - roo.height * 0.42, angle=-tilt if airborne else 0)

    # game HUD
    hud = ImageDraw.Draw(img)
    rrect(hud, [24, 24, 260, 96], 36, fill=(0, 0, 0, 150))
    paste_center(img, emoji_img("🪙", 120), 66, 60, scale=0.42)
    hud.text((106, 60), f"x {got}", font=font(IMPACT, 50), fill=WHITE, anchor="lm")
    hud.text((W - 30, 60), f"{int(cam / 10):06d}m", font=font(IMPACT, 50), fill=WHITE, anchor="rm",
             stroke_width=4, stroke_fill=INK)
    return img


# ---------- captions, overlays, frame ----------

def caption_text(w, nxt):
    txt = w["text"].upper()
    if txt == "AY":
        txt = "A"
    tier_col = TIER_COL.get(txt) if nxt is not None and norm(nxt["text"]) == "tier" else None
    return txt, tier_col


def captions(img, scene, lt):
    words = scene["words"]
    chunks = chunk_words(words)
    cur = None
    for i, ch in enumerate(chunks):
        start = ch[0]["start"] - 0.04
        end = chunks[i + 1][0]["start"] - 0.04 if i + 1 < len(chunks) else scene["dur"]
        if start <= lt < end:
            cur = (i, ch, start)
            break
    if not cur:
        return
    idx, ch, start = cur
    items = []
    for w in ch:
        j = words.index(w)
        items.append(caption_text(w, words[j + 1] if j + 1 < len(words) else None))
    probe = ImageDraw.Draw(img)
    size = 132
    while True:
        f = font(IMPACT, size)
        space = probe.textlength(" ", font=f)
        widths = [probe.textlength(t, font=f) for t, _ in items]
        total = sum(widths) + space * (len(items) - 1)
        if total <= W - 110 or size <= 60:
            break
        size -= 6
    pad = 30
    layer = Image.new("RGBA", (int(total) + pad * 2, size + pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x = pad
    for (txt, tcol), wd, w in zip(items, widths, ch):
        active = w["start"] - 0.04 <= lt <= w["end"] + 0.1
        fill = tcol or (YELLOW if active else WHITE)
        d.text((x, layer.height / 2), txt, font=f, fill=fill, anchor="lm", stroke_width=11,
               stroke_fill=INK)
        x += wd + space
    pop = ease_back(prog(lt, start, 0.14))
    tilt = (-3 if idx % 2 else 3) * (1 - prog(lt, start, 0.2))
    paste_center(img, layer, W / 2, SPLIT + 8, scale=0.7 + 0.3 * pop, alpha=clamp(pop * 3), angle=tilt)


def follow_button(img, scene, lt):
    ft = scene["cue_t"]["follow"] - 0.1
    if lt < ft:
        return
    a = ease_back(prog(lt, ft, 0.4))
    pulse = 1 + 0.05 * math.sin(lt * 9)
    b = Image.new("RGBA", (860, 150), (0, 0, 0, 0))
    bd = ImageDraw.Draw(b)
    rrect(bd, [6, 6, 854, 144], 70, fill=RED, outline=WHITE, width=8)
    text_center(bd, 430, 75, "FOLLOW FOR PART 2", font(IMPACT, 88), WHITE, stroke=4, anchor="mm")
    paste_center(img, b, W / 2, SPLIT + 330, scale=a * pulse, alpha=clamp(a * 2))


def render_frame(scenes, lands, world, total, t):
    scene = next(s for s in reversed(scenes) if t >= s["start"])
    lt = t - scene["start"]
    img = Image.new("RGBA", (W, H))
    img.paste(bottom_half(world, t), (0, SPLIT))
    img.paste(top_half(lands, scenes, scene, lt, t), (0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([0, SPLIT - 4, W, SPLIT + 4], fill=INK)
    captions(img, scene, lt)
    if scene["id"] == "jelly":
        follow_button(img, scene, lt)
    d.rectangle([0, 0, W, 10], fill=(255, 255, 255, 40))
    d.rectangle([0, 0, W * t / total, 10], fill=YELLOW)

    # impact: flash, zoom punch and screen shake right after each landing
    since, last = min(((t - lt_, s) for lt_, s in lands if t >= lt_), default=(9, None),
                      key=lambda x: x[0])
    scene_cut = t - scene["start"] if scene is not scenes[0] else 9
    if scene_cut < 0.1:
        img.alpha_composite(Image.new("RGBA", (W, H), (255, 255, 255, int(110 * (1 - scene_cut / 0.1)))))
    out = img.convert("RGB")
    if since < 0.45:
        big = last["tier"] == "S"
        if since < 0.12:
            col = (255, 40, 40) if big else (255, 255, 255)
            out = Image.blend(out, Image.new("RGB", (W, H), col), 0.45 * (1 - since / 0.12))
        z = 1 + (0.09 if big else 0.05) * (1 - ease_out(since / 0.3)) if since < 0.3 else 1
        amp = (34 if big else 20) * (1 - since / 0.45)
        rnd = random.Random(int(t * FPS))
        dx, dy = rnd.uniform(-amp, amp), rnd.uniform(-amp, amp)
        cw, chh = W / z, H / z
        x0, y0 = (W - cw) / 2 - dx, (H - chh) / 2 - dy
        out = out.transform((W, H), Image.Transform.EXTENT, (x0, y0, x0 + cw, y0 + chh),
                            Image.Resampling.BILINEAR)
    return out


def main():
    scenes, total = load_timeline()
    lands = landings(scenes)
    make_top_bg.cache = make_top_bg()
    make_sky.cache = make_sky()
    make_skyline.far = make_skyline(3, GH - 140, 160, 360, (70, 25, 100), (150, 90, 170))
    make_skyline.mid = make_skyline(5, GH - 60, 120, 300, (50, 18, 74), (230, 150, 120))
    world = make_world()
    OUT.mkdir(parents=True, exist_ok=True)

    if "--preview" in sys.argv:
        times = [float(x) for x in sys.argv[sys.argv.index("--preview") + 1:]]
        for t in times:
            render_frame(scenes, lands, world, total, t).save(OUT / f"preview_{t:05.1f}.png")
        print("scene starts:", [(s["id"], round(s["start"], 2)) for s in scenes], "total", round(total, 2))
        print("landings:", [(round(lt, 2), s["id"]) for lt, s in lands])
        return

    audio = build_audio(scenes, total)
    out = OUT / "aussie_animals_how_dead.mp4"
    ff = subprocess.Popen([
        "ffmpeg", "-y", "-v", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
        "-i", str(audio),
        "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out),
    ], stdin=subprocess.PIPE)
    frames = int(total * FPS)
    for i in range(frames):
        ff.stdin.write(render_frame(scenes, lands, world, total, i / FPS).tobytes())
        if i % 150 == 0:
            print(f"frame {i}/{frames}", file=sys.stderr)
    ff.stdin.close()
    ff.wait()
    print(out)


if __name__ == "__main__":
    main()
