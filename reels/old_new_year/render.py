"""Render 'The country where people celebrate New Year 13 days later' (1080x1920, 30fps).

Brainrot layout: the calendar story plays on top (a delete-13-days popup, flying calendar
pages, the holiday loop), a top-down "gameplay" clip runs on the bottom (a bear on a sled
dodging trees and collecting dumplings), big punchy captions sit on the seam.
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
OUT = ROOT / "output" / "old_new_year"
VO = OUT / "vo"

W, H, FPS = 1080, 1920, 30
SR = 48000
PAD = 0.25  # silence after each scene's line
SPLIT = 1060  # story above, gameplay below

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
KEYWORDS = {"OLD", "13", "11", "RUSSIA", "RUSSIAN", "JULIAN", "BY1918", "DELETED", "FEBRUARY", "FOURTEENTH",
            "CHRISTMAS", "SEVENTH", "AGAIN", "DUMPLINGS", "IN2101", "FIFTEENTH", "TWICE"}
SPOKEN_NUMBERS = {"THIRTEEN": "13", "ELEVEN": "11"}

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
    # a click on the delete popup, then a paper flick per calendar page flying off
    skip = next(s for s in scenes if s["id"] == "skip")
    el = int(0.05 * SR)
    click = np.sin(2 * np.pi * 1400 * np.arange(el) / SR) * tone_env(el, 80)
    add(fx, skip["start"] + skip["cue_t"]["deleted"], click, 0.35)
    fl = int(0.06 * SR)
    flick = rng.standard_normal(fl) * tone_env(fl, 60)
    for k in range(13):
        add(fx, skip["start"] + skip["cue_t"]["woke"] - 0.2 + k * 0.05, flick, 0.16)

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


def emoji_img(ch, size=280, mirror=False):
    key = (ch, size, mirror)
    if key not in _emoji_cache:
        f = font(EMOJI, size)
        probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        x0, y0, x1, y1 = probe.textbbox((0, 0), ch, font=f, embedded_color=True)
        im = Image.new("RGBA", (x1 - x0 + 8, y1 - y0 + 8), (0, 0, 0, 0))
        ImageDraw.Draw(im).text((4 - x0, 4 - y0), ch, font=f, embedded_color=True)
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


def flag(w=300, h=200):
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for i, col in enumerate((WHITE, (0, 57, 166), (213, 43, 30))):
        d.rectangle([0, i * h / 3, w, (i + 1) * h / 3], fill=col)
    d.rectangle([0, 0, w - 1, h - 1], outline=INK, width=4)
    return im


def wavy(im, t, amp=8):
    """Flag ripple: shift vertical strips by a travelling sine."""
    out = Image.new("RGBA", (im.width, im.height + amp * 2), (0, 0, 0, 0))
    for x in range(0, im.width, 10):
        dy = amp + amp * math.sin(x * 0.03 - t * 6) * (x / im.width)
        out.paste(im.crop((x, 0, x + 10, im.height)), (x, int(dy)))
    return out


# ---------- shared story pieces ----------

_cal_cache = {}


def cal_card(month, day, w=420, col=RED):
    """Tear-off calendar page."""
    key = (month, day, w, col)
    if key not in _cal_cache:
        k = w / 480
        im = Image.new("RGBA", (w, w), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        rrect(d, [4, 4, w - 4, w - 4], int(40 * k), fill=WHITE, outline=INK, width=max(4, int(6 * k)))
        rrect(d, [4, 4, w - 4, int(130 * k)], int(40 * k), fill=col, outline=INK, width=max(4, int(6 * k)))
        d.rectangle([10, int(90 * k), w - 10, int(126 * k)], fill=col)
        f = fit_font(d, month, IMPACT, int(84 * k), w - 40, min_size=16)
        text_center(d, w / 2, 68 * k, month, f, WHITE, anchor="mm")
        text_center(d, w / 2, 305 * k, day, fit_font(d, day, IMPACT, int(270 * k), w - 50), INK, anchor="mm")
        _cal_cache[key] = im
    return _cal_cache[key]


def pop_card(img, card, x, y, p, angle=0.0):
    paste_center(img, card, x, y, scale=max(0.0, ease_back(p)), alpha=clamp(p * 3), angle=angle)


def fireworks(img, lt, spots):
    """Looping radial bursts behind a scene."""
    d = ImageDraw.Draw(img)
    for i, (x, y, col) in enumerate(spots):
        age = (lt + i * 0.45) % 1.35
        for k in range(16):
            a = k * math.pi / 8 + i
            r = 150 * ease_out(age / 0.9)
            s = max(0.0, 7 * (1 - age / 1.35))
            px, py = x + r * math.cos(a), y + r * math.sin(a) + 40 * age * age
            d.ellipse([px - s, py - s, px + s, py + s], fill=col)


def snow(img, t, n=60, seed=4, height=None):
    d = ImageDraw.Draw(img)
    rnd = random.Random(seed)
    height = height or img.height
    for _ in range(n):
        x0, y0, v, r = rnd.uniform(0, W), rnd.uniform(0, height), rnd.uniform(60, 170), rnd.uniform(2, 5)
        x = (x0 + math.sin(t + y0) * 18) % W
        y = (y0 + t * v) % height
        d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, 190))


def arrow(d, a, b, col=WHITE, width=8):
    d.line([a, b], fill=INK, width=width + 6)
    d.line([a, b], fill=col, width=width)
    ang = math.atan2(b[1] - a[1], b[0] - a[0])
    head = [b, (b[0] - 30 * math.cos(ang - 0.5), b[1] - 30 * math.sin(ang - 0.5)),
            (b[0] - 30 * math.cos(ang + 0.5), b[1] - 30 * math.sin(ang + 0.5))]
    d.polygon(head, fill=col, outline=INK)


def make_top_bg():
    y = np.linspace(0, 1, SPLIT)[:, None, None]
    img = np.array([26, 22, 66]) + (np.array([10, 12, 34]) - np.array([26, 22, 66])) * y
    img = np.broadcast_to(img, (SPLIT, W, 3)).copy()
    return Image.fromarray(img.astype(np.uint8)).convert("RGBA")


ASSETS = {}


def load_assets():
    ASSETS["top_bg"] = make_top_bg()
    ASSETS["flag"] = flag()
    ASSETS["tile"] = make_snow_tile()
    ASSETS["sled"] = make_sled()


# ---------- story scenes (top half) ----------

def scene_hook(img, s, lt):
    c = s["cue_t"]
    fireworks(img, lt, [(180, 300, YELLOW), (900, 280, (255, 120, 200)), (540, 900, (120, 220, 255))])
    sticker(img, "NEW YEAR x2 🎉", 540, 262, prog(lt, c["twice"] - 0.1, 0.35), size=70)
    pop_card(img, cal_card("JANUARY", "1", 380), 280, 540, prog(lt, c["january"] - 0.05, 0.35), angle=-4)
    pop_card(img, cal_card("JANUARY", "14", 380), 800, 540, prog(lt, c["thirteen"] - 0.05, 0.35), angle=4)
    sticker(img, "+13 DAYS", 540, 540, prog(lt, c["thirteen"] + 0.15, 0.3), size=60, bg=RED, fg=WHITE, angle=-8)
    if lt >= c["january"]:
        sticker(img, "NEW YEAR 🎆", 280, 800, prog(lt, c["january"] + 0.1, 0.3), size=54, bg=WHITE)
    sticker(img, "OLD NEW YEAR 🤨", 760, 800, prog(lt, c["old"] - 0.05, 0.3), size=62, bg=RED, fg=WHITE, angle=-4)


def scene_bug(img, s, lt):
    c = s["cue_t"]
    sticker(img, "CALENDAR BUG 🐛", 540, 262, prog(lt, c["calendar"] - 0.1, 0.35), size=72, bg=GREEN)
    u = lt / s["dur"]  # the bug itself crawls across the scene
    paste_center(img, emoji_img("🐛", 150), -80 + 1240 * u, 660 + math.sin(lt * 6) * 28, scale=0.85,
                 angle=math.sin(lt * 10) * 10)
    fp = ease_back(prog(lt, c["russia"] - 0.1, 0.4))
    paste_center(img, wavy(ASSETS["flag"], lt), 290, 470, scale=max(0.0, fp))
    if fp > 0.3:
        text_center(ImageDraw.Draw(img), 290, 590, "RUSSIA", font(IMPACT, 66), WHITE, stroke=5)
    pop_card(img, cal_card("JULIAN", "45 BC", 340, (150, 110, 40)), 790, 480, prog(lt, c["julian"] - 0.1, 0.35),
             angle=4)
    ep = prog(lt, c["eleven"] - 0.05, 0.3)
    paste_center(img, emoji_img("⏰", 170), 170, 850, scale=ease_back(ep), angle=math.sin(lt * 18) * 10)
    sticker(img, "+11 MIN EVERY YEAR", 610, 850, ep, size=68, bg=RED, fg=WHITE, angle=-3)


CLOCKS = [(x, y) for y, xs in ((350, (180, 360, 540, 720, 900)), (450, (270, 450, 630, 810)),
                               (550, (360, 540, 720))) for x in xs]


def scene_drift(img, s, lt):
    c = s["cue_t"]
    fill = prog(lt, c["stacks"] - 0.1, c["thirteen"] - c["stacks"])
    year = 1582 + int(336 * smooth(fill))
    sticker(img, f"YEAR {year}", 540, 256, prog(lt, 0, 0.25), size=66, bg=WHITE)
    for i, (x, y) in enumerate(CLOCKS):
        p = prog(fill, i / 13, 0.1)
        if p > 0:
            paste_center(img, emoji_img("⏰", 120), x, y, scale=0.8 * ease_back(p),
                         angle=math.sin(lt * 12 + i) * 8)
    tp = prog(lt, c["thirteen"] - 0.05, 0.3)
    pop_card(img, cal_card("RUSSIA", "1", 250, (40, 90, 200)), 270, 760, tp, angle=-3)
    pop_card(img, cal_card("EUROPE", "14", 250, (40, 150, 90)), 810, 760, tp, angle=3)
    sticker(img, "13 DAYS BEHIND 💀", 540, 760, prog(lt, c["thirteen"] + 0.2, 0.3), size=46, bg=RED, fg=WHITE)


def delete_dialog(img, lt, c):
    a = prog(lt, 0.05, 0.25) * (1 - prog(lt, c["people"] - 0.15, 0.15))
    if a <= 0:
        return
    box = Image.new("RGBA", (860, 420), (0, 0, 0, 0))
    d = ImageDraw.Draw(box)
    d.rectangle([0, 0, 859, 419], fill=(236, 236, 236), outline=INK, width=4)
    d.rectangle([4, 4, 855, 68], fill=(0, 90, 200))
    d.text((24, 36), "Russia.exe - 1918", font=font(SEMI, 38), fill=WHITE, anchor="lm")
    d.rectangle([800, 12, 846, 58], fill=(220, 50, 50))
    d.text((823, 34), "x", font=font(BOLD, 34), fill=WHITE, anchor="mm")
    paste_center(box, emoji_img("⚠", 120), 110, 195, scale=0.9)
    d.text((200, 165), "DELETE 13 DAYS?", font=font(IMPACT, 76), fill=INK, anchor="lm")
    d.text((200, 235), "This cannot be undone.", font=font(SEMI, 36), fill=(90, 90, 90), anchor="lm")
    clicked = lt >= c["deleted"]
    d.rectangle([330, 310, 560, 390], fill=(80, 210, 110) if clicked else (225, 225, 225),
                outline=(0, 90, 200), width=4)
    d.text((445, 350), "YES", font=font(BOLD, 42), fill=INK, anchor="mm")
    d.rectangle([590, 310, 820, 390], fill=(225, 225, 225), outline=(150, 150, 150), width=3)
    d.text((705, 350), "NO", font=font(SEMI, 42), fill=(140, 140, 140), anchor="mm")
    paste_center(img, box, 540, 560, scale=0.6 + 0.4 * ease_back(a), alpha=clamp(a * 3))
    # cursor glides to YES and clicks on the word
    cu = smooth(prog(lt, c["deleted"] - 0.6, 0.55))
    cx, cy = 940 + (420 - 940) * cu, 940 + (720 - 940) * cu
    cur = Image.new("RGBA", (60, 80), (0, 0, 0, 0))
    ImageDraw.Draw(cur).polygon([(4, 4), (4, 66), (20, 52), (32, 76), (44, 70), (32, 46), (52, 44)],
                                fill=WHITE, outline=INK, width=3)
    paste_center(img, cur, cx, cy, scale=0.9 if clicked and lt < c["deleted"] + 0.12 else 1.1, alpha=clamp(a * 3))


def scene_skip(img, s, lt):
    c = s["cue_t"]
    delete_dialog(img, lt, c)
    if lt < c["people"] - 0.1:
        return
    done = lt >= c["february"] - 0.03
    card = cal_card("FEBRUARY", "14", 440) if done else cal_card("JANUARY", "31", 440)
    paste_center(img, card, 540, 520, scale=max(0.0, ease_back(prog(lt, c["people"] - 0.1, 0.3))),
                 angle=-3 if done else 2)
    if not done:
        bp = prog(lt, c["bed"] - 0.1, 0.3)
        paste_center(img, emoji_img("🛏", 180), 160, 780, scale=ease_back(bp))
        paste_center(img, emoji_img("😴", 150), 910, 780, scale=ease_back(bp), angle=math.sin(lt * 3) * 8)
    # the thirteen missing days fly off the wall
    rnd = random.Random(13)
    for i in range(13):
        vx, vy, spin = rnd.uniform(-1, 1), rnd.uniform(-0.5, 0.7), rnd.uniform(-540, 540)
        q = prog(lt, c["woke"] - 0.2 + i * 0.05, 0.55)
        if 0 < q < 1:
            paste_center(img, cal_card("FEB", str(i + 1), 200, (120, 120, 130)),
                         540 + vx * 760 * q, 520 + vy * 620 * q, scale=1.0, angle=spin * q)
    if done:
        fp = prog(lt, c["february"], 0.3)
        paste_center(img, emoji_img("😳", 170), 900, 340, scale=ease_back(fp), angle=10)
        paste_center(img, emoji_img("💘", 150), 180, 340, scale=ease_back(fp), angle=-10)
        sticker(img, "FEB 1-13: NEVER HAPPENED ❌", 540, 840, fp, size=56, bg=RED, fg=WHITE, angle=-2)


def scene_church(img, s, lt):
    c = s["cue_t"]
    p = prog(lt, c["church"] - 0.15, 0.35)
    paste_center(img, emoji_img("⛪", 280), 280, 520, scale=ease_back(p), angle=math.sin(lt * 2) * 2)
    sticker(img, "KEPT THE OLD CALENDAR 📜", 540, 262, prog(lt, c["old"] - 0.1, 0.35), size=60, bg=YELLOW)
    cp = prog(lt, c["christmas"] - 0.1, 0.35)
    pop_card(img, cal_card("JANUARY", "7", 400, (30, 140, 80)), 780, 530, cp, angle=3)
    sticker(img, "RUSSIAN CHRISTMAS 🎄", 540, 820, prog(lt, c["christmas"], 0.3), size=68, bg=GREEN)


def scene_loop(img, s, lt):
    c = s["cue_t"]
    sticker(img, "THE RUSSIAN HOLIDAY LOOP 🔁", 540, 262, prog(lt, 0, 0.3), size=58, bg=WHITE)
    beats = (("new", "1", 190, RED, "NEW YEAR 🎆"), ("christmas", "7", 540, (30, 140, 80), "CHRISTMAS 🎄"),
             ("again", "14", 890, RED, "NEW YEAR 🎆"))
    d = ImageDraw.Draw(img)
    for x in (365, 715):
        if lt >= c["christmas" if x == 365 else "again"] - 0.2:
            arrow(d, (x - 26, 490), (x + 26, 490), col=YELLOW)
    for cue, day, x, col, label in beats:
        p = prog(lt, c[cue] - 0.05, 0.3)
        pop_card(img, cal_card("JAN", day, 280, col), x, 490, p)
        sticker(img, label, x, 680, p, size=44, bg=YELLOW)
    sticker(img, "NEW YEAR 2: THE SEQUEL 🍿", 540, 830, prog(lt, c["again"] + 0.05, 0.3), size=64, bg=RED, fg=WHITE,
            angle=-3)


def scene_food(img, s, lt):
    c = s["cue_t"]
    sticker(img, "DAY OFF? ❌ NOPE", 540, 262, prog(lt, c["day"] - 0.05, 0.3), size=74, bg=RED, fg=WHITE, angle=-2)
    tp = prog(lt, c["tree"] - 0.1, 0.35)
    paste_center(img, emoji_img("🎄", 300), 270, 540, scale=ease_back(tp), angle=math.sin(lt * 2.5) * 3)
    sticker(img, "STILL UP", 270, 760, tp, size=54, bg=GREEN)
    dp = prog(lt, c["dumplings"] - 0.1, 0.35)
    for i, (x, y) in enumerate(((700, 560), (880, 560), (790, 440))):
        paste_center(img, emoji_img("🥟", 180), x, y + math.sin(lt * 5 + i) * 10, scale=ease_back(dp))
    sp = prog(lt, c["surprises"] - 0.05, 0.35)
    paste_center(img, emoji_img("🪙", 120), 790, 340 + (1 - ease_out(sp)) * 90, scale=ease_back(sp),
                 angle=lt * 200 % 360)
    sticker(img, "SURPRISE INSIDE 🤫", 790, 760, sp, size=54, bg=YELLOW, angle=2)


def scene_outro(img, s, lt):
    c = s["cue_t"]
    sticker(img, "YEAR 2101 🤖", 540, 262, prog(lt, c["in2101"] - 0.1, 0.35), size=72, bg=WHITE)
    moved = lt >= c["fifteenth"] - 0.03
    card = cal_card("JANUARY", "15" if moved else "14", 460)
    paste_center(img, card, 540, 550, scale=max(0.0, ease_back(prog(lt, 0, 0.35))) * (1 + 0.04 * math.sin(lt * 6)),
                 angle=math.sin(lt * 3) * 3)
    gp = prog(lt, c["gap"] - 0.1, 0.3)
    sticker(img, "GAP: 14 DAYS" if lt >= c["gap"] else "GAP: 13 DAYS", 220, 860, gp, size=54, bg=RED, fg=WHITE, angle=-5)
    if moved:
        fp = prog(lt, c["fifteenth"], 0.3)
        sticker(img, "NEW DATE 💀", 840, 860, fp, size=56, bg=YELLOW, angle=4)
        fireworks(img, lt, [(150, 420, YELLOW), (930, 440, (255, 120, 200))])


SCENE_DRAW = {"hook": scene_hook, "bug": scene_bug, "drift": scene_drift, "skip": scene_skip,
              "church": scene_church, "loop": scene_loop, "food": scene_food, "outro": scene_outro}


def header(img):
    d = ImageDraw.Draw(img)
    text_center(d, W / 2, 26, "THE COUNTRY WHERE NEW YEAR", font(IMPACT, 58), WHITE, stroke=5)
    text_with_emoji(img, W / 2, 132, "COMES 13 DAYS LATE 🤔", font(IMPACT, 78), YELLOW, stroke=6)


def top_half(scene, lt, t):
    img = ASSETS["top_bg"].copy()
    snow(img, t, n=45)
    SCENE_DRAW[scene["id"]](img, scene, lt)
    if "header" not in ASSETS:
        h = Image.new("RGBA", (W, 190), (0, 0, 0, 0))
        hd = ImageDraw.Draw(h)
        for y in range(190):  # fade so the header reads over any scene
            hd.line([(0, y), (W, y)], fill=(6, 8, 18, int(220 * clamp(1.25 - y / 190))))
        header(h)
        ASSETS["header"] = h
    img.alpha_composite(ASSETS["header"])
    return img


# ---------- gameplay (bottom half) ----------

GH = H - SPLIT
SLOPE = (150, 930)
LANES = [310, 540, 770]
SPEED = 640  # world px per second
SLED_Y = GH - 200
SWITCH = 210  # travel distance for a lane change
TILE_H = GH * 4


def make_snow_tile():
    """Seamless vertical tile: a groomed snow run between fir-tree banks."""
    im = Image.new("RGBA", (W, TILE_H), (206, 224, 240, 255))
    d = ImageDraw.Draw(im)
    rnd = random.Random(9)
    left, right = [], []
    for y in range(0, TILE_H + 1, 20):
        wob = 22 * math.sin(2 * math.pi * y / TILE_H * 5) + 10 * math.sin(2 * math.pi * y / TILE_H * 13)
        left.append((SLOPE[0] + wob, y))
        right.append((SLOPE[1] + wob * 0.8, y))
    d.polygon(left + right[::-1], fill=(244, 249, 255))
    for _ in range(200):
        y = rnd.uniform(0, TILE_H)
        x = rnd.uniform(SLOPE[0] + 40, SLOPE[1] - 80)
        L = rnd.uniform(16, 44)
        for yy in (y, y - TILE_H, y + TILE_H):
            d.line([x, yy, x, yy + L], fill=(218, 232, 246), width=3)
    for k in range(40):
        side = k % 2
        y = (k + rnd.uniform(0, 0.6)) * TILE_H / 40
        x = rnd.uniform(20, SLOPE[0] - 40) if side == 0 else rnd.uniform(SLOPE[1] + 40, W - 20)
        ch = "⛄" if rnd.random() < 0.12 else "🌲"
        for yy in (y, y - TILE_H, y + TILE_H):
            paste_center(im, emoji_img(ch, 120, mirror=side == 1), x, yy, scale=0.9)
    return im


def make_sled():
    """Top-down red sled with a bear passenger."""
    im = Image.new("RGBA", (150, 240), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for x in (22, 118):
        d.line([(x, 20), (x, 228)], fill=(90, 96, 110), width=9)
        d.arc([x - 2, 2, x + 24 if x < 75 else x + 2, 40], 180, 300, fill=(90, 96, 110), width=9)
    rrect(d, [30, 40, 120, 222], 22, fill=(214, 40, 40), outline=INK, width=5)
    for y in (70, 110, 150, 190):
        d.line([(36, y), (114, y)], fill=(150, 24, 24), width=4)
    paste_center(im, emoji_img("🐻", 120), 75, 120, scale=0.8)
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
        obstacles.append((p, L, rnd.choice(["🎄", "⛄", "🪨", "🎄"])))
        p += rnd.uniform(480, 600)
    dumplings = []
    for (a, _, _), (b, _, _) in zip(obstacles, obstacles[1:]):
        for k in range(4):
            cp = a + 110 + k * 85
            if cp < b - 120:
                dumplings.append((cp, sled_x(switches, cp)))
    return obstacles, switches, dumplings


def sled_x(switches, d):
    x = LANES[1]
    for s, a, b in switches:
        if d < s:
            break
        u = (d - s) / SWITCH
        x = LANES[b] if u >= 1 else LANES[a] + (LANES[b] - LANES[a]) * smooth(u)
    return x


def bottom_half(course, t):
    obstacles, switches, dumplings = course
    dist = t * SPEED
    img = Image.new("RGBA", (W, GH))
    off = int(dist % TILE_H)
    img.paste(ASSETS["tile"].crop((0, TILE_H - off, W, TILE_H)), (0, 0))
    if off < GH:
        img.paste(ASSETS["tile"].crop((0, 0, W, GH - off)), (0, off))
    d = ImageDraw.Draw(img)

    def sy(p):
        return SLED_Y - (p - dist)

    bx = sled_x(switches, dist)
    lean = (sled_x(switches, dist + 30) - bx) / 30
    # twin runner tracks carved behind the sled
    trail = [(sled_x(switches, dist - k * 30), SLED_Y + 100 + k * 30) for k in range(12)]
    for off_x in (-52, 44):
        d.line([(x + off_x, y) for x, y in trail], fill=(176, 198, 224), width=8)

    got = 0
    for cp, cx in dumplings:
        y = sy(cp)
        if cp < dist:
            got += 1
            if cp > dist - 120:
                age = (dist - cp) / SPEED
                d.text((cx + 60, SLED_Y - 80 - age * 300), "+1", font=font(IMPACT, 46), fill=(255, 150, 0),
                       anchor="mm", stroke_width=3, stroke_fill=INK)
            continue
        if -50 < y < GH + 50:
            paste_center(img, emoji_img("🥟", 120), cx, y, scale=0.55, angle=math.sin(t * 6 + cp) * 12)
    for p, lane, ch in obstacles:
        y = sy(p)
        if -120 < y < GH + 120:
            x = LANES[lane]
            d.ellipse([x - 70, y + 34, x + 70, y + 66], fill=(190, 208, 228))
            paste_center(img, emoji_img(ch, 150), x, y)

    paste_center(img, ASSETS["sled"], bx, SLED_Y, angle=-lean * 12)
    snow(img, t * 1.4, n=40, seed=8)

    hud = ImageDraw.Draw(img)
    rrect(hud, [24, 110, 270, 182], 36, fill=(0, 0, 0, 170))
    paste_center(img, emoji_img("🥟", 120), 68, 146, scale=0.42)
    hud.text((112, 146), f"x {got}", font=font(IMPACT, 50), fill=WHITE, anchor="lm")
    rrect(hud, [W - 340, 110, W - 24, 182], 36, fill=(0, 0, 0, 170))
    hud.text((W - 182, 146), "13 DAYS LATE", font=font(IMPACT, 46), fill=WHITE, anchor="mm")
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
    load_assets()
    course = make_course(total)
    OUT.mkdir(parents=True, exist_ok=True)

    if "--preview" in sys.argv:
        times = [float(x) for x in sys.argv[sys.argv.index("--preview") + 1:]]
        for t in times:
            render_frame(scenes, booms, course, total, t).save(OUT / f"preview_{t:05.1f}.png")
        print("scene starts:", [(s["id"], round(s["start"], 2)) for s in scenes], "total", round(total, 2))
        return

    audio = build_audio(scenes, total)
    out = OUT / "old_new_year_russia.mp4"
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
