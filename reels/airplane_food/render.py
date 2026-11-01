"""Render the 'Why airplane food tastes bland' reel (1080x1920, 30fps).

Run voiceover.py first. Frames are drawn with Pillow and piped straight into ffmpeg.
Usage: python render.py [--preview SECONDS ...]   (preview writes PNG stills instead)
"""

import json
import math
import random
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from script import SCENES

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output" / "airplane_food"
VO = OUT / "vo"

W, H, FPS = 1080, 1920, 30
SR = 48000
PAD = 0.3  # silence after each scene's line

FONTS = Path("C:/Windows/Fonts")
IMPACT = str(FONTS / "impact.ttf")
BOLD = str(FONTS / "seguibl.ttf")
SEMI = str(FONTS / "segoeuib.ttf")

AMBER = (255, 184, 48)
RED = (255, 84, 84)
GREEN = (92, 220, 140)
WHITE = (255, 255, 255)
SKY = (120, 190, 255)
INK = (14, 18, 40)

_font_cache = {}


def font(path, size):
    key = (path, size)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(path, size)
    return _font_cache[key]


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


def prog(t, start, dur):
    return clamp((t - start) / dur)


# ---------- timeline ----------

def load_timeline():
    scenes, t = [], 0.0
    for s in SCENES:
        audio = decode(VO / f"{s['id']}.mp3")
        words = json.loads((VO / f"{s['id']}.json").read_text())
        dur = len(audio) / SR + PAD
        scenes.append({**s, "start": t, "dur": dur, "audio": audio, "words": words})
        t += dur
    return scenes, t


def decode(path):
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
        check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def chunk_words(words):
    """Group words into caption chunks of <=3 words, splitting at pauses."""
    chunks, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        pause = nxt is not None and nxt["start"] - w["end"] > 0.18
        if len(cur) >= 3 or pause or nxt is None:
            chunks.append(cur)
            cur = []
    return chunks


# ---------- audio ----------

def build_audio(scenes, total):
    n = int(total * SR) + SR
    voice = np.zeros(n, np.float32)
    for s in scenes:
        i = int(s["start"] * SR)
        voice[i:i + len(s["audio"])] += s["audio"]

    rng = np.random.default_rng(7)
    # Cabin hum: brown noise, low-passed by integration, plus a faint engine tone.
    brown = np.cumsum(rng.standard_normal(n)).astype(np.float32)
    brown -= np.convolve(brown, np.ones(4801) / 4801, mode="same")
    brown /= np.abs(brown).max() + 1e-9
    tt = np.arange(n) / SR
    hum = 0.05 * brown + 0.012 * np.sin(2 * np.pi * 110 * tt) * (1 + 0.2 * np.sin(2 * np.pi * 0.3 * tt))

    # Whoosh on each scene change.
    fx = np.zeros(n, np.float32)
    wl = int(0.45 * SR)
    env = np.sin(np.linspace(0, np.pi, wl)) ** 2
    for s in scenes[1:]:
        noise = rng.standard_normal(wl).astype(np.float32)
        noise = np.convolve(noise, np.ones(6) / 6, mode="same")  # soften the hiss
        i = max(0, int((s["start"] - 0.2) * SR))
        fx[i:i + wl] += 0.18 * noise * env

    mix = voice * 1.0 + hum + fx
    fade = int(0.8 * SR)
    end = int(total * SR)
    mix[end - fade:end] *= np.linspace(1, 0, fade)
    mix[end:] = 0
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

def make_background():
    y = np.linspace(0, 1, H)[:, None]
    top = np.array([18, 24, 62])
    bottom = np.array([60, 22, 70])
    grad = top + (bottom - top) * y
    img = np.repeat(grad[:, None, :], W, axis=1).reshape(H, W, 3)
    # soft vignette
    xx = np.linspace(-1, 1, W)[None, :]
    yy = np.linspace(-1, 1, H)[:, None]
    vig = 1 - 0.35 * np.clip(xx ** 2 + yy ** 2 * 0.6, 0, 1)
    img = img * vig[..., None]
    return Image.fromarray(img.astype(np.uint8)).convert("RGBA")


random.seed(3)
CLOUDS = [(random.uniform(0, W), random.uniform(150, H - 150), random.uniform(120, 260),
           random.uniform(12, 30)) for _ in range(9)]


def draw_clouds(img, t):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for x0, y, r, speed in CLOUDS:
        x = (x0 - t * speed) % (W + 2 * r) - r
        for dx, dy, k in ((0, 0, 1), (-r * 0.6, r * 0.15, 0.7), (r * 0.6, r * 0.18, 0.75)):
            rr = r * k
            d.ellipse([x + dx - rr, y + dy - rr * 0.55, x + dx + rr, y + dy + rr * 0.55],
                      fill=(255, 255, 255, 14))
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(18)))


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


def headline(img, scene, lt):
    p = ease_out(prog(lt, 0.0, 0.4))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    lines = scene["headline"].split("\n")
    size = 150 if len(lines) > 1 else 130
    f = font(IMPACT, size)
    y = (250 if len(lines) > 1 else 300) + (1 - p) * 80
    for ln in lines:
        text_center(d, W / 2 + 6, y + 6, ln, f, (0, 0, 0, 140))
        text_center(d, W / 2, y, ln, f, WHITE)
        y += size * 1.02
    # accent underline
    if len(lines) == 1:
        bw = d.textlength(lines[0], font=f) * ease_out(prog(lt, 0.2, 0.4))
        rrect(d, [W / 2 - bw / 2, y + 14, W / 2 + bw / 2, y + 26], 6, fill=AMBER)
    img.alpha_composite(with_alpha(layer, p))


def captions(img, scene, lt):
    chunks = chunk_words(scene["words"])
    cur = None
    for i, ch in enumerate(chunks):
        start = ch[0]["start"] - 0.05
        end = chunks[i + 1][0]["start"] - 0.05 if i + 1 < len(chunks) else scene["dur"]
        if start <= lt < end:
            cur = (ch, start)
            break
    if not cur:
        return
    ch, start = cur
    d0 = ImageDraw.Draw(img)
    words = [w["text"].upper() for w in ch]
    size = 84
    while True:  # shrink long chunks to fit the frame
        f = font(BOLD, size)
        space = d0.textlength(" ", font=f)
        widths = [d0.textlength(w, font=f) for w in words]
        total = sum(widths) + space * (len(words) - 1)
        if total <= W - 120 or size <= 50:
            break
        size -= 4
    pop = ease_back(prog(lt, start, 0.18))
    y = 1560 - pop * 20
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x = W / 2 - total / 2
    for w, wd, word in zip(ch, widths, words):
        active = w["start"] - 0.05 <= lt <= w["end"] + 0.12
        d.text((x, y), word, font=f, fill=AMBER if active else WHITE, anchor="lm",
               stroke_width=8, stroke_fill=(0, 0, 0))
        x += wd + space
    img.alpha_composite(with_alpha(layer, clamp(pop * 1.4)))


def progress_bar(img, t, total):
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 10], fill=(255, 255, 255, 40))
    d.rectangle([0, 0, W * t / total, 10], fill=AMBER)


# ---------- scene visuals ----------

def v_hook(img, lt, dur):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    p = ease_back(prog(lt, 0.2, 0.6))
    bob = math.sin(lt * 2.2) * 10
    cx, cy = W / 2, 1010 + bob + (1 - p) * 300
    # window frame
    ww, wh = 340, 460
    rrect(d, [cx - ww / 2 - 34, cy - wh / 2 - 34, cx + ww / 2 + 34, cy + wh / 2 + 34], 195,
          fill=(214, 218, 230))
    rrect(d, [cx - ww / 2, cy - wh / 2, cx + ww / 2, cy + wh / 2], 165, fill=(70, 140, 230))
    # clouds through window
    win = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    wd = ImageDraw.Draw(win)
    for i in range(4):
        x = (cx + 300 - ((lt * 160 + i * 190) % 760))
        y = cy - 150 + i * 95
        wd.ellipse([x - 110, y - 40, x + 110, y + 40], fill=(255, 255, 255, 230))
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle([cx - ww / 2, cy - wh / 2, cx + ww / 2, cy + wh / 2],
                                           radius=165, fill=255)
    clip = Image.fromarray(np.minimum(np.array(win.getchannel("A")), np.array(mask)))
    win.putalpha(clip)
    layer.alpha_composite(win)
    # meal tray
    tp = ease_back(prog(lt, 0.6, 0.6))
    ty = 1340 + (1 - tp) * 500
    rrect(d, [150, ty - 110, W - 150, ty + 110], 36, fill=(232, 228, 216), outline=(160, 150, 130),
          width=6)
    d.ellipse([200, ty - 80, 400, ty + 80], fill=(176, 160, 140))          # grey mystery meat
    d.ellipse([430, ty - 70, 600, ty + 70], fill=(150, 175, 110))          # mushy peas
    rrect(d, [640, ty - 70, 880, ty + 70], 40, fill=(222, 190, 130))       # bread roll
    # "meh" face sticker
    if lt > 1.6:
        sp = ease_back(prog(lt, 1.6, 0.4))
        r = 90 * sp
        sx, sy = W - 210, ty - 150
        d.ellipse([sx - r, sy - r, sx + r, sy + r], fill=AMBER, outline=INK, width=6)
        if sp > 0.5:
            d.ellipse([sx - 38, sy - 30, sx - 18, sy - 6], fill=INK)
            d.ellipse([sx + 18, sy - 30, sx + 38, sy - 6], fill=INK)
            d.line([sx - 40, sy + 38, sx + 40, sy + 38], fill=INK, width=10)
    img.alpha_composite(layer)


def v_pressure(img, lt, dur):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rise = ease_out(prog(lt, 0.0, 0.8))
    base = 1380
    # mountains
    for off, col, hgt in ((-120, (70, 60, 120), 250), (260, (95, 80, 150), 320), (620, (70, 60, 120), 230)):
        hgt *= rise
        d.polygon([(off - 360, base), (off + 120, base - hgt), (off + 600, base)], fill=col)
        d.polygon([(off + 120, base - hgt), (off + 60, base - hgt + 90 * rise),
                   (off + 185, base - hgt + 90 * rise)], fill=(240, 240, 255))
    d.rectangle([0, base, W, H], fill=(40, 34, 80))
    # counter
    p = ease_out(prog(lt, 0.4, 1.8))
    val = int(round(8000 * p / 100) * 100)
    f = font(IMPACT, 230)
    text_center(d, W / 2, 620, f"{val:,}", f, AMBER, stroke=6)
    text_center(d, W / 2, 870, "FEET", font(IMPACT, 90), WHITE, stroke=4)
    if lt > 3.0:
        a = ease_out(prog(lt, 3.0, 0.4))
        sub = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(sub)
        rrect(sd, [150, 1010, W - 150, 1110], 50, fill=(0, 0, 0, 150))
        text_center(sd, W / 2, 1060, "= SITTING ON A MOUNTAIN", font(BOLD, 52), WHITE, anchor="mm")
        layer.alpha_composite(with_alpha(sub, a))
    img.alpha_composite(layer)


def v_humidity(img, lt, dur):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rows = [("YOUR HOME", 0.50, "40-60%", SKY), ("DESERT", 0.25, "~25%", AMBER),
            ("PLANE CABIN", 0.12, "UNDER 20%", RED)]
    y = 620
    for i, (label, frac, txt, col) in enumerate(rows):
        p = ease_out(prog(lt, 0.3 + i * 0.6, 0.9))
        d.text((120, y), label, font=font(BOLD, 56), fill=WHITE, anchor="lm")
        rrect(d, [120, y + 50, W - 120, y + 130], 40, fill=(255, 255, 255, 40))
        bw = (W - 240) * frac * 1.6 * p
        rrect(d, [120, y + 50, 120 + max(80, bw), y + 130], 40, fill=col + (255,))
        d.text((W - 120, y), txt, font=font(IMPACT, 60), fill=col, anchor="rm")
        y += 230
    # nose + "smell = flavor" callout
    if lt > 3.6:
        a = ease_back(prog(lt, 3.6, 0.5))
        sub = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(sub)
        rrect(sd, [130, 1300 - 70 * a, W - 130, 1420 - 70 * a], 60, fill=(255, 255, 255, 235))
        text_center(sd, W / 2, 1360 - 70 * a, "SMELL  =  MOST OF FLAVOR", font(BOLD, 54), INK,
                    anchor="mm")
        layer.alpha_composite(with_alpha(sub, a))
    img.alpha_composite(layer)


def v_stat(img, lt, dur):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    p = ease_out(prog(lt, 2.4, 1.2))
    pop = ease_back(prog(lt, 2.4, 0.5))
    f = font(IMPACT, int(150 + 170 * pop))
    text_center(d, W / 2, 760, f"-{int(round(30 * p))}%", f, RED, stroke=8, anchor="mm")
    for i, (label, col) in enumerate((("SALT", WHITE), ("SWEET", (255, 160, 200)))):
        y = 1040 + i * 170
        d.text((120, y), label, font=font(BOLD, 56), fill=WHITE, anchor="lm")
        rrect(d, [330, y - 40, W - 120, y + 40], 40, fill=(255, 255, 255, 40))
        full = W - 120 - 330
        bw = full * (1 - 0.3 * p) * ease_out(prog(lt, 0.2 + i * 0.3, 0.7))
        rrect(d, [330, y - 40, 330 + max(80, bw), y + 40], 40, fill=col + (255,))
    text_center(d, W / 2, 1385, "Fraunhofer Institute for Lufthansa, 2010", font(SEMI, 34),
                (255, 255, 255, 150))
    img.alpha_composite(layer)


def v_noise(img, lt, dur):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    n = 17
    bw = 44
    gap = (W - 160 - n * bw) / (n - 1)
    grow = ease_out(prog(lt, 0.0, 0.6))
    cy = 1080
    for i in range(n):
        amp = (0.35 + 0.65 * abs(math.sin(lt * 7.3 + i * 1.7) * math.sin(lt * 3.1 + i * 0.6)))
        amp *= 1 - abs(i - n // 2) / (n * 0.75)
        h = 30 + 300 * amp * grow
        x = 80 + i * (bw + gap)
        col = AMBER if amp < 0.55 else RED
        rrect(d, [x, cy - h, x + bw, cy + h], 22, fill=col)
    pop = ease_back(prog(lt, 1.6, 0.5))
    if pop > 0:
        f = font(IMPACT, int(220 * pop) + 1)
        text_center(d, W / 2 + 8, 640 + 8, "85 dB", f, (0, 0, 0, 160), anchor="mm")
        text_center(d, W / 2, 640, "85 dB", f, WHITE, anchor="mm")
    if lt > 3.2:
        a = ease_out(prog(lt, 3.2, 0.4))
        sub = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(sub)
        rrect(sd, [140, 1340, W - 140, 1440], 50, fill=(0, 0, 0, 160))
        text_center(sd, W / 2, 1390, "ABOUT AS LOUD AS A BLENDER", font(BOLD, 48), WHITE, anchor="mm")
        layer.alpha_composite(with_alpha(sub, a))
    img.alpha_composite(layer)


def v_umami(img, lt, dur):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    p = ease_back(prog(lt, 0.1, 0.7))
    bounce = abs(math.sin(lt * 3.0)) * 24
    cx, cy, r = W / 2, 860 - bounce, 210 * p
    if r > 1:
        d.ellipse([cx - r, cy - r * 0.92, cx + r, cy + r * 0.92], fill=(226, 50, 45))
        d.ellipse([cx - r * 0.6, cy - r * 0.62, cx - r * 0.15, cy - r * 0.25], fill=(255, 140, 130))
        for k in range(5):
            ang = -math.pi / 2 + k * 2 * math.pi / 5
            tip = (cx + math.cos(ang) * r * 0.55, cy - r * 0.8 + math.sin(ang) * r * 0.3)
            d.polygon([(cx - 18 * p, cy - r * 0.82), (cx + 18 * p, cy - r * 0.82), tip],
                      fill=(70, 170, 70))
        d.rectangle([cx - 8, cy - r * 1.05, cx + 8, cy - r * 0.8], fill=(60, 130, 60))
    chips = [("SWEET", RED, "DOWN"), ("SALTY", RED, "DOWN"), ("UMAMI", GREEN, "SURVIVES")]
    for i, (name, col, tag) in enumerate(chips):
        a = ease_back(prog(lt, 1.2 + i * 0.45, 0.4))
        if a <= 0:
            continue
        y = 1160 + i * 120
        sub = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(sub)
        rrect(sd, [190, y - 48, W - 190, y + 48], 48, fill=(0, 0, 0, 150), outline=col, width=5)
        sd.text((240, y), name, font=font(BOLD, 52), fill=WHITE, anchor="lm")
        sd.text((W - 240, y), tag, font=font(IMPACT, 56), fill=col, anchor="rm")
        layer.alpha_composite(with_alpha(sub, clamp(a)))
    img.alpha_composite(layer)


def v_kitchen(img, lt, dur):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    steps = [("COOKED", "on the ground", AMBER), ("CHILLED", "for hours", SKY),
             ("REHEATED", "at 35,000 ft", RED)]
    x0, x1, y = 200, W - 200, 820
    lp = ease_out(prog(lt, 0.3, 3.4))
    d.line([x0, y, x1, y], fill=(255, 255, 255, 60), width=14)
    d.line([x0, y, x0 + (x1 - x0) * lp, y], fill=WHITE, width=14)
    for i, (title, sub, col) in enumerate(steps):
        x = x0 + (x1 - x0) * i / 2
        a = ease_back(prog(lt, 0.3 + i * 1.5, 0.5))
        if a <= 0:
            continue
        r = 70 * a
        d.ellipse([x - r, y - r, x + r, y + r], fill=col, outline=WHITE, width=8)
        text_center(d, x, y, str(i + 1), font(IMPACT, int(80 * a) + 1), INK, anchor="mm")
        text_center(d, x, y + 110, title, font(IMPACT, 64), col)
        text_center(d, x, y + 190, sub, font(SEMI, 36), WHITE)
    # clock
    cx, cy, cr = W / 2, 1240, 120
    d.ellipse([cx - cr, cy - cr, cx + cr, cy + cr], outline=WHITE, width=10)
    for k in range(12):
        ang = k * math.pi / 6
        d.line([cx + math.cos(ang) * cr * 0.8, cy + math.sin(ang) * cr * 0.8,
                cx + math.cos(ang) * cr * 0.92, cy + math.sin(ang) * cr * 0.92], fill=WHITE, width=6)
    ang = lt * 4 - math.pi / 2
    d.line([cx, cy, cx + math.cos(ang) * cr * 0.75, cy + math.sin(ang) * cr * 0.75], fill=AMBER, width=10)
    ang = lt * 0.35 - math.pi / 2
    d.line([cx, cy, cx + math.cos(ang) * cr * 0.5, cy + math.sin(ang) * cr * 0.5], fill=WHITE, width=12)
    img.alpha_composite(layer)


def v_tips(img, lt, dur):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    tips = [("GO SPICY", "curry, chili, pepper"), ("GO SAVORY", "umami, tomato juice"),
            ("DRINK WATER", "fight the dry air")]
    for i, (title, sub) in enumerate(tips):
        a = ease_back(prog(lt, 0.4 + i * 0.7, 0.45))
        if a <= 0:
            continue
        y = 640 + i * 200
        xo = (1 - a) * -400
        sub_l = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(sub_l)
        rrect(sd, [120 + xo, y - 80, W - 120 + xo, y + 80], 40, fill=(255, 255, 255, 235))
        sd.ellipse([160 + xo, y - 48, 256 + xo, y + 48], fill=GREEN)
        sd.line([(185 + xo, y + 2), (203 + xo, y + 22), (234 + xo, y - 18)], fill=WHITE, width=12,
                joint="curve")
        sd.text((290 + xo, y - 22), title, font=font(IMPACT, 66), fill=INK, anchor="lm")
        sd.text((292 + xo, y + 38), sub, font=font(SEMI, 34), fill=(80, 80, 110), anchor="lm")
        layer.alpha_composite(with_alpha(sub_l, clamp(a)))
    if lt > 3.9:
        a = ease_back(prog(lt, 3.9, 0.5))
        pulse = 1 + 0.04 * math.sin(lt * 8)
        f = font(IMPACT, int(88 * a * pulse) + 1)
        rrect(d, [170, 1300 - 75 * a, W - 170, 1300 + 75 * a], 75, fill=AMBER)
        text_center(d, W / 2, 1300, "FOLLOW FOR MORE", f, INK, anchor="mm")
    img.alpha_composite(layer)


VISUALS = {"hook": v_hook, "pressure": v_pressure, "humidity": v_humidity, "stat": v_stat,
           "noise": v_noise, "umami": v_umami, "kitchen": v_kitchen, "tips": v_tips}


def render_frame(bg, scenes, total, t):
    img = bg.copy()
    draw_clouds(img, t)
    scene = next(s for s in reversed(scenes) if t >= s["start"])
    lt = t - scene["start"]
    VISUALS[scene["id"]](img, lt, scene["dur"])
    headline(img, scene, lt)
    captions(img, scene, lt)
    progress_bar(img, t, total)
    # quick flash on scene change
    if scene is not scenes[0] and lt < 0.12:
        flash = Image.new("RGBA", (W, H), (255, 255, 255, int(120 * (1 - lt / 0.12))))
        img.alpha_composite(flash)
    return img.convert("RGB")


def main():
    scenes, total = load_timeline()
    bg = make_background()
    OUT.mkdir(parents=True, exist_ok=True)

    if "--preview" in sys.argv:
        times = [float(x) for x in sys.argv[sys.argv.index("--preview") + 1:]]
        for t in times:
            render_frame(bg, scenes, total, t).save(OUT / f"preview_{t:05.1f}.png")
        print("scene starts:", [(s["id"], round(s["start"], 2)) for s in scenes], "total", round(total, 2))
        return

    audio = build_audio(scenes, total)
    out = OUT / "why_airplane_food_is_bland.mp4"
    ff = subprocess.Popen([
        "ffmpeg", "-y", "-v", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
        "-i", str(audio),
        "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out),
    ], stdin=subprocess.PIPE)
    frames = int(total * FPS)
    for i in range(frames):
        ff.stdin.write(render_frame(bg, scenes, total, i / FPS).tobytes())
        if i % 150 == 0:
            print(f"frame {i}/{frames}", file=sys.stderr)
    ff.stdin.close()
    ff.wait()
    print(out)


if __name__ == "__main__":
    main()
