"""Render the 'Why does Bolivia have a navy?' reel (1080x1920, 30fps).

Brainrot layout: the story plays on top (a stylised map of Bolivia, the constitution,
the world court, a calendar...), a top-down river-boat "gameplay" clip runs on the
bottom (a patrol boat dodging rocks and crocs), big punchy captions sit on the seam.
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
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from script import SCENES

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output" / "bolivia_navy"
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
BOL_RED, BOL_YEL, BOL_GRN = (213, 43, 30), (249, 228, 0), (0, 122, 51)
CHI_RED, CHI_BLU = (213, 43, 30), (0, 57, 166)
PAR_RED, PAR_BLU = (213, 43, 30), (0, 56, 168)
KEYWORDS = {"NAVY", "OCEAN", "LOST", "AGAIN", "CONSTITUTION", "CLOUDS", "READY", "PARAGUAY",
            "1879", "2018", "SEA", "COAST", "COASTLINE", "LANDLOCKED"}

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

    # Phonk loop at 136 bpm: kick + 808, snare on 2 and 4, cowbell riff in 16ths.
    music = np.zeros(n, np.float32)
    beat = 60 / 136
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

    scale = [554.4, 622.3, 659.3, 740.0, 830.6, 987.8]
    riff = [5, None, 3, 4, None, 4, 3, None, 2, None, 0, 2, 1, None, 0, None,
            5, None, 3, 4, None, 4, 5, 3, 4, None, 2, None, 1, 2, 0, None]
    bells = {f: cowbell(scale[f]) for f in set(r for r in riff if r is not None)}
    bass_notes = [46.2, 46.2, 41.2, 55.0]
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
    # error "bonk" for the 404 popup, a counter tick-up for the sailors
    seaday = next(s for s in scenes if s["id"] == "seaday")
    el = int(0.3 * SR)
    bonk = np.sign(np.sin(2 * np.pi * 220 * np.arange(el) / SR)) * tone_env(el, 12)
    add(fx, seaday["start"] + seaday["cue_t"]["doesnt"] + 0.02, bonk, 0.08)
    navy = next(s for s in scenes if s["id"] == "navy")
    tl = int(0.03 * SR)
    tick = np.sin(2 * np.pi * 1800 * np.arange(tl) / SR) * tone_env(tl, 90)
    for k in range(14):
        add(fx, navy["start"] + navy["cue_t"]["five"] + k * 0.06, tick, 0.12)

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


def flag(kind, w=300, h=200):
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if kind == "bolivia":
        for i, c in enumerate((BOL_RED, BOL_YEL, BOL_GRN)):
            d.rectangle([0, i * h / 3, w, (i + 1) * h / 3], fill=c)
    elif kind == "paraguay":
        for i, c in enumerate((PAR_RED, WHITE, PAR_BLU)):
            d.rectangle([0, i * h / 3, w, (i + 1) * h / 3], fill=c)
        r = h * 0.14
        d.ellipse([w / 2 - r, h / 2 - r, w / 2 + r, h / 2 + r], outline=(30, 120, 60), width=4)
        d.ellipse([w / 2 - r * 0.4, h / 2 - r * 0.4, w / 2 + r * 0.4, h / 2 + r * 0.4], fill=(250, 200, 0))
    elif kind == "chile":
        d.rectangle([0, 0, w, h / 2], fill=WHITE)
        d.rectangle([0, h / 2, w, h], fill=CHI_RED)
        d.rectangle([0, 0, h / 2, h / 2], fill=CHI_BLU)
        cx, cy, r = h / 4, h / 4, h * 0.13
        pts = [(cx + (r if k % 2 == 0 else r * 0.4) * math.sin(k * math.pi / 5),
                cy - (r if k % 2 == 0 else r * 0.4) * math.cos(k * math.pi / 5)) for k in range(10)]
        d.polygon(pts, fill=WHITE)
    d.rectangle([0, 0, w - 1, h - 1], outline=INK, width=4)
    return im


def wavy(im, t, amp=8):
    """Flag ripple: shift vertical strips by a travelling sine."""
    out = Image.new("RGBA", (im.width, im.height + amp * 2), (0, 0, 0, 0))
    for x in range(0, im.width, 10):
        dy = amp + amp * math.sin(x * 0.03 - t * 6) * (x / im.width)
        out.paste(im.crop((x, 0, x + 10, im.height)), (x, int(dy)))
    return out


def dim(img, a, col=(8, 10, 22)):
    if a > 0:
        img.alpha_composite(Image.new("RGBA", img.size, col + (int(255 * clamp(a)),)))


# ---------- map ----------

LON0, LAT0, SC = -76.0, -8.0, 48
MAP_BOX = (60, 190, 1020, 1006)


def proj(lon, lat):
    return MAP_BOX[0] + (lon - LON0) * SC, MAP_BOX[1] + (LAT0 - lat) * SC


def pts(poly):
    return [proj(*p) for p in poly]


BOLIVIA = [(-69.6, -10.95), (-68.6, -11.1), (-67.6, -10.6), (-66.6, -9.9), (-65.35, -9.75), (-65.3, -10.9),
           (-65.0, -11.7), (-64.0, -12.4), (-63.0, -12.8), (-62.1, -13.3), (-61.0, -13.5), (-60.4, -13.9),
           (-60.3, -15.1), (-60.1, -16.3), (-58.4, -16.3), (-58.3, -17.3), (-57.6, -17.9), (-57.5, -18.2),
           (-58.2, -19.8), (-59.1, -19.3), (-61.7, -19.6), (-62.3, -20.5), (-62.3, -21.9), (-62.8, -22.1),
           (-63.9, -22.0), (-64.4, -22.8), (-65.0, -22.1), (-66.3, -21.8), (-67.1, -22.7), (-67.8, -22.8),
           (-68.2, -21.5), (-68.7, -20.4), (-68.4, -19.4), (-69.0, -19.0), (-69.4, -18.0), (-69.5, -17.5),
           (-69.0, -16.7), (-68.8, -16.3), (-69.2, -16.0), (-69.4, -15.6), (-69.2, -15.2), (-68.9, -14.2),
           (-68.9, -12.9), (-68.7, -12.5)]
# Bolivia's lost Litoral department (to Chile, War of the Pacific 1879-84)
LITORAL = [(-70.1, -21.4), (-68.2, -21.5), (-67.8, -22.8), (-67.2, -23.3), (-67.4, -24.0), (-70.45, -24.0),
           (-70.4, -23.6), (-70.2, -22.5)]
CHILE = [(-70.3, -18.4), (-69.5, -17.5), (-69.4, -18.0), (-69.0, -19.0), (-68.4, -19.4), (-68.7, -20.4),
         (-68.2, -21.5), (-67.8, -22.8), (-67.2, -23.3), (-68.3, -25.0), (-68.5, -27), (-70.9, -27),
         (-70.6, -26), (-70.5, -25.5), (-70.4, -23.6), (-70.2, -22.5), (-70.1, -21.4), (-70.15, -20.2)]
PERU = [(-70.3, -18.4), (-71.4, -17.5), (-72.5, -16.5), (-74.8, -15.5), (-76.2, -14), (-77.2, -12), (-79, -8),
        (-72, -6), (-70.5, -9.5), (-70.6, -11.0), (-69.6, -10.95), (-68.7, -12.5), (-68.9, -12.9),
        (-68.9, -14.2), (-69.2, -15.2), (-69.4, -15.6), (-69.2, -16.0), (-68.8, -16.3), (-69.0, -16.7),
        (-69.5, -17.5)]
COAST = [(-80, -5), (-79, -8), (-77.2, -12), (-76.2, -14), (-74.8, -15.5), (-72.5, -16.5), (-71.4, -17.5),
         (-70.3, -18.4), (-70.15, -20.2), (-70.1, -21.4), (-70.2, -22.5), (-70.4, -23.6), (-70.5, -25.5),
         (-70.6, -26), (-70.9, -27), (-71.5, -30)]
RIVERS = [  # Beni, Mamoré, Guaporé: the Amazon-basin rivers the navy patrols
    [(-67.6, -14.6), (-67.2, -13.4), (-66.6, -12.0), (-66.1, -10.8), (-65.4, -10.2)],
    [(-64.8, -16.9), (-65.0, -15.2), (-64.8, -13.8), (-65.2, -12.3), (-65.3, -11.0), (-65.4, -10.2)],
    [(-60.3, -13.9), (-62.4, -12.9), (-64.3, -12.0), (-65.2, -11.4)],
]
TITICACA = (-69.3, -15.85)
MAMORE_PATH = RIVERS[1]

MAP_LAND = (54, 58, 78)
MAP_PERU = (66, 70, 92)
MAP_CHILE = (150, 52, 66)
MAP_OCEAN = (30, 96, 176)
MAP_BOL = (255, 206, 40)


def make_map(litoral):
    """Map card with the Litoral coloured as Bolivia ('past') or Chile ('now')."""
    img = Image.new("RGBA", (W, SPLIT), MAP_LAND + (255,))
    d = ImageDraw.Draw(img)
    d.polygon(pts(COAST + [(-90, -30), (-90, -5)]), fill=MAP_OCEAN)
    rnd = random.Random(5)
    for _ in range(40):  # little wave marks
        lon, lat = rnd.uniform(-76, -72), rnd.uniform(-17, -25)
        x, y = proj(lon, lat)
        if lon < -71.2 + (lat + 17) * 0.05:
            d.arc([x - 14, y - 6, x + 14, y + 6], 200, 340, fill=(90, 150, 220), width=3)
    d.polygon(pts(PERU), fill=MAP_PERU, outline=(90, 94, 118), width=2)
    d.polygon(pts(CHILE), fill=MAP_CHILE, outline=(180, 80, 90), width=2)
    d.polygon(pts(LITORAL), fill=MAP_BOL if litoral == "past" else MAP_CHILE,
              outline=(255, 255, 255) if litoral == "past" else (180, 80, 90), width=3)
    d.polygon(pts(BOLIVIA), fill=MAP_BOL, outline=INK, width=4)
    lx, ly = proj(*TITICACA)
    lake = Image.new("RGBA", (84, 40), (0, 0, 0, 0))
    ImageDraw.Draw(lake).ellipse([3, 3, 81, 37], fill=MAP_OCEAN, outline=(150, 210, 255), width=3)
    paste_center(img, lake, lx, ly, angle=38)
    lab = font(BOLD, 34)
    for text, lon, lat in (("PERU", -73.6, -11.6), ("BRAZIL", -61.5, -9.3), ("ARGENTINA", -63.8, -24.0),
                           ("PARAGUAY", -59.6, -21.9), ("CHILE", -69.2, -25.2)):
        text_center(d, *proj(lon, lat), text, lab, (200, 205, 225), stroke=3, anchor="mm")
    for i, word in enumerate(("PACIFIC", "OCEAN")):
        x, y = proj(-73.4, -20.4 - i * 0.9)
        text_center(d, x, y, word, font(BOLD, 40), (170, 210, 255), stroke=3, anchor="mm")
    text_center(d, *proj(-64.2, -16.9), "BOLIVIA", font(IMPACT, 76), INK, anchor="mm")
    mask = Image.new("L", (W, SPLIT), 0)
    ImageDraw.Draw(mask).rounded_rectangle(MAP_BOX, 34, fill=255)
    img.putalpha(mask)
    ImageDraw.Draw(img).rounded_rectangle(MAP_BOX, 34, outline=WHITE, width=5)
    return img


def make_glow(poly, col, width=12, blur=10):
    g = Image.new("RGBA", (W, SPLIT), (0, 0, 0, 0))
    ImageDraw.Draw(g).line(pts(poly + poly[:1]), fill=col + (255,), width=width, joint="curve")
    return g.filter(ImageFilter.GaussianBlur(blur))


def make_rivers():
    r = Image.new("RGBA", (W, SPLIT), (0, 0, 0, 0))
    d = ImageDraw.Draw(r)
    for river in RIVERS:
        d.line(pts(river), fill=(60, 170, 255), width=7, joint="curve")
    return r


def sepia(img):
    out = ImageOps.colorize(ImageOps.grayscale(img.convert("RGB")), (40, 24, 10), (245, 215, 160))
    out = out.convert("RGBA")
    out.putalpha(img.getchannel("A"))
    return out


ASSETS = {}


def load_assets():
    ASSETS["map_now"] = make_map("now")
    ASSETS["map_past"] = sepia(make_map("past"))
    ASSETS["bol_glow"] = make_glow(BOLIVIA, (255, 255, 255))
    ASSETS["lit_glow"] = make_glow(LITORAL, (255, 255, 255))
    ASSETS["rivers"] = make_rivers()
    ASSETS["river_glow"] = ASSETS["rivers"].filter(ImageFilter.GaussianBlur(9))
    ASSETS["flags"] = {k: flag(k) for k in ("bolivia", "chile", "paraguay")}
    ASSETS["top_bg"] = make_top_bg()


def make_top_bg():
    y = np.linspace(0, 1, SPLIT)[:, None, None]
    img = np.array([18, 26, 52]) + (np.array([8, 10, 24]) - np.array([18, 26, 52])) * y
    img = np.broadcast_to(img, (SPLIT, W, 3)).copy()
    return Image.fromarray(img.astype(np.uint8)).convert("RGBA")


def pulse_layer(layer, a):
    if a > 0.02:
        return with_alpha(layer.copy(), a)
    return None


def arrow(d, a, b, col=WHITE, width=6):
    d.line([a, b], fill=INK, width=width + 6)
    d.line([a, b], fill=col, width=width)
    ang = math.atan2(b[1] - a[1], b[0] - a[0])
    head = [b, (b[0] - 26 * math.cos(ang - 0.45), b[1] - 26 * math.sin(ang - 0.45)),
            (b[0] - 26 * math.cos(ang + 0.45), b[1] - 26 * math.sin(ang + 0.45))]
    d.polygon(head, fill=col, outline=INK)


# ---------- story scenes (top half) ----------

def scene_hook(img, s, lt):
    c = s["cue_t"]
    img.alpha_composite(ASSETS["map_now"])
    g = pulse_layer(ASSETS["bol_glow"], 0.55 + 0.45 * math.sin(lt * 7))
    if g:
        img.alpha_composite(g)
    bx, by = proj(-64.2, -14.4)
    p = prog(lt, c["navy"] - 0.1, 0.4)
    paste_center(img, emoji_img("🚢", 160), bx, by - 30 + math.sin(lt * 5) * 10, scale=ease_back(p),
                 angle=math.sin(lt * 3) * 6)
    sticker(img, "HAS A NAVY ✅", 540, 260, prog(lt, c["navy"] - 0.05, 0.35), size=70, bg=GREEN)
    sticker(img, "NO OCEAN ❌", 330, 770, prog(lt, c["ocean"] - 0.05, 0.3), size=78, bg=RED, fg=WHITE,
            angle=-8)
    p = prog(lt, c["sailing"] - 0.1, 0.35)
    paste_center(img, emoji_img("🤨", 220), 860, 820, scale=ease_back(p), angle=math.sin(lt * 4) * 8)


def scene_war(img, s, lt):
    c = s["cue_t"]
    flip = smooth(prog(lt, c["lost"], 0.25))
    base = ASSETS["map_past"] if flip < 1 else ASSETS["map_now"]
    if 0 < flip < 1:
        base = Image.blend(ASSETS["map_past"], ASSETS["map_now"], flip)
    img.alpha_composite(base)
    g = pulse_layer(ASSETS["lit_glow"], (0.6 + 0.4 * math.sin(lt * 8)) * (1 - 0.6 * flip))
    if g:
        img.alpha_composite(g)
    sticker(img, "📅 1879", 230, 270, prog(lt, 0.0, 0.35), size=72, bg=(245, 215, 160))
    lx, ly = proj(-69.0, -22.8)
    d = ImageDraw.Draw(img)
    if lt < c["lost"]:
        a = prog(lt, 0.5, 0.3)
        if a > 0:
            arrow(d, (250, 690), (lx - 30, ly - 20), col=(245, 215, 160))
        sticker(img, "BOLIVIA'S COAST 🏖", 250, 650, a, size=46, bg=(245, 215, 160))
    else:
        arrow(d, (250, 690), (lx - 30, ly - 20), col=RED)
        sticker(img, "-400 KM OF COAST 💀", 270, 650, prog(lt, c["lost"], 0.3), size=48, bg=RED, fg=WHITE)
    sticker(img, "BOLIVIA ⚔ CHILE", 660, 270, prog(lt, c["fought"] - 0.05, 0.35), size=66, bg=WHITE)
    sticker(img, "WAR OF THE PACIFIC", 660, 370, prog(lt, c["pacific"] - 0.4, 0.35), size=48, bg=RED,
            fg=WHITE, angle=3)
    if flip < 1:  # old-film flicker
        rnd = random.Random(int(lt * 15))
        for _ in range(4):
            x = rnd.uniform(MAP_BOX[0], MAP_BOX[2])
            d.line([x, MAP_BOX[1], x + rnd.uniform(-10, 10), MAP_BOX[3]], fill=(60, 40, 20, 90), width=2)


def scene_cope(img, s, lt):
    c = s["cue_t"]
    slide = ease_out(prog(lt, 0, 0.45))
    doc = Image.new("RGBA", (760, 700), (0, 0, 0, 0))
    d = ImageDraw.Draw(doc)
    rrect(d, [10, 10, 750, 690], 22, fill=(246, 234, 204), outline=(120, 90, 50), width=6)
    text_center(d, 380, 50, "CONSTITUTION", font(IMPACT, 84), (110, 60, 30))
    text_center(d, 380, 150, "PLURINATIONAL STATE OF BOLIVIA · 2009", font(SEMI, 30), (120, 90, 60))
    rnd = random.Random(3)
    for y in (220, 250, 280, 580, 610, 640):
        d.rounded_rectangle([60, y, 60 + rnd.randint(420, 640), y + 12], 6, fill=(205, 190, 160))
    text_center(d, 380, 320, "ARTICLE 267", font(IMPACT, 60), (170, 30, 30))
    hl = smooth(prog(lt, c["constitution"] - 0.1, 0.45))
    if hl > 0:
        d.rectangle([70, 455, 70 + 620 * hl, 515], fill=(255, 235, 60))
    body = font(SEMI, 40)
    for i, line in enumerate(("Bolivia declares its", "IRRENUNCIABLE right", "to access the Pacific Ocean.")):
        text_center(d, 380, 400 + i * 62, line, body if i != 1 else font(BOLD, 46), (40, 30, 20))
    paste_center(img, doc, 540, 620 + (1 - slide) * 600, angle=-2)
    sticker(img, "STILL NOT OVER IT 💔", 540, 255, prog(lt, c["never"] - 0.05, 0.35), size=66, bg=RED,
            fg=WHITE)
    sticker(img, "translation: we want it back 😤", 540, 960, prog(lt, c["constitution"] + 0.5, 0.35),
            size=46, bg=YELLOW, angle=-3)


def scene_court(img, s, lt):
    c = s["cue_t"]
    sticker(img, "⚖ WORLD COURT · 2018", 540, 260, prog(lt, c["world"] - 0.1, 0.35), size=66, bg=WHITE)
    for i, (kind, name, x) in enumerate((("bolivia", "BOLIVIA", 290), ("chile", "CHILE", 790))):
        p = ease_back(prog(lt, 0.1 + i * 0.15, 0.4))
        fl = wavy(ASSETS["flags"][kind], lt + i)
        paste_center(img, fl, x, 480, scale=max(0.0, p))
        if p > 0.3:
            text_center(ImageDraw.Draw(img), x, 600, name, font(IMPACT, 64), WHITE, stroke=5)
    text_center(ImageDraw.Draw(img), 540, 480, "VS", font(IMPACT, 110), YELLOW, stroke=6, anchor="mm")
    for i, (cue, year, x) in enumerate((("lost", "1879", 200), ("again", "2018", 380))):
        p = prog(lt, c[cue] - 0.05, 0.3)
        if p <= 0:
            continue
        st = Image.new("RGBA", (180, 240), (0, 0, 0, 0))
        sd = ImageDraw.Draw(st)
        text_center(sd, 90, 100, "L", font(IMPACT, 220), RED, stroke=8, stroke_fill=WHITE, anchor="mm")
        text_center(sd, 90, 225, year, font(IMPACT, 40), WHITE, stroke=4, anchor="mb")
        paste_center(img, st, x, 820, scale=2.2 - 1.2 * ease_back(p), alpha=clamp(p * 3), angle=-10 + i * 14)
    p = prog(lt, c["lost"] + 0.1, 0.35)
    paste_center(img, emoji_img("🗿", 150), 790, 820, scale=ease_back(p), angle=math.sin(lt * 3) * 6)
    sticker(img, "0 - 2 💀", 790, 960, prog(lt, c["again"] + 0.2, 0.35), size=60, bg=YELLOW)


def scene_seaday(img, s, lt):
    c = s["cue_t"]
    p = ease_back(prog(lt, 0, 0.4))
    cal = Image.new("RGBA", (480, 480), (0, 0, 0, 0))
    d = ImageDraw.Draw(cal)
    rrect(d, [6, 6, 474, 474], 40, fill=WHITE, outline=INK, width=6)
    d.rounded_rectangle([6, 6, 474, 130], 40, fill=RED, outline=INK, width=6)
    d.rectangle([12, 90, 468, 130], fill=RED)
    text_center(d, 240, 68, "MARCH", font(IMPACT, 80), WHITE, anchor="mm")
    text_center(d, 240, 300, "23", font(IMPACT, 280), INK, anchor="mm")
    paste_center(img, cal, 540, 470, scale=max(0.0, p), angle=-4 + math.sin(lt * 2) * 2)
    dp = prog(lt, c["day"] - 0.05, 0.35)
    sticker(img, "DÍA DEL MAR 🌊", 540, 790, dp, size=76, bg=BLUE, fg=WHITE)
    if dp > 0:  # confetti
        age = lt - c["day"]
        rnd = random.Random(8)
        d = ImageDraw.Draw(img)
        for _ in range(60):
            x0, vx, vy = rnd.uniform(100, 980), rnd.uniform(-160, 160), rnd.uniform(-700, -300)
            x, y = x0 + vx * age, 700 + vy * age + 900 * age * age
            if 180 < y < SPLIT:
                col = rnd.choice([BOL_RED, BOL_YEL, BOL_GRN, WHITE, BLUE])
                sz = rnd.uniform(8, 16)
                d.rectangle([x, y, x + sz, y + sz * 0.6], fill=col)
        paste_center(img, emoji_img("🎉", 140), 220, 330, scale=ease_back(dp), angle=20)
        paste_center(img, emoji_img("🎉", 140, mirror=True), 860, 330, scale=ease_back(dp), angle=-20)
    ep = prog(lt, c["doesnt"] - 0.05, 0.25)
    if ep > 0:
        dim(img, 0.35 * ep)
        box = Image.new("RGBA", (820, 330), (0, 0, 0, 0))
        bd = ImageDraw.Draw(box)
        bd.rectangle([0, 0, 819, 329], fill=(236, 236, 236), outline=INK, width=4)
        bd.rectangle([4, 4, 815, 64], fill=(0, 90, 200))
        bd.text((24, 34), "Error", font=font(SEMI, 36), fill=WHITE, anchor="lm")
        bd.rectangle([760, 12, 806, 56], fill=(220, 50, 50))
        bd.text((783, 34), "x", font=font(BOLD, 34), fill=WHITE, anchor="mm")
        paste_center(box, emoji_img("❌", 120), 100, 160, scale=0.75)
        bd.text((180, 132), "SEA NOT FOUND", font=font(IMPACT, 64), fill=INK, anchor="lm")
        bd.text((180, 192), "error 404: Bolivia.sea", font=font(SEMI, 34), fill=(90, 90, 90), anchor="lm")
        bd.rectangle([600, 250, 790, 310], fill=(225, 225, 225), outline=(0, 90, 200), width=3)
        bd.text((695, 280), "OK", font=font(SEMI, 34), fill=INK, anchor="mm")
        paste_center(img, box, 540, 800, scale=0.6 + 0.4 * ease_back(ep), alpha=clamp(ep * 3))


def path_point(path, u):
    pp = pts(path)
    seg = [math.dist(a, b) for a, b in zip(pp, pp[1:])]
    target = u * sum(seg)
    for (a, b), L in zip(zip(pp, pp[1:]), seg):
        if target <= L:
            k = target / L
            return a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, math.atan2(b[1] - a[1], b[0] - a[0])
        target -= L
    a, b = pp[-2], pp[-1]
    return b[0], b[1], math.atan2(b[1] - a[1], b[0] - a[0])


def scene_navy(img, s, lt):
    c = s["cue_t"]
    img.alpha_composite(ASSETS["map_now"])
    img.alpha_composite(ASSETS["rivers"])
    ap = prog(lt, c["amazon"] - 0.1, 0.3)
    if ap > 0:
        g = pulse_layer(ASSETS["river_glow"], ap * (0.7 + 0.3 * math.sin(lt * 8)))
        img.alpha_composite(g)
        img.alpha_composite(g)
    lx, ly = proj(*TITICACA)
    tp = prog(lt, c["titicaca"] - 0.1, 0.3)
    d = ImageDraw.Draw(img)
    if tp > 0:
        for k in range(2):
            r = 40 + ((lt * 60 + k * 35) % 70)
            a = int(255 * (1 - (r - 40) / 70) * tp)
            d.ellipse([lx - r, ly - r, lx + r, ly + r], outline=(255, 255, 255, a), width=5)
        arrow(d, (230, 470), (lx - 40, ly - 20))
    sticker(img, "LAKE TITICACA", 230, 430, tp, size=48, bg=WHITE)
    sticker(img, "AMAZON RIVERS 🌴", 830, 470, ap, size=46, bg=GREEN)
    if ap > 0:
        u = clamp((lt - c["amazon"]) / 2.2)
        x, y, ang = path_point(MAMORE_PATH, u)
        paste_center(img, emoji_img("🚤", 120), x, y, scale=0.7, angle=-math.degrees(ang) - 180)
    n = int(5000 * ease_out(prog(lt, c["five"] - 0.05, 0.85)))
    sticker_p = prog(lt, c["five"] - 0.1, 0.3)
    if sticker_p > 0:  # counter changes every frame, so draw it uncached
        f = font(IMPACT, 72)
        txt = f"🫡 {n:,} SAILORS"
        layer = Image.new("RGBA", (W, 160), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        rrect(ld, [180, 20, 900, 136], 58, fill=YELLOW, outline=INK, width=6)
        text_with_emoji(layer, 540, 78, txt, f, INK)
        paste_center(img, layer, 540, 270, scale=ease_back(sticker_p), alpha=clamp(sticker_p * 3))
    sp = prog(lt, c["smugglers"] - 0.1, 0.3)
    if sp > 0:
        siren = emoji_img("🚨", 120)
        flash = (int(lt * 6) % 2) == 0
        paste_center(img, siren, 200, 900, scale=ease_back(sp) * (1.1 if flash else 0.95))
        sticker(img, "SMUGGLERS: CAUGHT 📦", 600, 900, sp, size=54, bg=RED, fg=WHITE, angle=-3)


def scene_clouds(img, s, lt):
    c = s["cue_t"]
    sky = np.linspace(0, 1, SPLIT)[:, None, None]
    top, bot = np.array([70, 140, 230]), np.array([190, 225, 255])
    arr = np.broadcast_to(top + (bot - top) * sky, (SPLIT, W, 3)).astype(np.uint8)
    img.alpha_composite(Image.fromarray(arr).convert("RGBA"))
    d = ImageDraw.Draw(img)
    sea_y, lake_y = 930, 440
    d.rectangle([0, sea_y, W, SPLIT], fill=MAP_OCEAN)
    for x in range(-40, W, 80):
        xx = x + (lt * 60) % 80
        d.arc([xx, sea_y - 10, xx + 80, sea_y + 14], 180, 360, fill=WHITE, width=4)
    mountain = [(0, sea_y), (120, 700), (230, 520), (300, 380), (360, 300), (420, 400), (470, lake_y),
                (840, lake_y), (880, 330), (930, 250), (990, 360), (1080, 470), (1080, sea_y)]
    d.polygon(mountain, fill=(110, 90, 80))
    d.polygon([(300, 380), (360, 300), (420, 400), (390, 380), (360, 400), (330, 370)], fill=WHITE)
    d.polygon([(880, 330), (930, 250), (990, 360), (960, 340), (930, 360), (900, 335)], fill=WHITE)
    d.rectangle([470, lake_y - 4, 840, lake_y + 26], fill=(40, 120, 210))
    d.line([(470, lake_y - 4), (840, lake_y - 4)], fill=(170, 220, 255), width=4)
    bob = math.sin(lt * 4) * 5
    paste_center(img, emoji_img("🚤", 140), 655, lake_y - 30 + bob, scale=0.8, angle=math.sin(lt * 3) * 4)
    for k in range(5):  # clouds drifting below the lake
        x = (k * 260 + lt * (40 + k * 8)) % (W + 300) - 150
        paste_center(img, emoji_img("☁", 160), x, 560 + (k % 3) * 70, scale=0.9 + 0.2 * (k % 2), alpha=0.95)
    text_center(d, 960, sea_y + 40, "SEA LEVEL", font(IMPACT, 42), WHITE, stroke=4, anchor="mm")
    # altitude meter on the left
    fp = ease_out(prog(lt, c["four"] - 0.1, 0.9))
    x0, x1 = 60, 100
    rrect(d, [x0, lake_y, x1, sea_y], 18, fill=(0, 0, 0, 140), outline=WHITE, width=4)
    top_y = sea_y - (sea_y - lake_y) * fp
    if fp > 0.02:
        rrect(d, [x0 + 6, top_y, x1 - 6, sea_y - 6], 12, fill=YELLOW)
    alt = int(3812 * fp)
    d.text((x1 + 18, top_y), f"{alt:,} M", font=font(IMPACT, 60), fill=WHITE, anchor="lm",
           stroke_width=5, stroke_fill=INK)
    sticker(img, "NAVY IN THE CLOUDS ☁", 560, 250, prog(lt, c["clouds"] - 0.1, 0.35), size=66, bg=WHITE)


def rays(img, lt, col_a, col_b, cy=600):
    r = Image.new("RGBA", (W, SPLIT), col_a + (255,))
    d = ImageDraw.Draw(r)
    n = 16
    for k in range(n):
        a0 = lt * 0.4 + k * 2 * math.pi / n
        a1 = a0 + math.pi / n
        d.polygon([(540, cy), (540 + 1600 * math.cos(a0), cy + 1600 * math.sin(a0)),
                   (540 + 1600 * math.cos(a1), cy + 1600 * math.sin(a1))], fill=col_b)
    img.alpha_composite(r)


def scene_ready(img, s, lt):
    c = s["cue_t"]
    rays(img, lt, (30, 60, 120), (45, 80, 150))
    d = ImageDraw.Draw(img)
    for k in range(3):
        y = 800 + k * 50
        for x in range(-80, W + 80, 120):
            xx = x + ((lt * (80 + k * 30)) % 120)
            d.ellipse([xx, y, xx + 140, y + 70], fill=(40 + k * 15, 110 + k * 20, 210))
    d.rectangle([0, 850, W, SPLIT], fill=(40, 120, 220))
    bob = math.sin(lt * 3) * 12
    paste_center(img, wavy(ASSETS["flags"]["bolivia"], lt), 560, 360 + bob, scale=0.7)
    d = ImageDraw.Draw(img)
    d.line([(450, 330 + bob), (450, 600 + bob)], fill=(60, 60, 60), width=10)
    paste_center(img, emoji_img("🚢", 360), 540, 680 + bob, angle=math.sin(lt * 2) * 3)
    sticker(img, "A PROMISE 🤝", 540, 250, prog(lt, c["promise"] - 0.1, 0.35), size=70, bg=WHITE)
    rp = prog(lt, c["ready"] - 0.05, 0.3)
    if rp > 0:
        st = Image.new("RGBA", (760, 260), (0, 0, 0, 0))
        text_center(ImageDraw.Draw(st), 380, 130, "READY.", font(IMPACT, 220), RED, stroke=10,
                    stroke_fill=WHITE, anchor="mm")
        paste_center(img, st, 540, 520, scale=2.2 - 1.2 * ease_back(rp), alpha=clamp(rp * 3), angle=-8)
        paste_center(img, emoji_img("🫡", 200), 880, 820, scale=ease_back(prog(lt, c["ready"] + 0.1, 0.3)))


def scene_outro(img, s, lt):
    c = s["cue_t"]
    rays(img, lt, (24, 40, 70), (34, 56, 96), cy=520)
    sticker(img, "LANDLOCKED NAVY CLUB ⚓", 540, 255, prog(lt, 0.0, 0.4), size=66, bg=YELLOW)
    d = ImageDraw.Draw(img)
    p1 = ease_back(prog(lt, 0.05, 0.4))
    paste_center(img, wavy(ASSETS["flags"]["bolivia"], lt), 290, 520, scale=max(0.0, p1))
    if p1 > 0.3:
        text_center(d, 290, 650, "BOLIVIA", font(IMPACT, 64), WHITE, stroke=5)
    p2 = ease_back(prog(lt, c["paraguay"] - 0.1, 0.4))
    paste_center(img, wavy(ASSETS["flags"]["paraguay"], lt + 1), 790, 520, scale=max(0.0, p2))
    if p2 > 0.3:
        text_center(d, 790, 650, "PARAGUAY", font(IMPACT, 64), WHITE, stroke=5)
    np_ = prog(lt, c["navy"] - 0.05, 0.35)
    paste_center(img, emoji_img("🤝", 160), 540, 520, scale=ease_back(np_), angle=math.sin(lt * 5) * 10)
    for x in (290, 790):
        paste_center(img, emoji_img("⚓", 120), x, 800, scale=ease_back(np_) * 0.9,
                     angle=math.sin(lt * 4 + x) * 12)
    sticker(img, "ALSO HAS A NAVY", 790, 930, np_, size=48, bg=RED, fg=WHITE, angle=3)


SCENE_DRAW = {"hook": scene_hook, "war": scene_war, "cope": scene_cope, "court": scene_court,
              "seaday": scene_seaday, "navy": scene_navy, "clouds": scene_clouds, "ready": scene_ready,
              "outro": scene_outro}


def header(img):
    d = ImageDraw.Draw(img)
    text_center(d, W / 2, 26, "WHY DOES LANDLOCKED BOLIVIA", font(IMPACT, 58), WHITE, stroke=5)
    text_with_emoji(img, W / 2, 132, "HAVE A NAVY? 🤔", font(IMPACT, 82), YELLOW, stroke=6)


def top_half(scene, lt):
    img = ASSETS["top_bg"].copy()
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
RIVER = (150, 930)
LANES = [310, 540, 770]
SPEED = 640  # world px per second
BOAT_Y = GH - 200
SWITCH = 210  # travel distance for a lane change
TILE_H = GH * 4


def make_river_tile():
    """Seamless vertical tile: jungle banks with palms and llamas, rippling water."""
    im = Image.new("RGBA", (W, TILE_H), (36, 128, 66, 255))
    d = ImageDraw.Draw(im)
    rnd = random.Random(9)
    for _ in range(500):
        x, y = rnd.uniform(0, W), rnd.uniform(0, TILE_H)
        d.ellipse([x - 12, y - 8, x + 12, y + 8], fill=(28, 110, 56))
    left, right = [], []
    for y in range(0, TILE_H + 1, 20):
        wob = 22 * math.sin(2 * math.pi * y / TILE_H * 5) + 10 * math.sin(2 * math.pi * y / TILE_H * 13)
        left.append((RIVER[0] + wob, y))
        right.append((RIVER[1] + wob * 0.8, y))
    d.polygon(left + right[::-1], fill=(214, 190, 120))
    water = [(x + 16, y) for x, y in left] + [(x - 16, y) for x, y in right[::-1]]
    d.polygon(water, fill=(26, 132, 170))
    for _ in range(260):
        y = rnd.uniform(0, TILE_H)
        x = rnd.uniform(RIVER[0] + 50, RIVER[1] - 80)
        L = rnd.uniform(20, 60)
        for yy in (y, y - TILE_H, y + TILE_H):
            d.line([x, yy, x + L, yy], fill=(110, 200, 230), width=3)
    for k in range(34):
        side = k % 2
        y = (k + rnd.uniform(0, 0.6)) * TILE_H / 34
        x = rnd.uniform(20, RIVER[0] - 50) if side == 0 else rnd.uniform(RIVER[1] + 50, W - 20)
        ch = "🦙" if rnd.random() < 0.25 else rnd.choice(["🌴", "🌴", "🌿"])
        for yy in (y, y - TILE_H, y + TILE_H):
            paste_center(im, emoji_img(ch, 120, mirror=side == 1), x, yy, scale=0.85)
    return im


def make_log():
    im = Image.new("RGBA", (200, 70), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    rrect(d, [4, 8, 196, 62], 26, fill=(120, 76, 40), outline=(60, 36, 18), width=4)
    for x in (40, 90, 140):
        d.line([x, 16, x + 20, 54], fill=(90, 56, 28), width=3)
    d.ellipse([168, 12, 196, 58], fill=(196, 150, 96), outline=(60, 36, 18), width=3)
    return im


def make_boat():
    """Top-down patrol boat, bow up, with a Bolivian-flag stripe on the stern."""
    im = Image.new("RGBA", (120, 230), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    hull = [(60, 4), (88, 40), (106, 100), (108, 200), (100, 222), (20, 222), (12, 200), (14, 100),
            (32, 40)]
    d.polygon(hull, fill=(236, 240, 246), outline=INK, width=5)
    d.polygon([(60, 30), (84, 64), (94, 110), (94, 196), (26, 196), (26, 110), (36, 64)], fill=(150, 160, 175))
    rrect(d, [34, 100, 86, 160], 10, fill=(30, 60, 120), outline=INK, width=3)
    d.rectangle([40, 104, 80, 118], fill=(140, 200, 255))
    for i, c in enumerate((BOL_RED, BOL_YEL, BOL_GRN)):
        d.rectangle([20 + i * 27, 200, 47 + i * 27, 218], fill=c)
    d.ellipse([52, 70, 68, 86], fill=(80, 80, 90), outline=INK, width=2)
    return im


def make_course(total):
    rnd = random.Random(11)
    length = SPEED * total + 2000
    obstacles, switches = [], []
    lane, p = 1, 900.0
    while p < length:
        L = rnd.randrange(3)
        if L == lane:
            new = rnd.choice([l for l in (lane - 1, lane + 1) if 0 <= l < 3])
            switches.append((p - 360, lane, new))
            lane = new
        obstacles.append((p, L, rnd.choice(["rock", "croc", "log", "rock"])))
        p += rnd.uniform(480, 600)
    coins = []
    for (a, _, _), (b, _, _) in zip(obstacles, obstacles[1:]):
        for k in range(4):
            cp = a + 110 + k * 85
            if cp < b - 120:
                coins.append((cp, boat_x(switches, cp)))
    return obstacles, switches, coins


def boat_x(switches, d):
    x = LANES[1]
    for s, a, b in switches:
        if d < s:
            break
        u = (d - s) / SWITCH
        x = LANES[b] if u >= 1 else LANES[a] + (LANES[b] - LANES[a]) * smooth(u)
    return x


def bottom_half(course, t):
    obstacles, switches, coins = course
    dist = t * SPEED
    img = Image.new("RGBA", (W, GH))
    off = int(dist % TILE_H)
    img.paste(ASSETS["river"].crop((0, TILE_H - off, W, TILE_H)), (0, 0))
    if off < GH:
        img.paste(ASSETS["river"].crop((0, 0, W, GH - off)), (0, off))
    d = ImageDraw.Draw(img)

    def sy(p):
        return BOAT_Y - (p - dist)

    bx = boat_x(switches, dist)
    lean = (boat_x(switches, dist + 30) - bx) / 30
    # wake behind the boat
    wake = Image.new("RGBA", (W, GH), (0, 0, 0, 0))
    wd = ImageDraw.Draw(wake)
    trail = [(boat_x(switches, dist - k * 40), BOAT_Y + 60 + k * 40) for k in range(9)]
    for k, (x, y) in enumerate(trail):
        spread = 20 + k * 16
        a = int(170 * (1 - k / 9))
        wd.ellipse([x - spread - 8, y - 8, x - spread + 8, y + 8], fill=(255, 255, 255, a))
        wd.ellipse([x + spread - 8, y - 8, x + spread + 8, y + 8], fill=(255, 255, 255, a))
        wd.ellipse([x - 14, y - 10, x + 14, y + 10], fill=(220, 245, 255, a // 2))
    img.alpha_composite(wake.filter(ImageFilter.GaussianBlur(3)))

    got = 0
    for cp, cx in coins:
        y = sy(cp)
        if cp < dist:
            got += 1
            if cp > dist - 120:
                age = (dist - cp) / SPEED
                d.text((cx + 40, BOAT_Y - 60 - age * 300), "+1", font=font(IMPACT, 46), fill=YELLOW,
                       anchor="mm", stroke_width=3, stroke_fill=INK)
            continue
        if -40 < y < GH + 40:
            squeeze = abs(math.cos(t * 6 + cp * 0.01))
            rw = 24 * squeeze + 4
            d.ellipse([cx - rw, y - 24, cx + rw, y + 24], fill=(255, 205, 40), outline=(200, 130, 0), width=4)
    for p, lane, kind in obstacles:
        y = sy(p)
        if not -120 < y < GH + 120:
            continue
        x = LANES[lane]
        if kind == "rock":
            paste_center(img, emoji_img("🪨", 120), x, y, scale=1.0)
        elif kind == "croc":
            paste_center(img, emoji_img("🐊", 120), x, y, scale=1.1, angle=math.sin(t * 6 + p) * 8)
        else:
            paste_center(img, ASSETS["log"], x, y)
        d.arc([x - 80, y - 30, x + 80, y + 50], 20, 160, fill=(200, 235, 250), width=3)

    paste_center(img, ASSETS["boat"], bx, BOAT_Y, angle=-lean * 25)

    hud = ImageDraw.Draw(img)
    rrect(hud, [24, 110, 260, 182], 36, fill=(0, 0, 0, 150))
    paste_center(img, emoji_img("🪙", 120), 66, 146, scale=0.42)
    hud.text((106, 146), f"x {got}", font=font(IMPACT, 50), fill=WHITE, anchor="lm")
    rrect(hud, [W - 330, 110, W - 24, 182], 36, fill=(0, 0, 0, 150))
    hud.text((W - 177, 146), "NAVY SIM", font=font(IMPACT, 46), fill=WHITE, anchor="mm")
    paste_center(img, emoji_img("⚓", 120), W - 60, 146, scale=0.38)
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
    img.paste(top_half(scene, lt), (0, 0))
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
    ASSETS["river"] = make_river_tile()
    ASSETS["log"] = make_log()
    ASSETS["boat"] = make_boat()
    course = make_course(total)
    OUT.mkdir(parents=True, exist_ok=True)

    if "--preview" in sys.argv:
        times = [float(x) for x in sys.argv[sys.argv.index("--preview") + 1:]]
        for t in times:
            render_frame(scenes, booms, course, total, t).save(OUT / f"preview_{t:05.1f}.png")
        print("scene starts:", [(s["id"], round(s["start"], 2)) for s in scenes], "total", round(total, 2))
        return

    audio = build_audio(scenes, total)
    out = OUT / "bolivia_navy_landlocked.mp4"
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
