"""Render 'Things Americans think are fake about Australia' (1080x1920, 30fps).

Brainrot layout: each claim and its real-or-fake verdict stamp plays on top with a running
scoreboard, a top-down "gameplay" clip runs on the bottom (a ute dodging kangaroos on an outback
road while magpies steal its pies), big punchy captions sit on the seam.
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

from script import SCENES

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output" / "aussie_fake_or_real"
VO = OUT / "vo"

W, H, FPS = 1080, 1920, 30
SR = 48000
PAD = 0.25  # silence after each scene's line
SPLIT = 1060  # story above, gameplay below
BRAINROT = 0.6  # music + sfx level, about 4.4 dB under the earlier brainrot reels

FONTS = Path("C:/Windows/Fonts")
IMPACT = str(FONTS / "impact.ttf")
BOLD = str(FONTS / "seguibl.ttf")
SEMI = str(FONTS / "segoeuib.ttf")
EMOJI = str(FONTS / "seguiemj.ttf")

WHITE = (255, 255, 255)
INK = (10, 10, 16)
YELLOW = (255, 230, 0)
RED = (255, 60, 60)
GREEN = (60, 200, 100)
BLUE = (40, 140, 255)
KEYWORDS = {"DROP", "BEARS", "KOALAS", "FAKE", "REAL", "HALF", "PRANK", "VEGEMITE", "SPIDERS", "PLATE", "HUNTSMAN",
            "15", "LAOS", "BIRDS", "KOOKABURRAS", "IBIS", "CHICKENS", "COCKATOOS", "SANDWICH"}
SPOKEN_NUMBERS = {"FIFTEEN": "15"}

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


def ease_back(x):
    x = clamp(x)
    c = 1.70158
    return 1 + (c + 1) * (x - 1) ** 3 + c * (x - 1) ** 2


def smooth(x):
    x = clamp(x)
    return x * x * (3 - 2 * x)


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


def load_timeline():
    scenes, t = [], 0.0
    for s in SCENES:
        audio = decode(VO / f"{s['id']}.mp3")
        words = json.loads((VO / f"{s['id']}.json").read_text())
        dur = len(audio) / SR + PAD
        cues = {c: cue_time(words, c) for c in s["cues"]}
        cues.setdefault("end", dur)
        scenes.append({**s, "start": t, "dur": dur, "audio": audio, "words": words, "cue_t": cues})
        t += dur
    return scenes, t


def decode(path):
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
        check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def boom_times(scenes):
    return [s["start"] + s["cue_t"][b] for s in scenes for b in s["booms"]]


def chunk_words(words):
    """Brainrot captions: one or two words at a time, split at pauses."""
    chunks, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        pause = nxt is not None and nxt["start"] - w["end"] > 0.15
        long_word = len(w["text"]) > 7
        if len(cur) >= 2 or pause or long_word or nxt is None:
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

    rng = np.random.default_rng(31)

    def add(buf, at, sig, gain):
        i = int(at * SR)
        if i >= n:
            return
        m = min(len(sig), n - i)
        buf[i:i + m] += gain * sig[:m]

    # Phonk loop at 124 bpm: kick + 808, snare on 2 and 4, cowbell riff in 16ths.
    music = np.zeros(n, np.float32)
    beat = 60 / 124
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

    scale = [523.3, 587.3, 622.3, 698.5, 784.0, 932.3]
    riff = [5, None, 3, 4, None, 4, 3, None, 2, None, 0, 2, 1, None, 0, None,
            5, None, 3, 4, None, 4, 5, 3, 4, None, 2, None, 1, 2, 0, None]
    bells = {f: cowbell(scale[f]) for f in set(r for r in riff if r is not None)}
    bass_notes = [43.7, 43.7, 38.9, 49.0]
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

    def whoosh(length):
        wl = int(length * SR)
        env = np.sin(np.linspace(0, np.pi, wl)) ** 2
        return np.convolve(rng.standard_normal(wl), np.ones(8) / 8, mode="same") * env
    for s in scenes[1:]:
        add(fx, s["start"] - 0.15, whoosh(0.4), 0.18)
    # vine-boom on each punchline
    vl = int(1.6 * SR)
    vt = np.arange(vl) / SR
    boom = np.sin(2 * np.pi * np.cumsum(46 + 70 * np.exp(-vt * 14)) / SR)
    boom += 0.5 * np.sin(2 * np.pi * np.cumsum(92 + 140 * np.exp(-vt * 14)) / SR)
    boom = np.tanh(3 * boom) * tone_env(vl, 2.6)
    boom += 0.3 * rng.standard_normal(vl) * tone_env(vl, 30)
    for bt_ in boom_times(scenes):
        add(fx, bt_, boom, 0.45)
    # duck music under the voice
    vol = np.convolve(np.abs(voice), np.ones(2400) / 2400, mode="same")
    duck = 1 - 0.6 * np.clip(vol / (vol.max() * 0.25 + 1e-9), 0, 1)

    mix = voice * 1.0 + BRAINROT * (music * duck + fx)
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


def emoji_img(ch, size=280, mirror=False, tint=None):
    key = (ch, size, mirror, tint)
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
        if mirror:
            im = im.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        _emoji_cache[key] = im
    return _emoji_cache[key]


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


def emoji_parts(d, text, f):
    parts = [p for p in re.split(f"({EMOJI_RE.pattern})", text) if p]
    widths = [f.size * 1.1 if EMOJI_RE.fullmatch(p) else d.textlength(p, font=f) for p in parts]
    return parts, widths


def text_with_emoji(layer, cx, cy, text, f, fill, stroke=0):
    """Centre a line mixing text and emoji (Pillow can't fall back between fonts)."""
    d = ImageDraw.Draw(layer)
    parts, widths = emoji_parts(d, text, f)
    x = cx - sum(widths) / 2
    for p, wd in zip(parts, widths):
        if EMOJI_RE.fullmatch(p):
            paste_center(layer, emoji_img(p, 120), x + wd / 2, cy, scale=f.size / 120 * 0.85)
        else:
            d.text((x, cy), p, font=f, fill=fill, anchor="lm", stroke_width=stroke, stroke_fill=INK)
        x += wd


_sticker_cache = {}


def sticker(img, text, cx, cy, p, size=64, bg=YELLOW, fg=INK, angle=0.0, scale=1.0):
    """Rounded label that pops in with an overshoot. p is raw 0..1 progress."""
    if p <= 0:
        return
    key = (text, size, bg, fg)
    if key not in _sticker_cache:
        f = font(IMPACT, size)
        probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        _, widths = emoji_parts(probe, text, f)
        w, h = int(sum(widths)) + size, int(size * 1.5)
        st = Image.new("RGBA", (w + 12, h + 12), (0, 0, 0, 0))
        rrect(ImageDraw.Draw(st), [6, 6, w + 6, h + 6], h // 2, fill=bg, outline=INK, width=6)
        text_with_emoji(st, (w + 12) / 2, (h + 12) / 2, text, f, fg)
        _sticker_cache[key] = st
    s = ease_back(p)
    paste_center(img, _sticker_cache[key], cx, cy, scale=scale * max(0.0, s), alpha=clamp(p * 3),
                 angle=angle)


# ---------- shared story pieces ----------

def dust(img, t, n=60, seed=4, height=None):
    d = ImageDraw.Draw(img)
    rnd = random.Random(seed)
    height = height or img.height
    for _ in range(n):
        x0, y0, v, r = rnd.uniform(0, W), rnd.uniform(0, height), rnd.uniform(30, 90), rnd.uniform(2, 4)
        x = (x0 + t * v) % W
        y = (y0 + math.sin(t + x0) * 22) % height
        d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 190, 130, 110))


_stamp_cache = {}


def stamp(img, text, col, cx, cy, p, size=150, angle=-9):
    """Rubber-stamp verdict: slams down from oversized, p is raw 0..1 progress."""
    if p <= 0:
        return
    key = (text, col, size)
    if key not in _stamp_cache:
        f = font(IMPACT, size)
        w = int(ImageDraw.Draw(Image.new("RGBA", (1, 1))).textlength(text, font=f)) + 90
        h = int(size * 1.5)
        st = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(st)
        rrect(d, [4, 4, w - 4, h - 4], 24, fill=(255, 255, 255, 235), outline=col, width=max(6, size // 11))
        text_center(d, w / 2, h / 2, text, f, col, anchor="mm")
        _stamp_cache[key] = st
    paste_center(img, _stamp_cache[key], cx, cy, scale=2.0 - ease_out(p), alpha=clamp(p * 4), angle=angle)


_art_cache = {}


def evil_koala(size=280):
    """The koala emoji with glowing red eyes and fangs."""
    key = ("koala", size)
    if key not in _art_cache:
        im = emoji_img("🐨", size).copy()
        d = ImageDraw.Draw(im)
        w, h = im.size
        r = w * 0.06
        for ex in (0.36, 0.64):
            d.ellipse([w * ex - r, h * 0.47 - r, w * ex + r, h * 0.47 + r], fill=(235, 20, 20), outline=INK, width=3)
            d.ellipse([w * ex - r * 0.3, h * 0.47 - r * 0.3, w * ex + r * 0.3, h * 0.47 + r * 0.3], fill=(255, 235, 120))
        for fx_ in (0.43, 0.57):
            d.polygon([(w * (fx_ - 0.035), h * 0.74), (w * (fx_ + 0.035), h * 0.74), (w * fx_, h * 0.87)],
                      fill=WHITE, outline=INK)
        _art_cache[key] = im
    return _art_cache[key]


def huntsman(span):
    """Top-down huntsman: flat brown body with sideways, crab-like legs. span is leg tip to leg tip."""
    key = ("spider", span)
    if key not in _art_cache:
        S = int(span * 3)
        im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        c, u = S / 2, S / 2
        lw = max(4, int(S * 0.022))
        legs = [((0.13, -0.10), (0.52, -0.42), (0.93, -0.34)), ((0.15, -0.04), (0.60, -0.17), (0.98, -0.02)),
                ((0.15, 0.04), (0.58, 0.14), (0.92, 0.32)), ((0.13, 0.10), (0.45, 0.40), (0.74, 0.70))]
        for sign in (-1, 1):
            for pts in legs:
                line = [(c + sign * x * u, c + y * u) for x, y in pts]
                d.line(line, fill=(84, 54, 30), width=lw, joint="curve")
                for x, y in line[1:]:
                    d.ellipse([x - lw * 0.6, y - lw * 0.6, x + lw * 0.6, y + lw * 0.6], fill=(60, 38, 22))
        d.ellipse([c - u * 0.17, c - u * 0.24, c + u * 0.17, c + u * 0.08], fill=(150, 104, 58), outline=(60, 38, 22),
                  width=lw // 2)
        d.ellipse([c - u * 0.14, c + u * 0.02, c + u * 0.14, c + u * 0.40], fill=(116, 78, 42), outline=(60, 38, 22),
                  width=lw // 2)
        _art_cache[key] = im.resize((int(span), int(span)), Image.LANCZOS)
    return _art_cache[key]


def plate(dia):
    key = ("plate", dia)
    if key not in _art_cache:
        S = dia * 2
        im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.ellipse([4, 4, S - 4, S - 4], fill=(248, 248, 244), outline=(150, 150, 160), width=8)
        m = S * 0.17
        d.ellipse([m, m, S - m, S - m], fill=(236, 236, 230), outline=(200, 200, 205), width=5)
        _art_cache[key] = im.resize((dia, dia), Image.LANCZOS)
    return _art_cache[key]


def wheelie_bin(lid):
    """Side-on wheelie bin. lid: 0 closed, 1 flipped open."""
    im = Image.new("RGBA", (420, 480), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.polygon([(90, 170), (330, 170), (306, 430), (114, 430)], fill=(45, 95, 60), outline=INK)
    d.line([(90, 170), (114, 430)], fill=INK, width=5)
    d.line([(330, 170), (306, 430)], fill=INK, width=5)
    d.ellipse([92, 410, 150, 468], fill=INK)
    d.ellipse([270, 410, 328, 468], fill=INK)
    a = math.radians(115 * lid)  # hinged at the back
    hx, hy = 335, 168
    pts = [(0, 0), (-260, 0), (-260, -24), (0, -24)]
    rot = [(hx + x * math.cos(a) - y * math.sin(a), hy + x * math.sin(a) + y * math.cos(a)) for x, y in pts]
    d.polygon(rot, fill=(225, 190, 40), outline=INK)
    return im


def text_card(img, lines, cx, cy, p, w=900, h=250):
    """Fake museum web page."""
    if p <= 0:
        return
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    rrect(d, [2, 2, w - 2, h - 2], 18, fill=(248, 246, 238), outline=INK, width=5)
    y = 22
    for text, size, col, path in lines:
        d.text((34, y), text, font=font(path, size), fill=col)
        y += int(size * 1.35)
    paste_center(img, im, cx, cy, scale=max(0.0, ease_back(p)), alpha=clamp(p * 3))


def make_top_bg():
    y = np.linspace(0, 1, SPLIT)[:, None, None]
    img = np.array([58, 24, 56]) + (np.array([120, 50, 26]) - np.array([58, 24, 56])) * y
    img = np.broadcast_to(img, (SPLIT, W, 3)).copy()
    return Image.fromarray(img.astype(np.uint8)).convert("RGBA")


ASSETS = {}
ORANGE = (255, 140, 0)
BROWN_BIRD = (150, 110, 70)
COCKY = (240, 235, 215)


def load_assets(scenes):
    ASSETS["top_bg"] = make_top_bg()
    ASSETS["tile"] = make_road_tile()
    ASSETS["ute"] = make_ute()
    by_id = {s["id"]: s for s in scenes}

    def at(sid, cue):
        return by_id[sid]["start"] + by_id[sid]["cue_t"][cue]
    # scoreboard: each claim shows up in the hook and gets its verdict in its own scene
    ASSETS["chips"] = [
        (190, "🐨", None, "FAKE", RED, at("hook", "drop"), at("bear_verdict", "fake")),
        (540, "🕷", (120, 80, 50), "HALF REAL", ORANGE, at("hook", "spiders"), at("spider_verdict", "half")),
        (890, "🐦", BROWN_BIRD, "REAL", GREEN, at("hook", "birds"), at("bird_verdict", "real")),
    ]


def scoreboard(img, t):
    for x, ch, tint, verdict, col, show, reveal in ASSETS["chips"]:
        p = prog(t, show - 0.05, 0.3)
        if p <= 0:
            continue
        done = t >= reveal
        chip = Image.new("RGBA", (330, 88), (0, 0, 0, 0))
        d = ImageDraw.Draw(chip)
        rrect(d, [3, 3, 327, 85], 40, fill=col if done else (30, 26, 40), outline=WHITE, width=4)
        paste_center(chip, emoji_img(ch, 120, tint=tint), 50, 44, scale=0.46)
        text = verdict if done else "???"
        d.text((192, 44), text, font=fit_font(d, text, IMPACT, 50, 220), fill=WHITE, anchor="mm")
        pop = 1 + 0.25 * (1 - prog(t, reveal, 0.3)) if done else 1
        paste_center(img, chip, x, 246, scale=pop * max(0.0, ease_back(p)), alpha=clamp(p * 3))


# ---------- story scenes (top half) ----------

def label(img, text, x, y, p, size=50, col=WHITE):
    if p > 0:
        f = fit_font(ImageDraw.Draw(img), text, IMPACT, size, 330)
        text_center(ImageDraw.Draw(img), x, y, text, f, col, stroke=5, anchor="mm")


def scene_hook(img, s, lt):
    c = s["cue_t"]
    sticker(img, "AMERICANS: NAH, THAT'S FAKE 🤨", 540, 368, prog(lt, c["americans"] - 0.1, 0.35), size=54, bg=WHITE)
    p = prog(lt, c["drop"] - 0.05, 0.35)
    paste_center(img, evil_koala(), 190, 600, scale=0.8 * max(0.0, ease_back(p)), angle=math.sin(lt * 5) * 4)
    label(img, "DROP BEARS", 190, 770, p, size=56)
    p = prog(lt, c["spiders"] - 0.05, 0.35)
    paste_center(img, plate(250), 540, 600, scale=max(0.0, ease_back(p)))
    paste_center(img, huntsman(240), 540, 600, scale=max(0.0, ease_back(p)), angle=math.sin(lt * 7) * 5)
    label(img, "PLATE SPIDERS", 540, 770, p, size=56)
    p = prog(lt, c["birds"] - 0.05, 0.35)
    paste_center(img, emoji_img("🐦", 280, tint=BROWN_BIRD), 890, 590 + math.sin(lt * 9) * 12,
                 scale=0.72 * max(0.0, ease_back(p)))
    paste_center(img, emoji_img("🍟", 120), 800, 660, scale=max(0.0, ease_back(p)))
    label(img, "FOOD THIEVES", 890, 770, p, size=56)
    sticker(img, "REAL OR FAKE? 🤔", 540, 880, prog(lt, c["real"] - 0.1, 0.3), size=78, bg=YELLOW, angle=-2)


def scene_bear_claim(img, s, lt):
    c = s["cue_t"]
    paste_center(img, emoji_img("🌳", 280), 540, 500, scale=2.0)
    fall = prog(lt, c["fall"] - 0.1, 0.42)
    y = 400 + (760 - 400) * fall ** 2
    hit = lt >= c["fall"] + 0.32
    paste_center(img, emoji_img("😱", 120), 540, 850, scale=1.25, angle=math.sin(lt * 25) * 4 if hit else 0)
    paste_center(img, evil_koala(), 540, y, scale=0.72, angle=fall * 380)
    if hit:
        paste_center(img, emoji_img("💥", 280), 540, 800, scale=0.9 * ease_back(prog(lt, c["fall"] + 0.32, 0.2)),
                     alpha=1 - prog(lt, c["fall"] + 0.9, 0.3))
    sticker(img, "KILLER KOALAS 💀", 540, 368, prog(lt, c["killer"] - 0.1, 0.3), size=70, bg=RED, fg=WHITE, angle=-2)
    sticker(img, "⚠ TOURIST WARNING ⚠", 540, 900, prog(lt, c["tourists"] - 0.1, 0.3), size=58, bg=YELLOW, angle=2)


def scene_bear_verdict(img, s, lt):
    c = s["cue_t"]
    if lt < c["vegemite"] - 0.2:
        paste_center(img, evil_koala(), 540, 590, scale=1.35, angle=math.sin(lt * 6) * 4)
        stamp(img, "FAKE", RED, 540, 590, prog(lt, c["fake"] - 0.03, 0.14), size=190)
        sticker(img, "IT'S A PRANK 😂", 540, 880, prog(lt, c["prank"] - 0.1, 0.3), size=72, bg=YELLOW, angle=2)
    elif lt < c["museum"] - 0.2:
        p = prog(lt, c["vegemite"] - 0.2, 0.3)
        d = ImageDraw.Draw(img)
        if p > 0.5:  # a brown smear behind each ear
            for x in (345, 735):
                d.ellipse([x - 38, 560, x + 38, 660], fill=(52, 30, 14), outline=INK, width=4)
        paste_center(img, emoji_img("😬", 120), 540, 610, scale=2.9 * max(0.0, ease_back(p)))
        sticker(img, "VEGEMITE BEHIND EARS", 540, 368, p, size=66, bg=YELLOW, angle=-2)
        sticker(img, "TOTALLY LEGIT TIP 👍", 540, 880, prog(lt, c["vegemite"] + 0.5, 0.3), size=62, bg=WHITE, angle=2)
    else:
        p = prog(lt, c["museum"] - 0.2, 0.3)
        paste_center(img, emoji_img("🏛", 280), 540, 450, scale=0.72 * max(0.0, ease_back(p)))
        text_card(img, [("Australian Museum", 34, (90, 90, 100), SEMI),
                        ("DROP BEAR", 70, INK, IMPACT),
                        ("Thylarctos plummetus", 50, (150, 40, 40), SEMI)], 540, 710, p, h=240)
        sticker(img, "AS A JOKE 🤡", 540, 900, prog(lt, c["joke"] - 0.1, 0.25), size=66, bg=RED, fg=WHITE, angle=-3)


def scene_spider_claim(img, s, lt):
    c = s["cue_t"]
    sticker(img, "SPIDER = PLATE??", 540, 368, prog(lt, c["spiders"] - 0.1, 0.3), size=78, bg=YELLOW, angle=-2)
    paste_center(img, plate(460), 540, 650, scale=max(0.0, ease_back(prog(lt, c["plate"] - 0.1, 0.3))))
    u = ease_out(prog(lt, c["spiders"], c["plate"] - c["spiders"] + 0.2))
    paste_center(img, huntsman(380), 1200 - 660 * u, 650 + math.sin(lt * 14) * 5 * (1 - u), angle=30 * (1 - u))
    sticker(img, "SURELY NOT 🤨", 540, 900, prog(lt, c["exaggerating"] - 0.1, 0.3), size=68, bg=WHITE, angle=2)


CM = 17  # px per cm, so both spiders and plates are drawn to scale


def scene_spider_verdict(img, s, lt):
    c = s["cue_t"]
    if lt < c["golden"] - 0.1:
        paste_center(img, huntsman(380), 540, 600, angle=math.sin(lt * 8) * 3)
        stamp(img, "HALF REAL", ORANGE, 540, 600, prog(lt, c["half"] - 0.03, 0.14), size=130)
        return
    sticker(img, "GOLDEN HUNTSMAN", 250, 362, prog(lt, c["golden"] - 0.1, 0.3), size=44, bg=YELLOW)
    fp = prog(lt, c["fifteen"] - 0.1, 0.3)
    paste_center(img, plate(18 * CM), 250, 620, scale=max(0.0, ease_back(fp)))
    paste_center(img, huntsman(15 * CM), 250, 620, angle=math.sin(lt * 6) * 3,
                 scale=max(0.0, ease_back(prog(lt, c["golden"] - 0.1, 0.3))))
    label(img, "15 CM", 250, 815, fp, size=70, col=YELLOW)
    sticker(img, "SIDE PLATE", 250, 895, prog(lt, c["side"] - 0.1, 0.3), size=50, bg=WHITE, angle=-2)
    dp = prog(lt, c["dinner"] - 0.1, 0.3)
    paste_center(img, plate(27 * CM), 745, 620, scale=max(0.0, ease_back(dp)))
    sticker(img, "DINNER PLATE", 745, 895, dp, size=50, bg=WHITE, angle=2)
    lp = prog(lt, c["laos"] - 0.1, 0.25)
    paste_center(img, huntsman(30 * CM), 745, 620, scale=max(0.0, ease_back(lp)), angle=math.sin(lt * 6) * 3)
    sticker(img, "30 CM... IN LAOS 💀", 745, 362, lp, size=50, bg=RED, fg=WHITE, angle=2)


def scene_bird_claim(img, s, lt):
    c = s["cue_t"]
    sticker(img, "BIRDS THAT STEAL FOOD 🍟", 540, 368, prog(lt, c["birds"] - 0.1, 0.3), size=62, bg=YELLOW, angle=-2)
    # the gull hovers, dives to the chips on "seagull", then carries them off to the left
    dive = smooth(prog(lt, c["seagull"] - 0.45, 0.45))
    away = prog(lt, c["seagull"], 0.8) ** 2
    x = 860 + (540 - 860) * dive - 900 * away
    y = 530 + (580 - 530) * dive - 220 * away + math.sin(lt * 7) * 12
    paste_center(img, emoji_img("🍟", 280), 540 - 900 * away, 680 - 220 * away, scale=0.75)
    paste_center(img, emoji_img("🐦", 280, tint=(235, 235, 240)), x, y, scale=0.8)
    sticker(img, "JUST A SEAGULL THING? 🤔", 540, 900, prog(lt, c["seagull"] - 0.1, 0.3), size=58, bg=WHITE, angle=2)


GRID = [(120 + (i % 11) * 84, 450 + (i // 11) * 92) for i in range(44)]


def scene_bird_verdict(img, s, lt):
    c = s["cue_t"]
    if lt < c["kookaburras"] - 0.15:
        paste_center(img, emoji_img("🐦", 280, tint=BROWN_BIRD), 540, 590, scale=1.3, angle=math.sin(lt * 9) * 6)
        stamp(img, "REAL", GREEN, 540, 600, prog(lt, c["real"] - 0.03, 0.14), size=190)
    elif lt < c["ibis"] - 0.15:
        p = prog(lt, c["kookaburras"] - 0.15, 0.3)
        sticker(img, "KOOKABURRAS", 540, 368, p, size=72, bg=YELLOW, angle=-2)
        u = (lt - c["kookaburras"]) % 1.1 / 1.1
        paste_center(img, emoji_img("🍖", 280), 260, 680, scale=0.6 * max(0.0, ease_back(p)))
        paste_center(img, emoji_img("🐦", 280, tint=BROWN_BIRD), 760 - 200 * math.sin(u * math.pi), 590,
                     scale=1.05, angle=math.sin(lt * 12) * 8)
        sticker(img, "PICNICS + BBQS 🔥", 540, 890, p, size=62, bg=RED, fg=WHITE, angle=2)
    elif lt < c["cockatoos"] - 0.15:
        p = prog(lt, c["ibis"] - 0.15, 0.3)
        sticker(img, "IBIS", 540, 368, p, size=78, bg=WHITE, angle=-2)
        paste_center(img, emoji_img("🦩", 280, tint=(235, 235, 235)), 700, 600 + math.sin(lt * 8) * 12, scale=1.15)
        paste_center(img, emoji_img("🗑", 280), 300, 640, scale=0.85 * max(0.0, ease_back(p)))
        sticker(img, "BIN CHICKEN 🐔", 540, 890, prog(lt, c["chickens"] - 0.3, 0.3), size=74, bg=YELLOW, angle=2)
    elif lt < c["three"] - 0.15:
        p = prog(lt, c["cockatoos"] - 0.15, 0.3)
        sticker(img, "SYDNEY COCKATOOS", 540, 368, p, size=66, bg=YELLOW, angle=-2)
        lid = smooth(prog((lt - c["cockatoos"]) % 2.0, 0.5, 0.5))
        paste_center(img, wheelie_bin(lid), 500, 650)
        paste_center(img, emoji_img("🦜", 280, tint=COCKY), 420 + 80 * lid, 480 + 10 * lid, scale=0.6,
                     angle=-12 * lid)
        tp = prog(lt, c["taught"] - 0.1, 0.25)
        if tp > 0:
            for i, (x, y) in enumerate(((130, 540), (130, 740), (900, 560), (900, 760))):
                paste_center(img, emoji_img("🦜", 120, tint=COCKY), x, y + math.sin(lt * 7 + i) * 8,
                             scale=1.2 * max(0.0, ease_back(prog(tp, i * 0.15, 0.5))))
            sticker(img, "TAUGHT EACH OTHER 🎓", 540, 900, tp, size=58, bg=WHITE, angle=2)
    else:
        grow = prog(lt, c["forty"] - 0.1, 0.5)
        n = 3 + int(41 * grow)
        col = RED if n == 44 else YELLOW
        sticker(img, f"{n} SUBURBS", 540, 368, 1.0, size=84, bg=col, fg=WHITE if n == 44 else INK)
        for i in range(n):
            x, y = GRID[i]
            paste_center(img, emoji_img("🦜", 120, tint=COCKY), x, y + math.sin(lt * 8 + i) * 5, scale=0.62)


def scene_outro(img, s, lt):
    c = s["cue_t"]
    rows = (("one", evil_koala(), 0.68, "DROP BEARS", "FAKE", RED, 190),
            ("half", huntsman(230), 1.0, "PLATE SPIDERS", "HALF REAL", ORANGE, 540),
            ("very", emoji_img("🐦", 280, tint=BROWN_BIRD), 0.68, "FOOD THIEVES", "REAL", GREEN, 890))
    for cue, art, k, name, verdict, col, x in rows:
        p = prog(lt, c[cue] - 0.05, 0.3)
        paste_center(img, art, x, 450, scale=k * max(0.0, ease_back(p)))
        label(img, name, x, 610, p, size=52)
        stamp(img, verdict, col, x, 690, prog(lt, c[cue], 0.14), size=56, angle=-4)
    sp = prog(lt, c["sandwich"] - 0.1, 0.3)
    if sp > 0:
        # a bird flies in, grabs the sandwich and leaves with it
        arrive = smooth(prog(lt, c["sandwich"], 0.35))
        away = prog(lt, c["sandwich"] + 0.4, 0.8) ** 2
        paste_center(img, emoji_img("🥪", 280), 500 + 800 * away, 880 - 40 * away, scale=0.6 * ease_back(sp))
        paste_center(img, emoji_img("🐦", 280, tint=BROWN_BIRD), 1200 - 620 * arrive + 800 * away, 830 - 40 * away,
                     scale=0.65, angle=math.sin(lt * 14) * 8)


SCENE_DRAW = {"hook": scene_hook, "bear_claim": scene_bear_claim, "bear_verdict": scene_bear_verdict,
              "spider_claim": scene_spider_claim, "spider_verdict": scene_spider_verdict,
              "bird_claim": scene_bird_claim, "bird_verdict": scene_bird_verdict, "outro": scene_outro}


def header(img):
    d = ImageDraw.Draw(img)
    text_center(d, W / 2, 22, "THINGS AMERICANS THINK", font(IMPACT, 62), WHITE, stroke=5)
    text_with_emoji(img, W / 2, 135, "ARE FAKE ABOUT AUSTRALIA 🤔", font(IMPACT, 76), YELLOW, stroke=6)


def top_half(scene, lt, t):
    img = ASSETS["top_bg"].copy()
    dust(img, t, n=45)
    SCENE_DRAW[scene["id"]](img, scene, lt)
    if "header" not in ASSETS:
        h = Image.new("RGBA", (W, 190), (0, 0, 0, 0))
        hd = ImageDraw.Draw(h)
        for y in range(190):  # fade so the header reads over any scene
            hd.line([(0, y), (W, y)], fill=(16, 8, 18, int(220 * clamp(1.25 - y / 190))))
        header(h)
        ASSETS["header"] = h
    img.alpha_composite(ASSETS["header"])
    scoreboard(img, t)
    return img


# ---------- gameplay (bottom half) ----------

GH = H - SPLIT
ROAD = (170, 910)
LANES = [320, 540, 760]
SPEED = 640  # world px per second
UTE_Y = GH - 200
SWITCH = 210  # travel distance for a lane change
TILE_H = GH * 4
STEAL_EVERY = 6.5  # seconds between magpie pie raids


def make_road_tile():
    """Seamless vertical tile: a dirt road through red outback scrub."""
    im = Image.new("RGBA", (W, TILE_H), (176, 84, 42, 255))
    d = ImageDraw.Draw(im)
    rnd = random.Random(9)
    left, right = [], []
    for y in range(0, TILE_H + 1, 20):
        wob = 18 * math.sin(2 * math.pi * y / TILE_H * 5) + 8 * math.sin(2 * math.pi * y / TILE_H * 13)
        left.append((ROAD[0] + wob, y))
        right.append((ROAD[1] + wob * 0.8, y))
    d.polygon(left + right[::-1], fill=(214, 130, 74))
    for _ in range(240):
        y = rnd.uniform(0, TILE_H)
        x = rnd.uniform(ROAD[0] + 40, ROAD[1] - 80)
        L = rnd.uniform(16, 44)
        for yy in (y, y - TILE_H, y + TILE_H):
            d.line([x, yy, x, yy + L], fill=(196, 112, 60), width=3)
    for k in range(40):
        side = k % 2
        y = (k + rnd.uniform(0, 0.6)) * TILE_H / 40
        x = rnd.uniform(20, ROAD[0] - 40) if side == 0 else rnd.uniform(ROAD[1] + 40, W - 20)
        ch = rnd.choice(["🌿", "🌳", "🌿", "🪨"])
        for yy in (y, y - TILE_H, y + TILE_H):
            paste_center(im, emoji_img(ch, 120, mirror=side == 1), x, yy, scale=0.85)
    return im


def make_ute():
    """Top-down white ute with a load tray."""
    im = Image.new("RGBA", (170, 270), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for x, y in ((10, 50), (140, 50), (10, 190), (140, 190)):
        rrect(d, [x, y, x + 20, y + 46], 6, fill=INK)
    rrect(d, [24, 10, 146, 260], 26, fill=(240, 240, 236), outline=INK, width=5)
    rrect(d, [38, 62, 132, 104], 10, fill=(70, 110, 140), outline=INK, width=3)
    rrect(d, [38, 148, 132, 246], 8, fill=(110, 80, 56), outline=INK, width=4)
    d.line([(38, 180), (132, 180)], fill=INK, width=2)
    d.line([(38, 214), (132, 214)], fill=INK, width=2)
    return im


def make_course(total):
    rnd = random.Random(21)
    length = SPEED * total + 2000
    obstacles, switches = [], []
    lane, p = 1, 900.0
    while p < length:
        L = rnd.randrange(3)
        if L == lane:
            new = rnd.choice([l for l in (lane - 1, lane + 1) if 0 <= l < 3])
            switches.append((p - 360, lane, new))
            lane = new
        obstacles.append((p, L, rnd.choice(["🦘", "🪨", "🦘", "🪵"])))
        p += rnd.uniform(480, 600)
    pies = []
    for (a, _, _), (b, _, _) in zip(obstacles, obstacles[1:]):
        for k in range(4):
            cp = a + 110 + k * 85
            if cp < b - 120:
                pies.append((cp, ute_x(switches, cp)))
    return obstacles, switches, pies


def ute_x(switches, d):
    x = LANES[1]
    for s, a, b in switches:
        if d < s:
            break
        u = (d - s) / SWITCH
        x = LANES[b] if u >= 1 else LANES[a] + (LANES[b] - LANES[a]) * smooth(u)
    return x


def bottom_half(course, t):
    obstacles, switches, pies = course
    dist = t * SPEED
    img = Image.new("RGBA", (W, GH))
    off = int(dist % TILE_H)
    img.paste(ASSETS["tile"].crop((0, TILE_H - off, W, TILE_H)), (0, 0))
    if off < GH:
        img.paste(ASSETS["tile"].crop((0, 0, W, GH - off)), (0, off))
    d = ImageDraw.Draw(img)

    def sy(p):
        return UTE_Y - (p - dist)

    bx = ute_x(switches, dist)
    lean = (ute_x(switches, dist + 30) - bx) / 30
    # dust kicked up behind the ute
    rnd = random.Random(int(t * 12))
    for k in range(10):
        r = 14 + k * 5
        px, py = ute_x(switches, dist - k * 30) + rnd.uniform(-20, 20), UTE_Y + 140 + k * 28
        d.ellipse([px - r, py - r, px + r, py + r], fill=(232, 176, 124))

    got = 0
    for cp, cx in pies:
        y = sy(cp)
        if cp < dist:
            got += 1
            if cp > dist - 120:
                age = (dist - cp) / SPEED
                d.text((cx + 70, UTE_Y - 90 - age * 300), "+1", font=font(IMPACT, 46), fill=YELLOW,
                       anchor="mm", stroke_width=3, stroke_fill=INK)
            continue
        if -50 < y < GH + 50:
            paste_center(img, emoji_img("🥧", 120), cx, y, scale=0.55, angle=math.sin(t * 6 + cp) * 12)
    for p, lane, ch in obstacles:
        y = sy(p)
        if -120 < y < GH + 120:
            x = LANES[lane]
            d.ellipse([x - 70, y + 34, x + 70, y + 66], fill=(150, 76, 40))
            hop = abs(math.sin(t * 7 + p)) * 26 if ch == "🦘" else 0
            paste_center(img, emoji_img(ch, 150), x, y - hop)

    paste_center(img, ASSETS["ute"], bx, UTE_Y, angle=-lean * 7)

    # every few seconds a magpie swoops across and takes pies off the tally
    raids = int(t // STEAL_EVERY)
    got = max(0, got - raids * 2)
    phase = t % STEAL_EVERY
    if raids > 0 and phase < 1.0:
        mx = W + 120 - (W + 240) * phase
        my = UTE_Y - 60 - 160 * math.sin(phase * math.pi)
        paste_center(img, emoji_img("🐦", 280, tint=(70, 70, 80)), mx, my, scale=0.55, angle=math.sin(t * 20) * 10)
        paste_center(img, emoji_img("🥧", 120), mx - 10, my + 60, scale=0.5)
        ImageDraw.Draw(img).text((bx, UTE_Y - 170), "-2 STOLEN", font=font(IMPACT, 54), fill=RED,
                                 anchor="mm", stroke_width=4, stroke_fill=INK)

    hud = ImageDraw.Draw(img)
    rrect(hud, [24, 110, 270, 182], 36, fill=(0, 0, 0, 170))
    paste_center(img, emoji_img("🥧", 120), 68, 146, scale=0.42)
    hud.text((112, 146), f"x {got}", font=font(IMPACT, 50), fill=WHITE, anchor="lm")
    rrect(hud, [W - 340, 110, W - 24, 182], 36, fill=(0, 0, 0, 170))
    hud.text((W - 182, 146), "REAL OR FAKE", font=font(IMPACT, 46), fill=WHITE, anchor="mm")
    return img


# ---------- captions, overlays, frame ----------

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
    items = [SPOKEN_NUMBERS.get(norm(w["text"]).upper(), w["text"].upper()) for w in ch]
    probe = ImageDraw.Draw(img)
    size = 132
    while True:
        f = font(IMPACT, size)
        space = probe.textlength(" ", font=f)
        widths = [probe.textlength(t, font=f) for t in items]
        total = sum(widths) + space * (len(items) - 1)
        if total <= W - 110 or size <= 60:
            break
        size -= 6
    pad = 30
    layer = Image.new("RGBA", (int(total) + pad * 2, size + pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x = pad
    for txt, wd, w in zip(items, widths, ch):
        active = w["start"] - 0.04 <= lt <= w["end"] + 0.1
        key = re.sub(r"[^A-Z0-9]", "", txt) in KEYWORDS
        fill = (YELLOW if active else WHITE) if not key else (RED if active else (255, 140, 140))
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
    text_center(bd, 430, 75, "FOLLOW FOR MORE", font(IMPACT, 88), WHITE, stroke=4, anchor="mm")
    paste_center(img, b, W / 2, SPLIT + 400, scale=a * pulse, alpha=clamp(a * 2))


def render_frame(scenes, booms, course, total, t):
    scene = next(s for s in reversed(scenes) if t >= s["start"])
    lt = t - scene["start"]
    img = Image.new("RGBA", (W, H))
    img.paste(bottom_half(course, t), (0, SPLIT))
    img.paste(top_half(scene, lt, t), (0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([0, SPLIT - 4, W, SPLIT + 4], fill=INK)
    captions(img, scene, lt)
    if scene["id"] == "outro":
        follow_button(img, scene, lt)
    d.rectangle([0, 0, W, 10], fill=(255, 255, 255, 40))
    d.rectangle([0, 0, W * t / total, 10], fill=YELLOW)

    scene_cut = t - scene["start"] if scene is not scenes[0] else 9
    if scene_cut < 0.1:
        img.alpha_composite(Image.new("RGBA", (W, H), (255, 255, 255, int(110 * (1 - scene_cut / 0.1)))))
    out = img.convert("RGB")
    # impact: flash, zoom punch and screen shake right after each boom
    since = min((t - b for b in booms if t >= b), default=9)
    if since < 0.45:
        if since < 0.1:
            out = Image.blend(out, Image.new("RGB", (W, H), WHITE), 0.4 * (1 - since / 0.1))
        z = 1 + 0.06 * (1 - ease_out(since / 0.3)) if since < 0.3 else 1
        amp = 22 * (1 - since / 0.45)
        rnd = random.Random(int(t * FPS))
        dx, dy = rnd.uniform(-amp, amp), rnd.uniform(-amp, amp)
        cw, chh = W / z, H / z
        x0, y0 = (W - cw) / 2 - dx, (H - chh) / 2 - dy
        out = out.transform((W, H), Image.Transform.EXTENT, (x0, y0, x0 + cw, y0 + chh),
                            Image.Resampling.BILINEAR)
    return out


def main():
    scenes, total = load_timeline()
    booms = boom_times(scenes)
    load_assets(scenes)
    course = make_course(total)
    OUT.mkdir(parents=True, exist_ok=True)

    if "--preview" in sys.argv:
        times = [float(x) for x in sys.argv[sys.argv.index("--preview") + 1:]]
        for t in times:
            render_frame(scenes, booms, course, total, t).save(OUT / f"preview_{t:05.1f}.png")
        print("scene starts:", [(s["id"], round(s["start"], 2)) for s in scenes], "total", round(total, 2))
        return

    audio = build_audio(scenes, total)
    out = OUT / "aussie_fake_or_real.mp4"
    ff = subprocess.Popen([
        "ffmpeg", "-y", "-v", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
        "-i", str(audio),
        "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out),
    ], stdin=subprocess.PIPE)
    frames = int(total * FPS)
    for i in range(frames):
        ff.stdin.write(render_frame(scenes, booms, course, total, i / FPS).tobytes())
        if i % 150 == 0:
            print(f"frame {i}/{frames}", file=sys.stderr)
    ff.stdin.close()
    ff.wait()
    print(out)


if __name__ == "__main__":
    main()
