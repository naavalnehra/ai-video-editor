"""Render 'How long you'd survive after a bite from...' (1080x1920, 30fps).

Clipper layout: each animal and its seven-segment countdown plays on top with a running leaderboard,
a top-down "gameplay" clip runs on the bottom (an ambulance weaving through traffic toward a hospital
it reaches at the end), big punchy captions sit on the seam. Music is a dark orchestral loop mixed
well under the voice, see MUSIC_DB.
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
OUT = ROOT / "output" / "bite_countdown"
VO = OUT / "voice"

W, H, FPS = 1080, 1920, 30
SR = 48000
PAD = 0.2  # silence after each scene's line
SPLIT = 1060  # story above, gameplay below
MUSIC_DB = -18.0  # music RMS relative to the voice, before ducking
SFX = 0.5

FONTS = Path("C:/Windows/Fonts")
IMPACT = str(FONTS / "impact.ttf")
BOLD = str(FONTS / "seguibl.ttf")
EMOJI = str(FONTS / "seguiemj.ttf")

WHITE = (255, 255, 255)
INK = (10, 10, 16)
YELLOW = (255, 230, 0)
RED = (255, 44, 44)
GREEN = (60, 230, 110)
KEYWORDS = {"BITTEN", "15", "3", "2", "20", "45", "HOURS", "MINUTES", "ANTIVENOM", "VENTILATOR", "PARALYSIS",
            "ZERO", "SCARIEST", "RABID", "FATAL", "SHOTS", "TREATED", "1981"}

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
        dur = len(audio) / SR + s.get("hold", PAD)
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
    """Clipper captions: one or two words at a time, split at pauses."""
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


def timer_state(s, lt):
    """Value on an animal's clock at lt, and whether it's scrambling, running, stopped or out."""
    start = s["cue_t"][s["reveal"]] if "reveal" in s else 0.0
    if lt < start:
        return None, "scramble"
    left = 1 - s.get("drain_to", 0.0)

    def value(x):
        u = prog(x, start + 0.3, s["dur"] - 0.6 - start - 0.3)
        return s["timer"] * (1 - left * u ** 1.6)
    if "stop" in s and lt >= s["cue_t"][s["stop"]]:
        return value(s["cue_t"][s["stop"]]), "stopped"
    v = value(lt)
    return v, ("out" if v < 1 else "run")


# ---------- audio ----------

def tone_env(n, decay):
    return np.exp(-np.arange(n) / SR * decay)


def saw(freq, n, harmonics=7):
    t = np.arange(n) / SR
    return sum(np.sin(2 * np.pi * freq * k * t) / k for k in range(1, harmonics + 1))


def rms(x):
    return float(np.sqrt(np.mean(x ** 2) + 1e-12))


def build_audio(scenes, total):
    n = int(total * SR) + SR
    voice = np.zeros(n, np.float32)
    for s in scenes:
        i = int(s["start"] * SR)
        voice[i:i + len(s["audio"])] += s["audio"]

    rng = np.random.default_rng(47)
    by_id = {s["id"]: s for s in scenes}
    clock = np.arange(n) / SR

    def add(buf, at, sig, gain):
        i = int(at * SR)
        if i >= n or i < 0:
            return
        m = min(len(sig), n - i)
        buf[i:i + m] += gain * sig[:m]

    # how hard the score plays: climbs animal by animal, drops out for the twist, returns on the dog
    almost = by_id["dog"]["start"] + by_id["dog"]["cue_t"]["almost"]
    quiet_from = by_id["twist"]["start"]
    points = []
    for sid, lvl in (("hook", 0.5), ("mamba", 0.55), ("cobra", 0.65), ("taipan", 0.75),
                     ("octopus", 0.85), ("funnel", 1.0), ("shots", 0.8), ("outro", 0.45)):
        s = by_id[sid]
        points += [(s["start"] + 0.05, lvl), (s["start"] + s["dur"] - 0.05, lvl)]
    points += [(quiet_from, 0.0), (almost - 0.02, 0.0), (almost + 0.02, 1.0), (by_id["shots"]["start"], 1.0)]
    points.sort()
    level = np.interp(clock, [p[0] for p in points], [p[1] for p in points]).astype(np.float32)

    # D minor score at 96 bpm: bars walk D, D, Bb, A under a staccato string ostinato and taiko
    beat = 60 / 96
    six = beat / 4
    bar = beat * 4
    roots = [73.42, 73.42, 58.27, 55.0]
    pads = [(293.66, 349.23, 440.0), (293.66, 349.23, 466.16), (293.66, 349.23, 466.16), (277.18, 329.63, 440.0)]
    low, mid, top, drums = (np.zeros(n, np.float32) for _ in range(4))
    bar_n = int(bar * SR)
    tail = int(0.15 * SR)
    ramp = np.arange(bar_n + tail)
    fade = np.minimum(np.minimum(ramp / (0.05 * SR), 1), (bar_n + tail - ramp) / tail)
    tremolo = 0.65 + 0.35 * np.sin(2 * np.pi * 11 * ramp / SR)
    k = 0
    while k * bar < total:
        i = k % 4
        add(low, k * bar, saw(roots[i], bar_n + tail, 4) * fade, 0.28)
        add(top, k * bar, sum(saw(f, bar_n + tail, 3) for f in pads[i]) * tremolo * fade, 0.3)
        k += 1
    stab_n = int(0.2 * SR)
    key = [[146.83, 155.56, 174.61, 220.0], [146.83, 155.56, 174.61, 220.0],
           [116.54, 146.83, 174.61, 220.0], [110.0, 155.56, 174.61, 220.0]]
    stabs = {f: saw(f, stab_n, 6) * tone_env(stab_n, 16) for row in key for f in row}
    riff = [0, None, 0, 1, 0, None, 2, 1, 0, None, 0, 1, 3, None, 2, 1]
    tl = int(0.4 * SR)
    tt = np.arange(tl) / SR
    taiko = np.sin(2 * np.pi * np.cumsum(58 + 60 * np.exp(-tt * 30)) / SR) * tone_env(tl, 8)
    taiko = taiko + 0.2 * np.convolve(rng.standard_normal(tl), np.ones(24) / 24, mode="same") * tone_env(tl, 40)
    k = 0
    while k * six < total:
        step = k % 16
        note = riff[step]
        if note is not None:
            add(mid, k * six, stabs[key[(k // 16) % 4][note]], 0.55)
        if step in (0, 3, 8, 11, 14):
            add(drums, k * six, taiko, 0.5 if step in (0, 8) else 0.3)
        k += 1
    music = low + level * mid + level ** 1.5 * top + level * drums

    # the twist and the dog's "you feel fine" stretch: one held note and slow, lonely pings
    eerie = np.zeros(n, np.float32)
    ql = int((almost - quiet_from) * SR)
    add(eerie, quiet_from, np.sin(2 * np.pi * 587.33 * np.arange(ql) / SR) * np.minimum(np.arange(ql) / (0.3 * SR), 1), 0.35)
    pl = int(1.6 * SR)
    ping = np.sin(2 * np.pi * 880 * np.arange(pl) / SR) * tone_env(pl, 3.5)
    at = by_id["dog"]["start"] + 0.2
    while at < almost:
        add(eerie, at, ping, 0.8)
        at += 1.5
    gap = (clock >= quiet_from) & (clock < almost)
    music = np.where(gap, 0.25 * low, music) + eerie

    # music level is set against the voice so it stays low whatever the render's length
    music *= rms(voice[voice != 0]) * 10 ** (MUSIC_DB / 20) / rms(music[: int(total * SR)])

    fx = np.zeros(n, np.float32)

    def whoosh(length):
        wl = int(length * SR)
        env = np.sin(np.linspace(0, np.pi, wl)) ** 2
        return np.convolve(rng.standard_normal(wl), np.ones(10) / 10, mode="same") * env

    for s in scenes[1:]:
        add(fx, s["start"] - 0.15, whoosh(0.4), 0.14)
    vl = int(1.4 * SR)
    vt = np.arange(vl) / SR
    boom = np.sin(2 * np.pi * np.cumsum(44 + 70 * np.exp(-vt * 14)) / SR)
    boom = np.tanh(3 * boom) * tone_env(vl, 3)
    for b in boom_times(scenes):
        add(fx, b, boom, 0.34)

    # clock ticks speed up as each timer drains; a dead tone if it runs out, a chime if it's stopped
    tick_n = int(0.03 * SR)
    tick = np.sin(2 * np.pi * 2400 * np.arange(tick_n) / SR) * tone_env(tick_n, 170)
    chime_n = SR
    ct = np.arange(chime_n) / SR
    chime = (np.sin(2 * np.pi * 587.33 * ct) + np.sin(2 * np.pi * 880 * ct)) * tone_env(chime_n, 5)
    flat_n = int(0.6 * SR)
    flat = np.sin(2 * np.pi * 988 * np.arange(flat_n) / SR) * np.minimum((flat_n - np.arange(flat_n)) / (0.05 * SR), 1)
    for s in scenes:
        if "timer" not in s:
            continue
        begin = s["cue_t"][s["reveal"]] + 0.3 if "reveal" in s else 0.3
        finish = s["cue_t"][s["stop"]] if "stop" in s else s["dur"] - 0.6
        lt = begin
        while lt < finish:
            add(fx, s["start"] + lt, tick, 0.16)
            lt += 0.09 + 0.3 * (1 - prog(lt, begin, finish - begin))
        if "stop" in s:
            add(fx, s["start"] + finish, chime, 0.1)
        elif "drain_to" not in s:
            add(fx, s["start"] + finish, flat, 0.05)

    # heartbeat under the twist and the dog's calm
    hb_n = int(0.25 * SR)
    hb = np.sin(2 * np.pi * 52 * np.arange(hb_n) / SR) * tone_env(hb_n, 14)
    at = quiet_from
    while at < almost:
        add(fx, at, hb, 0.5)
        add(fx, at + 0.26, hb, 0.34)
        at += 0.95

    # duck music under the voice so it never competes with the words
    vol = np.convolve(np.abs(voice), np.ones(2400) / 2400, mode="same")
    duck = 1 - 0.4 * np.clip(vol / (vol.max() * 0.25 + 1e-9), 0, 1)
    ducked = music * duck

    speaking = vol > vol.max() * 0.08
    print(f"voice {20 * np.log10(rms(voice[speaking])):.1f} dB, music under voice "
          f"{20 * np.log10(rms(ducked[speaking])):.1f} dB, gap "
          f"{20 * np.log10(rms(voice[speaking]) / rms(ducked[speaking])):.1f} dB", file=sys.stderr)

    mix = voice * 1.0 + ducked + SFX * fx
    fade_n = int(0.8 * SR)
    end = int(total * SR)
    mix[end - fade_n:end] *= np.linspace(1, 0, fade_n)
    mix = mix[:end]
    mix /= np.abs(mix).max() / 0.95

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
    paste_center(img, _sticker_cache[key], cx, cy, scale=scale * max(0.0, s), alpha=clamp(p * 3), angle=angle)


_stamp_cache = {}


def stamp(img, text, col, cx, cy, p, size=110, angle=-7):
    """Rubber-stamp verdict: slams down from oversized, p is raw 0..1 progress."""
    if p <= 0:
        return
    key = (text, col, size)
    if key not in _stamp_cache:
        f = font(IMPACT, size)
        w = int(ImageDraw.Draw(Image.new("RGBA", (1, 1))).textlength(text, font=f)) + 80
        h = int(size * 1.5)
        st = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(st)
        rrect(d, [4, 4, w - 4, h - 4], 24, fill=(255, 255, 255, 240), outline=col, width=max(6, size // 11))
        text_center(d, w / 2, h / 2, text, f, col, anchor="mm")
        _stamp_cache[key] = st
    paste_center(img, _stamp_cache[key], cx, cy, scale=2.0 - ease_out(p), alpha=clamp(p * 4), angle=angle)


# ---------- seven-segment timer ----------

SEGMENTS = {"0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc", "5": "afgcd", "6": "afgedc",
            "7": "abc", "8": "abcdefg", "9": "abcdfg"}
_seg_cache = {}


def seg_polys(w, h, t):
    """Each segment as a bevelled bar; w and h are the digit's size, t its stroke thickness."""
    g, m = t * 0.14, h / 2

    def hbar(y):
        return [(t / 2 + g, y), (t + g, y - t / 2), (w - t - g, y - t / 2), (w - t / 2 - g, y),
                (w - t - g, y + t / 2), (t + g, y + t / 2)]

    def vbar(x, y0, y1):
        return [(x, y0 + g), (x + t / 2, y0 + t / 2 + g), (x + t / 2, y1 - t / 2 - g), (x, y1 - g),
                (x - t / 2, y1 - t / 2 - g), (x - t / 2, y0 + t / 2 + g)]
    return {"a": hbar(t / 2), "g": hbar(m), "d": hbar(h - t / 2),
            "f": vbar(t / 2, t / 2, m), "b": vbar(w - t / 2, t / 2, m),
            "e": vbar(t / 2, m, h - t / 2), "c": vbar(w - t / 2, m, h - t / 2)}


def seg_glyph(ch, w, h, col):
    """Lit digit on faint unlit segments with a neon glow baked in."""
    key = (ch, w, h, col)
    if key not in _seg_cache:
        pad = 24
        polys = seg_polys(w, h, max(10, int(w * 0.2)))
        lit = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
        base = lit.copy()
        ld, bd = ImageDraw.Draw(lit), ImageDraw.Draw(base)
        for name, poly in polys.items():
            pts = [(x + pad, y + pad) for x, y in poly]
            bd.polygon(pts, fill=(col[0] // 7, col[1] // 7, col[2] // 7, 255))
            if name in SEGMENTS[ch]:
                ld.polygon(pts, fill=col + (255,))
        glow = lit.filter(ImageFilter.GaussianBlur(11))
        base.alpha_composite(glow)
        base.alpha_composite(glow)
        base.alpha_composite(lit)
        _seg_cache[key] = base
    return _seg_cache[key]


def timer_digits(value, days):
    v = int(max(0.0, value))
    if days:
        return f"{v // 86400:03d}:{v % 86400 // 3600:02d}:{v % 3600 // 60:02d}", ("DAYS", "HRS", "MIN")
    return f"{v // 3600:02d}:{v % 3600 // 60:02d}:{v % 60:02d}", ("HRS", "MIN", "SEC")


def draw_timer(img, value, status, label, cy, lt, days=False, slam=1.0):
    """Bomb-timer panel. value None scrambles the digits, which is the open loop before each reveal."""
    col = {"stopped": GREEN, "scramble": (255, 150, 40)}.get(status, RED)
    if status == "scramble":
        rnd = random.Random(int(lt * 20))
        text, units = timer_digits(0, days)
        text = "".join(rnd.choice("0123456789") if c != ":" else c for c in text)
    else:
        text, units = timer_digits(value, days)
    panel_w, panel_h = 980, 200
    panel = Image.new("RGBA", (panel_w, panel_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(panel)
    rrect(d, [3, 3, panel_w - 3, panel_h - 3], 26, fill=(14, 6, 8, 245), outline=col, width=6)
    n_digits = sum(c != ":" for c in text)
    dw = 116 if n_digits == 6 else 100
    dh, gap, colon = 150, 14, 44
    x = (panel_w - (n_digits * (dw + gap) + 2 * colon)) / 2
    blink = status != "run" or int(lt * 4) % 2 == 0
    for c in text:
        if c == ":":
            if blink:
                for yy in (panel_h * 0.37, panel_h * 0.63):
                    d.ellipse([x + colon / 2 - 8, yy - 8, x + colon / 2 + 8, yy + 8], fill=col)
            x += colon
            continue
        panel.alpha_composite(seg_glyph(c, dw, dh, col), (int(x + gap / 2 - 24), int((panel_h - dh) / 2 - 24)))
        x += dw + gap
    jitter = 4 * math.sin(lt * 70) if status == "run" else 0
    paste_center(img, panel, W / 2 + jitter, cy, scale=1.5 - 0.5 * ease_out(slam))
    text_center(ImageDraw.Draw(img), W / 2, cy + 106, f"{label}  ·  {' : '.join(units)}", font(BOLD, 30),
                (235, 225, 225), stroke=3)


# ---------- top half ----------

ASSETS = {}
ANIMALS = []


def make_top_bg(strength):
    """Black to blood-red with a dark vignette; later animals get a hotter room."""
    h = SPLIT
    yy, xx = np.mgrid[0:h, 0:W].astype(np.float32)
    dist = np.sqrt(((xx - W / 2) / (W * 0.72)) ** 2 + ((yy - h * 0.48) / (h * 0.6)) ** 2)
    glow = np.clip(1 - dist, 0, 1) ** 1.4
    rgb = np.dstack([14 + glow * 130 * strength, 8 + glow * 12, 12 + glow * 20 * strength])
    alpha = np.full((h, W), 255, np.float32)
    return Image.fromarray(np.dstack([rgb, alpha]).astype(np.uint8), "RGBA")


def make_bitten_arm():
    im = Image.new("RGBA", (980, 400), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    rrect(d, [-200, 80, 1180, 330], 120, fill=(222, 170, 132, 255))
    d.ellipse([360, 130, 620, 290], fill=(190, 70, 70, 170))
    im = im.filter(ImageFilter.GaussianBlur(5))
    d = ImageDraw.Draw(im)
    for x in (430, 550):
        d.ellipse([x - 18, 188, x + 18, 224], fill=(70, 8, 10, 255))
        d.polygon([(x - 11, 212), (x + 11, 212), (x + 5, 300), (x, 326), (x - 5, 300)], fill=(190, 16, 20, 255))
    return im


def load_assets(scenes):
    global ANIMALS
    ANIMALS = [s for s in scenes if "chip" in s and s["id"] != "shots"]
    ASSETS["bg"] = {i: make_top_bg(0.35 + 0.13 * i) for i in range(6)}
    ASSETS["cold"] = make_top_bg(0.12)
    ASSETS["green"] = Image.new("RGBA", (W, SPLIT), (40, 255, 120, 26))
    ASSETS["tile"] = make_road_tile()
    ASSETS["ambulance"] = {on: make_ambulance(on) for on in (False, True)}
    ASSETS["cars"] = [make_car(c) for c in ((60, 120, 210), (210, 70, 60), (235, 190, 60), (110, 110, 120), (70, 170, 110))]
    ASSETS["arm"] = make_bitten_arm()
    glow = Image.new("RGBA", (620, 620), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([70, 70, 550, 550], fill=(255, 40, 30, 150))
    ASSETS["halo"] = glow.filter(ImageFilter.GaussianBlur(60))
    header = Image.new("RGBA", (W, 190), (0, 0, 0, 0))
    hd = ImageDraw.Draw(header)
    text_center(hd, W / 2, 20, "HOW LONG YOU'D SURVIVE", font(IMPACT, 72), WHITE, stroke=5)
    text_center(hd, W / 2, 104, "AFTER A BITE FROM...", font(IMPACT, 60), YELLOW, stroke=5)
    ASSETS["header"] = header


def chips(img, t, scene):
    """Running leaderboard: every clock so far, with the last one kept hidden until the twist pays off."""
    d = ImageDraw.Draw(img)
    cw, gap = 164, 8
    x0 = (W - (len(ANIMALS) * (cw + gap) - gap)) / 2
    for i, s in enumerate(ANIMALS):
        x = x0 + i * (cw + gap)
        started = t >= s["start"]
        revealed = t >= s["start"] + s["cue_t"][s["reveal"]]
        current = scene["id"] == s["id"] or (s["id"] == "dog" and scene["id"] == "shots")
        fill = (120, 20, 20, 235) if current else (24, 14, 18, 215)
        rrect(d, [x, 196, x + cw, 278], 18, fill=fill, outline=YELLOW if current else (90, 70, 74), width=4 if current else 2)
        if started:
            paste_center(img, animal_img(s, 120), x + 44, 237, scale=0.46)
        else:
            d.text((x + 44, 237), "?", font=font(IMPACT, 50), fill=(150, 130, 134), anchor="mm")
        d.text((x + 112, 237), s["chip"] if revealed else "?", font=font(IMPACT, 40 if revealed else 46),
               fill=YELLOW if revealed else (170, 150, 154), anchor="mm")


def animal_scene(img, s, lt, t):
    d = ImageDraw.Draw(img)
    name_f = fit_font(d, s["name"], IMPACT, 96, W - 70)
    p_name = ease_back(prog(lt, 0.0, 0.22))
    layer = Image.new("RGBA", (W, 130), (0, 0, 0, 0))
    text_center(ImageDraw.Draw(layer), W / 2, 65, s["name"], name_f, WHITE, stroke=7, anchor="mm")
    paste_center(img, layer, W / 2, 346, scale=0.6 + 0.4 * p_name, alpha=clamp(p_name * 2))
    # the animal lunges in at the camera, then breathes
    lunge = 1.75 - 0.75 * ease_out(prog(lt, 0.0, 0.3))
    breathe = 1 + 0.025 * math.sin(lt * 5)
    paste_center(img, ASSETS["halo"], W / 2, 540, scale=0.72 + 0.05 * math.sin(lt * 7), alpha=0.85)
    paste_center(img, animal_img(s, 280), W / 2, 545, scale=0.86 * lunge * breathe, angle=math.sin(lt * 2.2) * 3)
    if not (s["id"] == "dog" and lt >= s["cue_t"]["symptoms"]):
        sticker(img, s["stat"], W / 2, 688, prog(lt, s["cue_t"][s["stat_cue"]], 0.3), size=46, bg=YELLOW, angle=-2)
    value, status = timer_state(s, lt)
    reveal_at = s["cue_t"].get(s.get("reveal"), 0.0)
    slam = prog(lt, reveal_at, 0.18) if status != "scramble" else 1.0
    draw_timer(img, value, status, s["label"], 842, lt, days=s.get("days", False), slam=slam)
    if status == "stopped":
        img.alpha_composite(ASSETS["green"])
    if status == "out":
        stamp(img, "TIME'S UP", RED, W / 2, 545, prog(lt, s["dur"] - 0.6, 0.14), size=130)
    sid = s["id"]
    if sid == "taipan":
        sticker(img, "LUCKILY, IT'S SHY", W / 2, 440, prog(lt, s["cue_t"]["luck"], 0.25), size=44, bg=GREEN, angle=3)
    elif sid == "octopus":
        sticker(img, "BITE BARELY HURTS", W / 2, 440, prog(lt, s["cue_t"]["hurt"], 0.25), size=44, bg=WHITE, angle=3)
        if status == "stopped":
            stamp(img, "VENTILATOR", GREEN, W / 2, 545, prog(lt, s["cue_t"]["ventilator"], 0.14))
    elif sid == "funnel" and status == "stopped":
        if lt < s["cue_t"]["zero"]:
            stamp(img, "ANTIVENOM: 1981", GREEN, W / 2, 545, prog(lt, s["cue_t"]["antivenom"], 0.14), size=96)
        else:
            stamp(img, "0 DEATHS SINCE", GREEN, W / 2, 545, prog(lt, s["cue_t"]["zero"], 0.14), size=100, angle=6)
    elif sid == "dog":
        sticker(img, "⚠ SYMPTOMS START", W / 2, 688, prog(lt, s["cue_t"]["symptoms"], 0.25), size=46, bg=RED, fg=WHITE, angle=-2)
        stamp(img, "ALMOST ALWAYS FATAL", RED, W / 2, 545, prog(lt, s["cue_t"]["almost"], 0.14), size=84)
    elif sid == "shots" and status == "stopped":
        stamp(img, "CLOCK STOPPED", GREEN, W / 2, 545, prog(lt, s["cue_t"]["shots"], 0.14), size=100)


def scene_hook(img, s, lt, t):
    # the first frame already shows the wound and a live clock, there's no build-up to scroll past
    paste_center(img, ASSETS["arm"], W / 2, 500, scale=0.97 + 0.015 * math.sin(lt * 7))
    if lt < s["cue_t"]["ambulance"]:
        sticker(img, "YOU JUST GOT BITTEN", W / 2, 340, min(1.0, 0.5 + lt * 3), size=70, bg=RED, fg=WHITE, angle=-2)
    else:
        sticker(img, "🚑 MILES AWAY", W / 2, 340, prog(lt, s["cue_t"]["ambulance"], 0.2), size=70, bg=YELLOW, angle=2)
    at15, turn = s["cue_t"]["15"], s["cue_t"]["scariest"] - 0.5
    if lt < at15:
        draw_timer(img, None, "scramble", "TIME LEFT", 780, lt)
    elif lt < turn:
        draw_timer(img, 15 * 60 - (lt - at15) * 40, "run", "THE FASTEST", 780, lt, slam=prog(lt, at15, 0.18))
    else:
        draw_timer(img, None, "scramble", "THE SCARIEST", 780, lt)
        stamp(img, "NOT THE SCARIEST", RED, W / 2, 500, prog(lt, turn, 0.14), size=96)


def scene_twist(img, s, lt, t):
    d = ImageDraw.Draw(img)
    text_center(d, W / 2, 470, "WORSE THAN", font(IMPACT, 120), WHITE, stroke=7, anchor="mm")
    text_center(d, W / 2, 620, "15 MINUTES?", font(IMPACT, 130), RED, stroke=7, anchor="mm")
    at = s["cue_t"]["this"]
    if lt >= at:
        img.alpha_composite(Image.new("RGBA", (W, SPLIT), (0, 0, 0, 255)))
        paste_center(img, ASSETS["halo"], W / 2, 560, scale=0.9, alpha=0.9)
        paste_center(img, emoji_img("🐕", 280, tint=(16, 16, 20)), W / 2, 560, scale=1.0 + 0.4 * ease_out(prog(lt, at, 0.2)))
        text_center(ImageDraw.Draw(img), W / 2, 860, "? ? ?", font(IMPACT, 120), YELLOW, stroke=6, anchor="mm")


def scene_outro(img, s, lt, t):
    # all the clocks frozen green: every timer has the same fix
    for i, a in enumerate(ANIMALS):
        p = prog(lt, 0.05 + i * 0.1, 0.22)
        x, y = 195 + (i % 3) * 345, 400 + (i // 3) * 195
        layer = Image.new("RGBA", (320, 180), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        rrect(ld, [3, 3, 317, 177], 22, fill=(10, 34, 20, 245), outline=GREEN, width=5)
        paste_center(layer, animal_img(a, 120), 88, 90, scale=0.86)
        ld.text((222, 90), a["chip"], font=font(IMPACT, 66), fill=GREEN, anchor="mm")
        paste_center(img, layer, x, y, scale=max(0.02, ease_back(p)), alpha=clamp(p * 3))
    stamp(img, "GET TREATED NOW", GREEN, W / 2, 725, prog(lt, s["cue_t"]["right"], 0.14), size=84, angle=-2)
    sticker(img, "WHICH CLOCK SCARES YOU MOST? 👇", W / 2, 835, prog(lt, s["cue_t"]["which"], 0.25), size=44, bg=YELLOW)
    d = ImageDraw.Draw(img)
    text_center(d, W / 2, 884, "Times are rough estimates for untreated bites.", font(BOLD, 28), (235, 235, 235), stroke=3)
    text_center(d, W / 2, 924, "Bitten? Call emergency services.", font(BOLD, 28), (235, 235, 235), stroke=3)


SCENE_DRAW = {"hook": scene_hook, "twist": scene_twist, "outro": scene_outro}


def top_half(scene, lt, t, idx):
    ani = [i for i, a in enumerate(ANIMALS) if a["id"] == scene["id"]]
    if scene["id"] in ("hook", "twist"):
        img = ASSETS["cold"].copy()
    elif scene["id"] in ("outro", "shots"):
        img = ASSETS["bg"][1].copy()
    else:
        img = ASSETS["bg"][ani[0]].copy()
    # blood-red heartbeat over the room, quicker with every animal
    beat = max(0.0, math.sin(t * 2 * math.pi * (1.1 + idx * 0.12))) ** 8
    if beat > 0.02:
        img.alpha_composite(Image.new("RGBA", (W, SPLIT), (255, 0, 0, int(34 * beat))))
    SCENE_DRAW.get(scene["id"], animal_scene)(img, scene, lt, t)
    img.alpha_composite(ASSETS["header"])
    chips(img, t, scene)
    return img


# ---------- gameplay (bottom half) ----------

GH = H - SPLIT
ROAD = (150, 930)
LANES = [280, 540, 800]
SPEED = 1000  # world px per second
AMB_Y = GH - 210
SWITCH = 300  # travel distance for a lane change
TILE_H = GH * 3
BRAKE = 1.6  # seconds spent braking into the hospital
KM_START = 18.4


def make_road_tile():
    """Seamless vertical tile: a three-lane city road between dark blocks."""
    im = Image.new("RGBA", (W, TILE_H), (44, 46, 54, 255))
    d = ImageDraw.Draw(im)
    rnd = random.Random(14)
    for x0, x1 in ((0, ROAD[0] - 14), (ROAD[1] + 14, W)):
        d.rectangle([x0, 0, x1, TILE_H], fill=(30, 30, 38))
    for k in range(12):
        y = k * TILE_H / 12
        for x0, x1 in ((6, ROAD[0] - 30), (ROAD[1] + 30, W - 6)):
            shade = rnd.randrange(38, 66)
            d.rectangle([x0, y + 10, x1, y + TILE_H / 12 - 12], fill=(shade, shade, shade + 10), outline=(20, 20, 26), width=3)
            for _ in range(5):
                wx, wy = rnd.uniform(x0 + 10, x1 - 22), y + rnd.uniform(24, TILE_H / 12 - 44)
                d.rectangle([wx, wy, wx + 12, wy + 16], fill=(238, 208, 120) if rnd.random() < 0.6 else (24, 24, 32))
    d.rectangle([ROAD[0] - 14, 0, ROAD[0], TILE_H], fill=(150, 150, 156))
    d.rectangle([ROAD[1], 0, ROAD[1] + 14, TILE_H], fill=(150, 150, 156))
    for x in ((LANES[0] + LANES[1]) // 2, (LANES[1] + LANES[2]) // 2):
        for y in range(0, TILE_H, TILE_H // 16):
            d.rectangle([x - 5, y, x + 5, y + 76], fill=(226, 226, 226))
    return im


def make_ambulance(light_on):
    """Top-down ambulance with a flashing light bar."""
    im = Image.new("RGBA", (260, 360), (0, 0, 0, 0))
    glow = Image.new("RGBA", im.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    if light_on:
        gd.ellipse([0, 10, 150, 160], fill=(255, 30, 30, 200))
    else:
        gd.ellipse([110, 10, 260, 160], fill=(40, 90, 255, 200))
    im.alpha_composite(glow.filter(ImageFilter.GaussianBlur(24)))
    d = ImageDraw.Draw(im)
    for x, y in ((46, 70), (192, 70), (46, 256), (192, 256)):
        rrect(d, [x, y, x + 24, y + 54], 7, fill=INK)
    rrect(d, [60, 20, 200, 340], 26, fill=(248, 248, 244), outline=INK, width=5)
    rrect(d, [76, 44, 184, 88], 10, fill=(80, 120, 150), outline=INK, width=3)
    d.rectangle([60, 180, 200, 208], fill=(230, 40, 40))
    d.rectangle([118, 218, 142, 298], fill=(230, 40, 40))
    d.rectangle([90, 246, 170, 270], fill=(230, 40, 40))
    rrect(d, [84, 104, 130, 128], 6, fill=(255, 60, 60) if light_on else (110, 30, 30), outline=INK, width=2)
    rrect(d, [130, 104, 176, 128], 6, fill=(60, 110, 255) if not light_on else (20, 40, 110), outline=INK, width=2)
    return im


def red_cross(d, cx, cy, size):
    arm = size // 6
    rrect(d, [cx - size / 2, cy - size / 2, cx + size / 2, cy + size / 2], size // 6, fill=WHITE, outline=INK, width=max(2, size // 24))
    d.rectangle([cx - arm, cy - size * 0.36, cx + arm, cy + size * 0.36], fill=(226, 30, 36))
    d.rectangle([cx - size * 0.36, cy - arm, cx + size * 0.36, cy + arm], fill=(226, 30, 36))


def make_car(col):
    im = Image.new("RGBA", (150, 240), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for x, y in ((6, 40), (126, 40), (6, 170), (126, 170)):
        rrect(d, [x, y, x + 18, y + 44], 5, fill=INK)
    rrect(d, [18, 8, 132, 232], 24, fill=col, outline=INK, width=4)
    rrect(d, [34, 50, 116, 90], 8, fill=(40, 50, 66), outline=INK, width=2)
    rrect(d, [34, 150, 116, 190], 8, fill=(40, 50, 66), outline=INK, width=2)
    return im


def dist_at(t, arrive):
    if t <= arrive:
        return SPEED * t
    return SPEED * arrive + SPEED * BRAKE / 3 * ease_out((t - arrive) / BRAKE)


def make_course(total):
    rnd = random.Random(23)
    arrive = total - BRAKE - 1.2
    stop = dist_at(arrive, arrive)
    obstacles, switches = [], []
    lane, p = 1, 1300.0
    while p < stop - 1100:
        L = rnd.randrange(3)
        if L == lane:
            new = rnd.choice([l for l in (lane - 1, lane + 1) if 0 <= l < 3])
            switches.append((p - 520, lane, new))
            lane = new
        obstacles.append((p, L, rnd.randrange(5)))
        p += rnd.uniform(760, 960)
    if lane != 1:
        switches.append((stop - 600, lane, 1))
    return obstacles, switches, arrive


def amb_x(switches, d):
    x = LANES[1]
    for s, a, b in switches:
        if d < s:
            break
        u = (d - s) / SWITCH
        x = LANES[b] if u >= 1 else LANES[a] + (LANES[b] - LANES[a]) * smooth(u)
    return x


def bottom_half(course, t):
    obstacles, switches, arrive = course
    dist = dist_at(t, arrive)
    final = dist_at(arrive + BRAKE, arrive)
    img = Image.new("RGBA", (W, GH))
    off = int(dist % TILE_H)
    img.paste(ASSETS["tile"].crop((0, TILE_H - off, W, TILE_H)), (0, 0))
    if off < GH:
        img.paste(ASSETS["tile"].crop((0, 0, W, GH - off)), (0, off))
    d = ImageDraw.Draw(img)

    def sy(p):
        return AMB_Y - (p - dist)

    # the hospital waits across the road at the end of the run
    hy = sy(final + 340)
    if -300 < hy < GH:
        d.rectangle([60, hy - 150, W - 60, hy + 130], fill=(238, 238, 234), outline=INK, width=6)
        d.rectangle([60, hy + 90, W - 60, hy + 130], fill=(230, 40, 40))
        red_cross(d, 200, hy - 30, 150)
        text_center(d, 610, hy - 30, "HOSPITAL", font(IMPACT, 130), (200, 24, 24), anchor="mm")

    bx = amb_x(switches, dist)
    lean = (amb_x(switches, dist + 50) - bx) / 50
    for p, lane, c in obstacles:
        y = sy(p)
        if -160 < y < GH + 160:
            paste_center(img, ASSETS["cars"][c], LANES[lane], y)
        since = (dist - p) / SPEED
        if 0.0 < since < 0.45 and int(p) % 3 == 0:
            d.text((LANES[lane], AMB_Y - 160 - since * 200), "CLOSE!", font=font(IMPACT, 54), fill=YELLOW,
                   anchor="mm", stroke_width=4, stroke_fill=INK)

    paste_center(img, ASSETS["ambulance"][int(t * 7) % 2 == 0], bx, AMB_Y, angle=-lean * 9)

    # the distance pill gives way to the hospital itself once it rolls into view
    if hy < -160:
        hud = ImageDraw.Draw(img)
        left = KM_START * clamp(1 - t / (arrive + BRAKE))
        rrect(hud, [W / 2 - 240, 110, W / 2 + 240, 182], 36, fill=(0, 0, 0, 195))
        red_cross(hud, W / 2 - 196, 146, 48)
        hud.text((W / 2 + 26, 146), f"HOSPITAL {left:04.1f} KM", font=font(IMPACT, 50), fill=YELLOW, anchor="mm")
    sticker(img, "ARRIVED", 830, AMB_Y + 40, prog(t, arrive + BRAKE * 0.6, 0.25), size=56, bg=GREEN, angle=-4)
    return img


# ---------- captions, overlays, frame ----------

def captions(img, scene, lt):
    chunks = chunk_words(scene["words"])
    cur = None
    for i, ch in enumerate(chunks):
        start = ch[0]["start"] - 0.04
        end = chunks[i + 1][0]["start"] - 0.04 if i + 1 < len(chunks) else ch[-1]["end"] + 0.35
        if start <= lt < end:
            cur = (i, ch, start)
            break
    if not cur:
        return
    idx, ch, start = cur
    items = [w["text"].upper() for w in ch]
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
        key = any(p in KEYWORDS for p in re.sub(r"[^A-Z0-9 ]", "", txt).split())
        fill = (YELLOW if active else WHITE) if not key else (RED if active else (255, 140, 140))
        d.text((x, layer.height / 2), txt, font=f, fill=fill, anchor="lm", stroke_width=11, stroke_fill=INK)
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
    paste_center(img, b, W / 2, SPLIT + 420, scale=a * pulse, alpha=clamp(a * 2))


def render_frame(scenes, booms, course, total, t):
    idx = next(i for i, s in reversed(list(enumerate(scenes))) if t >= s["start"])
    scene = scenes[idx]
    lt = t - scene["start"]
    img = Image.new("RGBA", (W, H))
    img.paste(bottom_half(course, t), (0, SPLIT))
    img.paste(top_half(scene, lt, t, idx), (0, 0))
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
    out = OUT / "bite_countdown.mp4"
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
