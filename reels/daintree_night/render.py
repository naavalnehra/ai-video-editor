"""Render the '$1 million to spend one night in the Daintree' reel (1080x1920, 30fps).

A hook with a money counter, the rules, six hazards counted down through the night
(clock, torch spotlight, danger skulls, NOPE-O-METER) and a 'Would you do it?' ending.
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

from script import HAZARDS, SCENES

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output" / "daintree_night"
VO = OUT / "vo"

W, H, FPS = 1080, 1920, 30
SR = 48000
PAD = 0.35  # silence after each scene's line

FONTS = Path("C:/Windows/Fonts")
IMPACT = str(FONTS / "impact.ttf")
BOLD = str(FONTS / "seguibl.ttf")
SEMI = str(FONTS / "segoeuib.ttf")
EMOJI = str(FONTS / "seguiemj.ttf")

GOLD = (255, 200, 40)
JUNGLE = (60, 220, 110)
RED = (235, 50, 60)
WHITE = (255, 255, 255)
INK = (10, 14, 20)
GREY = (150, 150, 165)

SPOT_Y = 760  # where each hazard appears, in the torch beam

_font_cache = {}
_emoji_cache = {}
_bg_cache = {}


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


def prog(t, start, dur):
    return clamp((t - start) / dur)


def lerp(a, b, p):
    return tuple(int(x + (y - x) * p) for x, y in zip(a, b))


# ---------- timeline ----------

def norm(word):
    return re.sub(r"[^a-z]", "", word.lower())


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
        cues = {k: cue_time(words, v) for k, v in s.get("cues", {}).items()}
        if "cue" in s:
            cues["reveal"] = cue_time(words, s["cue"])
        scenes.append({**s, "start": t, "dur": dur, "audio": audio, "words": words, "cue_t": cues})
        t += dur
    return scenes, t


def decode(path):
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
        check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def reveals(scenes):
    """Absolute reveal time of every hazard."""
    return [s["start"] + s["cue_t"]["reveal"] for s in scenes if "cue" in s]


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
    tt = np.arange(n) / SR
    bed = np.zeros(n, np.float32)

    # Low uneasy drone with a slow swell.
    drone = (np.sin(2 * np.pi * 55 * tt) + 0.6 * np.sin(2 * np.pi * 58.3 * tt)
             + 0.35 * np.sin(2 * np.pi * 110.5 * tt))
    bed += 0.05 * drone * (0.7 + 0.3 * np.sin(2 * np.pi * tt / 6))

    # Crickets: triple chirps of a ~4.6 kHz tone, scattered, gone by sunrise.
    dawn = next(s["start"] for s in scenes if s["id"] == "h6")
    cl = int(0.035 * SR)
    ct = np.arange(cl) / SR
    chirp = np.sin(2 * np.pi * 4600 * ct) * np.sin(np.pi * ct / ct[-1])
    t = 0.2
    while t < dawn:
        for k in range(3):
            i = int((t + k * 0.06) * SR)
            bed[i:i + cl] += 0.018 * chirp
        t += rng.uniform(0.5, 1.1)

    # Heartbeat through the hazards, speeding up as the night goes on.
    hl = int(0.16 * SR)
    ht = np.arange(hl) / SR
    thump = np.sin(2 * np.pi * np.cumsum(40 + 50 * np.exp(-ht * 40)) / SR) * np.exp(-ht * 22)
    for k, s in enumerate(x for x in scenes if "cue" in x):
        bpm = 70 + k * 12
        t = s["start"]
        while t < s["start"] + s["dur"]:
            for off, amp in ((0, 0.22), (0.2, 0.14)):
                i = int((t + off) * SR)
                bed[i:i + hl] += amp * thump[:max(0, min(hl, n - i))]
            t += 60 / bpm

    fx = np.zeros(n, np.float32)
    # Whoosh on each scene change.
    wl = int(0.45 * SR)
    env = np.sin(np.linspace(0, np.pi, wl)) ** 2
    for s in scenes[1:]:
        noise = np.convolve(rng.standard_normal(wl), np.ones(6) / 6, mode="same")
        i = max(0, int((s["start"] - 0.2) * SR))
        fx[i:i + wl] += 0.14 * noise * env
    # Horror sting on every hazard: sub boom + dissonant stab.
    il = int(1.1 * SR)
    it = np.arange(il) / SR
    boom = np.sin(2 * np.pi * np.cumsum(34 + 90 * np.exp(-it * 16)) / SR) * np.exp(-it * 4)
    boom += 0.3 * rng.standard_normal(il) * np.exp(-it * 25)
    stab = sum(np.sign(np.sin(2 * np.pi * f * it)) for f in (466, 494, 698)) / 3
    stab *= np.exp(-it * 5)
    for rt in reveals(scenes):
        i = int(rt * SR)
        fx[i:i + il] += (0.5 * boom + 0.07 * stab)[:max(0, min(il, n - i))]
    # Coins while the hook's counter rolls up, and a cash-register ding at the end.
    hook = scenes[0]
    m0 = hook["start"] + max(0.0, hook["cue_t"]["money"] - 0.5)
    dl = int(0.25 * SR)
    dt = np.arange(dl) / SR
    coin = (np.sin(2 * np.pi * 2093 * dt) + 0.5 * np.sin(2 * np.pi * 3136 * dt)) * np.exp(-dt * 18)
    for k in range(9):
        i = int((m0 + k * 0.11) * SR)
        fx[i:i + dl] += 0.06 * coin
    end = scenes[-1]
    i = int((end["start"] + 0.1) * SR)
    fx[i:i + dl] += 0.12 * coin

    # Duck the bed under the voice.
    vol = np.convolve(np.abs(voice), np.ones(2400) / 2400, mode="same")
    duck = 1 - 0.5 * np.clip(vol / (vol.max() * 0.25 + 1e-9), 0, 1)

    mix = voice * 1.0 + bed * duck + fx
    fade = int(0.8 * SR)
    end_i = int(total * SR)
    mix[end_i - fade:end_i] *= np.linspace(1, 0, fade)
    mix = mix[:end_i]
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


# ---------- background ----------

# (sky value, top colour, horizon colour): dusk -> deep night -> dawn
SKY_KEYS = [
    (-0.2, (70, 30, 100), (150, 60, 70)),
    (0.1, (10, 14, 46), (22, 30, 60)),
    (0.8, (6, 10, 36), (20, 26, 64)),
    (1.0, (90, 120, 200), (255, 150, 80)),
]


def sky_colors(s):
    for (s0, t0, h0), (s1, t1, h1) in zip(SKY_KEYS, SKY_KEYS[1:]):
        if s <= s1:
            p = clamp((s - s0) / (s1 - s0))
            return lerp(t0, t1, p), lerp(h0, h1, p)
    return SKY_KEYS[-1][1:]


def leaf(d, x, y, length, angle, width, fill):
    """Almond-shaped leaf from (x, y) pointing along angle."""
    pts = []
    for k in range(13):
        u = k / 12
        off = math.sin(math.pi * u) * width
        pts.append((u * length, off))
    pts += [(u, -o) for u, o in reversed(pts)]
    ca, sa = math.cos(angle), math.sin(angle)
    d.polygon([(x + u * ca - v * sa, y + u * sa + v * ca) for u, v in pts], fill=fill)


def make_background(s):
    if s in _bg_cache:
        return _bg_cache[s]
    top, hor = sky_colors(s)
    y = np.linspace(0, 1, H)[:, None, None]
    img = np.array(top) + (np.array(hor) - np.array(top)) * np.clip(y * 1.4, 0, 1)
    base = Image.fromarray(np.repeat(img, W, axis=1).astype(np.uint8)).convert("RGBA")
    d = ImageDraw.Draw(base)

    if s < 0.95:  # moon arcs across the sky through the night
        mx, my = 820 - 600 * clamp(s), 330 + 120 * abs(clamp(s) - 0.5)
        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse([mx - 160, my - 160, mx + 160, my + 160], fill=(200, 210, 255, 50))
        base.alpha_composite(glow.filter(ImageFilter.GaussianBlur(50)))
        d.ellipse([mx - 60, my - 60, mx + 60, my + 60], fill=(235, 235, 220))
        d.ellipse([mx - 35, my - 70, mx + 85, my + 50], fill=top)  # bite out a crescent
    else:  # sun peeking over the horizon
        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse([W / 2 - 400, 900, W / 2 + 400, 1700], fill=(255, 200, 120, 120))
        base.alpha_composite(glow.filter(ImageFilter.GaussianBlur(80)))

    rng = random.Random(3)
    dark = lerp((4, 16, 10), (30, 50, 40), clamp((s - 0.8) / 0.2))
    mid = lerp((10, 32, 20), (50, 80, 50), clamp((s - 0.8) / 0.2))
    fol = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    fd = ImageDraw.Draw(fol)
    for _ in range(9):  # distant trunks
        x = rng.uniform(0, W)
        wd = rng.uniform(14, 40)
        fd.rectangle([x, 500, x + wd, H], fill=mid + (150,))
    for _ in range(170):  # canopy and undergrowth hugging the frame edges
        edge = rng.random()
        if edge < 0.3:
            x, y = rng.uniform(-80, 160), rng.uniform(0, H)
            ang = rng.uniform(-0.8, 0.8)
        elif edge < 0.6:
            x, y = rng.uniform(W - 160, W + 80), rng.uniform(0, H)
            ang = math.pi + rng.uniform(-0.8, 0.8)
        elif edge < 0.85:
            x, y = rng.uniform(0, W), rng.uniform(H - 260, H + 40)
            ang = -math.pi / 2 + rng.uniform(-1.1, 1.1)
        else:
            x, y = rng.uniform(0, W), rng.uniform(-60, 120)
            ang = math.pi / 2 + rng.uniform(-1.1, 1.1)
        col = dark if rng.random() < 0.6 else mid
        leaf(fd, x, y, rng.uniform(140, 300), ang, rng.uniform(26, 55), col + (255,))
    base.alpha_composite(fol)
    _bg_cache[s] = base
    return base


def make_spotlight():
    """Oversized darkness mask with a soft torch-beam hole in the middle."""
    sw, sh = W + 400, H + 400
    xv = (np.arange(sw) - sw / 2)[None, :]
    yv = (np.arange(sh) - sh / 2)[:, None]
    r = np.sqrt(xv ** 2 + (yv * 0.9) ** 2)
    a = np.clip((r - 230) / 330, 0, 1) ** 1.2 * 175
    m = np.zeros((sh, sw, 4), np.uint8)
    m[..., 3] = a.astype(np.uint8)
    return Image.fromarray(m, "RGBA")


SPOT = None


def spotlight(img, lt, cx, cy, a):
    if a <= 0:
        return
    sx = cx + math.sin(lt * 1.3) * 25 - (W + 400) / 2
    sy = cy + math.sin(lt * 1.7 + 1) * 15 - (H + 400) / 2
    crop = SPOT.crop((int(-sx), int(-sy), int(-sx) + W, int(-sy) + H))
    flicker = 0.92 + 0.08 * math.sin(lt * 23) * math.sin(lt * 7)
    img.alpha_composite(with_alpha(crop, a * flicker))


random.seed(5)
FIREFLIES = [(random.uniform(0, W), random.uniform(300, H), random.uniform(0, math.tau),
              random.uniform(0.3, 0.9)) for _ in range(28)]
# (x, y, phase) pairs of glowing eyes lurking in the foliage
EYES = [(120, 1340, 0.0), (960, 560, 1.7), (90, 700, 3.1), (990, 1300, 4.4), (180, 1720, 2.2)]


def draw_ambient(img, t, night):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for x0, y0, ph, sp in FIREFLIES:
        x = x0 + math.sin(t * sp + ph) * 60
        y = y0 + math.cos(t * sp * 0.7 + ph) * 40
        glow = max(0.0, math.sin(t * 2 * sp + ph * 3))
        if glow > 0.05:
            r = 5 + 4 * glow
            d.ellipse([x - r * 2.5, y - r * 2.5, x + r * 2.5, y + r * 2.5],
                      fill=(200, 255, 120, int(40 * glow * night)))
            d.ellipse([x - r / 2, y - r / 2, x + r / 2, y + r / 2],
                      fill=(240, 255, 170, int(230 * glow * night)))
    for x, y, ph in EYES:
        cyc = (t * 0.35 + ph / math.tau) % 1
        if cyc < 0.45:
            blink = 1 if (cyc * 40) % 9 > 0.6 else 0.1
            a = int(220 * night * blink * clamp(cyc * 10) * clamp((0.45 - cyc) * 10))
            for dx in (-16, 16):
                d.ellipse([x + dx - 7, y - 5, x + dx + 7, y + 5], fill=(255, 220, 80, a))
    img.alpha_composite(layer)


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


def make_tick(size):
    """There is no tick emoji, so draw a cartoon one in the same style."""
    s = size / 320
    im = Image.new("RGBA", (int(330 * s), int(330 * s)), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx = 165 * s
    leg = (60, 40, 30)
    for k, y in enumerate((125, 150, 175, 200)):
        for side in (-1, 1):
            kx, ky = cx + side * 115 * s, (y - 30 + k * 12) * s
            fx, fy = cx + side * 150 * s, (y + 25 + k * 18) * s
            d.line([(cx, y * s), (kx, ky), (fx, fy)], fill=leg, width=int(12 * s), joint="curve")
    d.ellipse([cx - 22 * s, 30 * s, cx + 22 * s, 80 * s], fill=(90, 50, 40))  # mouthparts
    d.ellipse([cx - 90 * s, 70 * s, cx + 90 * s, 300 * s], fill=(150, 120, 105),
              outline=(70, 45, 35), width=int(8 * s))
    d.ellipse([cx - 60 * s, 70 * s, cx + 60 * s, 160 * s], fill=(80, 50, 40))  # shield
    for gx in (-35, 0, 35):
        d.line([(cx + gx * s, 185 * s), (cx + gx * 0.8 * s, 270 * s)], fill=(120, 95, 80), width=int(5 * s))
    d.ellipse([cx - 30 * s, 92 * s, cx - 10 * s, 108 * s], fill=(255, 255, 255, 120))  # shine
    return im


def emoji_img(ch, size=320):
    key = (ch, size)
    if key not in _emoji_cache:
        if ch == "tick":
            _emoji_cache[key] = make_tick(size)
            return _emoji_cache[key]
        f = font(EMOJI, size)
        probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        x0, y0, x1, y1 = probe.textbbox((0, 0), ch, font=f, embedded_color=True)
        im = Image.new("RGBA", (x1 - x0 + 8, y1 - y0 + 8), (0, 0, 0, 0))
        ImageDraw.Draw(im).text((4 - x0, 4 - y0), ch, font=f, embedded_color=True)
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
    if x >= 0 and y >= 0 and x + im.width <= W and y + im.height <= H:
        layer.alpha_composite(im, (x, y))
    else:
        tmp = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        tmp.paste(im, (x, y))
        layer.alpha_composite(tmp)


def emoji_text(layer, cx, cy, ch, text, f, fill, emoji_px, gap=18, stroke=4):
    """An emoji followed by text, centred together on (cx, cy)."""
    d = ImageDraw.Draw(layer)
    em = emoji_img(ch)
    sc = emoji_px / em.height
    ew = em.width * sc
    tw = d.textlength(text, font=f)
    x = cx - (ew + gap + tw) / 2
    paste_center(layer, em, x + ew / 2, cy, scale=sc)
    d.text((x + ew + gap, cy), text, font=f, fill=fill, anchor="lm", stroke_width=stroke,
           stroke_fill=INK)


def stamp(img, text, cx, cy, lt, start, fill=RED, fg=WHITE, size=96, angle=-8):
    sp = ease_back(prog(lt, start, 0.35))
    if sp <= 0:
        return
    f = font(IMPACT, size)
    tw = ImageDraw.Draw(img).textlength(text, font=f)
    im = Image.new("RGBA", (int(tw + 80), int(size * 1.45)), (0, 0, 0, 0))
    st = ImageDraw.Draw(im)
    rrect(st, [6, 6, im.width - 6, im.height - 6], 24, fill=fill, outline=INK, width=8)
    text_center(st, im.width / 2, im.height / 2, text, f, fg, anchor="mm")
    paste_center(img, im, cx, cy, scale=2.0 - sp, alpha=clamp(sp * 2), angle=angle)


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
    y = 1600 - pop * 20
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x = W / 2 - total / 2
    for w, wd, word in zip(ch, widths, words):
        active = w["start"] - 0.05 <= lt <= w["end"] + 0.12
        d.text((x, y), word, font=f, fill=GOLD if active else WHITE, anchor="lm",
               stroke_width=8, stroke_fill=(0, 0, 0))
        x += wd + space
    img.alpha_composite(with_alpha(layer, clamp(pop * 1.4)))


def progress_bar(img, t, total):
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 10], fill=(255, 255, 255, 40))
    d.rectangle([0, 0, W * t / total, 10], fill=GOLD)


def prize_pill(img, a=1.0):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rrect(d, [290, 40, W - 290, 140], 50, fill=(0, 0, 0, 170), outline=GOLD, width=4)
    emoji_text(layer, W / 2, 90, "💰", "$1,000,000", font(IMPACT, 66), GOLD, 64, stroke=0)
    img.alpha_composite(with_alpha(layer, a))


# ---------- scene visuals ----------

def money_text(lt, start):
    p = ease_out(prog(lt, start, 1.0))
    return f"${int(round(1_000_000 * p, -3 if p < 1 else 0)):,}"


def v_hook(img, scene, lt):
    cues = scene["cue_t"]
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    m0 = max(0.0, cues["money"] - 0.5)
    pulse = 1 + 0.03 * math.sin(lt * 9)
    f = font(IMPACT, int(190 * pulse))
    for dx, dy, col in ((8, 8, (0, 0, 0, 160)), (0, 0, GOLD)):
        text_center(d, W / 2 + dx, 300 + dy, money_text(lt, m0), f, col, stroke=6 if not dx else 0,
                    anchor="mm")
    a = ease_out(prog(lt, cues["money"] + 0.3, 0.35))
    text_center(d, W / 2, 460 + (1 - a) * 30, "TO SPEND ONE NIGHT IN...", font(BOLD, 60),
                (255, 255, 255, int(255 * a)), stroke=5, anchor="mm")
    img.alpha_composite(layer)

    p = ease_back(prog(lt, cues["place"] - 0.05, 0.4))
    if p > 0:
        place = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        pd = ImageDraw.Draw(place)
        text_center(pd, W / 2, 610, "THE", font(IMPACT, 90), WHITE, stroke=5, anchor="mm")
        text_center(pd, W / 2, 760, "DAINTREE", font(IMPACT, 220), JUNGLE, stroke=9, anchor="mm")
        text_center(pd, W / 2, 900, "RAINFOREST, QLD", font(BOLD, 50), WHITE, stroke=5, anchor="mm")
        paste_center(img, place, W / 2, H / 2, scale=1 + 0.6 * (1 - p), alpha=clamp(p * 2))
        for cx, ph in ((W / 2 - 170, 0), (W / 2 + 170, 1.4)):
            paste_center(img, emoji_img("🌴"), cx, 605 + math.sin(lt * 2 + ph) * 8, scale=0.3 * p)

    stamp(img, "ALONE.", W / 2, 1040, lt, cues["alone"], angle=-6)

    q0 = cues["last"]
    if lt > q0 - 0.3:  # six mystery boxes: what's out there?
        box = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        bd = ImageDraw.Draw(box)
        a = ease_out(prog(lt, q0 - 0.3, 0.3))
        text_center(bd, W / 2, 1200, "6 THINGS OUT THERE WANT YOU GONE", font(BOLD, 44), RED,
                    stroke=5, anchor="mm")
        for k in range(6):
            kp = ease_back(prog(lt, q0 - 0.2 + k * 0.08, 0.3))
            cx = W / 2 + (k - 2.5) * 150
            r = 62 * kp
            if r > 1:
                rrect(bd, [cx - r, 1340 - r, cx + r, 1340 + r], 22, fill=(0, 0, 0, 190),
                      outline=(255, 255, 255, 90), width=3)
                text_center(bd, cx, 1340, "?", font(IMPACT, max(1, int(80 * kp))), WHITE, anchor="mm")
        img.alpha_composite(with_alpha(box, a))


RULES = [("tent", "⛺", "ONE TENT"), ("torch", "🔦", "ONE TORCH"),
         ("phone", "📵", "NO PHONE"), ("sunset", "🌅", "SUNSET TO SUNRISE")]


def v_rules(img, scene, lt):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    a = ease_out(prog(lt, 0, 0.35))
    text_center(d, W / 2, 300 - (1 - a) * 40, "THE RULES", font(IMPACT, 160), WHITE, stroke=6,
                anchor="mm")
    bw = d.textlength("THE RULES", font=font(IMPACT, 160)) * ease_out(prog(lt, 0.15, 0.4))
    rrect(d, [W / 2 - bw / 2, 395, W / 2 + bw / 2, 410], 7, fill=GOLD)
    img.alpha_composite(with_alpha(layer, a))
    for k, (cue, ch, text) in enumerate(RULES):
        p = ease_back(prog(lt, scene["cue_t"][cue] - 0.1, 0.4))
        if p <= 0:
            continue
        y = 560 + k * 205
        row = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        rd = ImageDraw.Draw(row)
        rrect(rd, [90, y - 80, W - 90, y + 80], 40, fill=(0, 0, 0, 160), outline=(255, 255, 255, 70),
              width=3)
        paste_center(row, emoji_img(ch), 200, y, scale=0.38)
        f = fit_font(rd, text, IMPACT, 96, W - 420)
        rd.text((300, y), text, font=f, fill=WHITE if k < 3 else GOLD, anchor="lm")
        dx = (1 - p) * (W if k % 2 else -W)
        img.alpha_composite(row, (int(dx), 0)) if dx >= 0 else img.alpha_composite(row.crop((int(-dx), 0, W, H)))


def v_hazard(img, scene, lt, idx, prev_nope):
    rv = scene["cue_t"]["reveal"]
    spotlight(img, lt, W / 2, SPOT_Y, ease_out(prog(lt, 0, 0.4)) * (0.55 if scene["sky"] >= 1 else 1))

    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    # Clock: digits drop in at the start of each scene.
    cp = ease_back(prog(lt, 0.0, 0.45))
    ch = "🌅" if scene["sky"] >= 1 else "🌙"
    emoji_text(layer, W / 2, 255 - (1 - cp) * 60, ch, scene["time"], font(IMPACT, 150), WHITE, 120)
    text_center(d, W / 2, 365, f"HAZARD {idx + 1} / {len(HAZARDS)}", font(BOLD, 40),
                (255, 255, 255, 200), stroke=4, anchor="mm")
    img.alpha_composite(with_alpha(layer, ease_out(prog(lt, 0, 0.25))))

    if lt < rv:  # something's out there: eyes and a question mark in the beam
        pulse = 1 + 0.06 * math.sin(lt * 6)
        mys = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        md = ImageDraw.Draw(mys)
        text_center(md, W / 2, SPOT_Y, "?", font(IMPACT, int(300 * pulse)), (255, 255, 255, 50),
                    anchor="mm")
        blink = 0.1 if (lt * 1.3) % 1 > 0.92 else 1
        for dx in (-45, 45):
            md.ellipse([W / 2 + dx - 18, SPOT_Y - 150 - 12, W / 2 + dx + 18, SPOT_Y - 150 + 12],
                       fill=(255, 210, 60, int(230 * blink)))
        img.alpha_composite(mys)
    else:
        p = ease_back(prog(lt, rv, 0.4))
        bob = math.sin(lt * 2.4) * 10
        paste_center(img, emoji_img(scene["emoji"]), W / 2, SPOT_Y + bob,
                     scale=1.2 * (2.0 - p), alpha=clamp(p * 3), angle=(1 - p) * 20)

        info = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        idr = ImageDraw.Draw(info)
        ta = ease_out(prog(lt, rv + 0.15, 0.3))
        nf = fit_font(idr, scene["name"], IMPACT, 110, W - 120)
        text_center(idr, W / 2, 1030 + (1 - ta) * 30, scene["name"], nf, GOLD, stroke=6, anchor="mm")
        stats = "  •  ".join(scene["stats"])
        text_center(idr, W / 2, 1120, stats, fit_font(idr, stats, BOLD, 46, W - 120), WHITE,
                    stroke=5, anchor="mm")
        img.alpha_composite(with_alpha(info, ta))

        # Danger skulls light up one by one.
        skulls = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(skulls)
        sd.text((W / 2 - 330, 1215), "DANGER", font=font(IMPACT, 54), fill=WHITE, anchor="lm",
                stroke_width=4, stroke_fill=INK)
        for k in range(5):
            on = k < scene["danger"] and lt > rv + 0.35 + k * 0.1
            paste_center(skulls, emoji_img("💀"), W / 2 - 60 + k * 85, 1215, scale=0.22,
                         alpha=1.0 if on else 0.25)
        img.alpha_composite(with_alpha(skulls, ta))

    nope_meter(img, lt, rv, prev_nope, scene["nope"])
    if scene.get("note") and lt > rv + 0.6:
        a = ease_out(prog(lt, rv + 0.6, 0.4))
        note = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        text_center(ImageDraw.Draw(note), W / 2, 1490, scene["note"], font(SEMI, 36),
                    (255, 255, 255, 210), stroke=3, anchor="mm")
        img.alpha_composite(with_alpha(note, a))


def nope_meter(img, lt, rv, prev, nope):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x0, x1, y = 90, W - 90, 1370
    fill = prev + (nope - prev) * ease_out(prog(lt, rv + 0.2, 0.7))
    full = fill >= 0.999
    d.text((x0, y - 50), "NOPE-O-METER", font=font(IMPACT, 50), fill=WHITE, anchor="lm",
           stroke_width=4, stroke_fill=INK)
    label = "FULL NOPE" if full else f"{int(fill * 100)}%"
    pulse = 1 + (0.12 * abs(math.sin(lt * 8)) if full else 0)
    d.text((x1, y - 50), label, font=font(IMPACT, int(50 * pulse)), fill=RED if fill > 0.6 else GOLD,
           anchor="rm", stroke_width=4, stroke_fill=INK)
    rrect(d, [x0, y, x1, y + 56], 28, fill=(0, 0, 0, 170), outline=(255, 255, 255, 80), width=3)
    col = lerp(GOLD, RED, clamp((fill - 0.3) / 0.6))
    rrect(d, [x0 + 6, y + 6, x0 + 6 + max(44, (x1 - x0 - 12) * fill), y + 50], 22, fill=col)
    img.alpha_composite(layer)


def v_end(img, scene, lt):
    cues = scene["cue_t"]
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    # What you'd be sharing the night with.
    for k, hz in enumerate(HAZARDS):
        p = ease_back(prog(lt, 0.1 + k * 0.1, 0.35))
        cx = W / 2 + (k - 2.5) * 155
        paste_center(layer, emoji_img(hz["emoji"]), cx, 330 + math.sin(lt * 3 + k) * 10,
                     scale=0.36 * max(0.0, p), alpha=clamp(p * 2))
    text_center(d, W / 2, 470, "ONE NIGHT. ALL OF THEM.", font(BOLD, 50),
                (255, 255, 255, int(255 * ease_out(prog(lt, 0.6, 0.3)))), stroke=5, anchor="mm")
    text_center(d, W / 2, 590, "$1,000,000", font(IMPACT, 150), GOLD, stroke=6, anchor="mm")
    img.alpha_composite(with_alpha(layer, ease_out(prog(lt, 0, 0.3))))

    q = ease_back(prog(lt, cues["ask"] - 0.1, 0.4))
    if q > 0:
        ask = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ad = ImageDraw.Draw(ask)
        for k, ln in enumerate(("WOULD YOU", "DO IT?")):
            text_center(ad, W / 2 + 7, 790 + k * 150 + 7, ln, font(IMPACT, 165), (0, 0, 0, 150),
                        anchor="mm")
            text_center(ad, W / 2, 790 + k * 150, ln, font(IMPACT, 165), WHITE, stroke=6, anchor="mm")
        paste_center(img, ask, W / 2, H / 2, scale=1 + 0.4 * (1 - q), alpha=clamp(q * 2))

        # YES / NO buttons take turns pulsing.
        for k, (label, ch, col, fg) in enumerate((("YES", "💰", GOLD, INK), ("NO", "🏃", RED, WHITE))):
            bp = ease_back(prog(lt, cues["ask"] + 0.3 + k * 0.15, 0.35))
            if bp <= 0:
                continue
            beat = 1 + 0.07 * max(0.0, math.sin(lt * 5 + k * math.pi))
            btn = Image.new("RGBA", (420, 190), (0, 0, 0, 0))
            bd = ImageDraw.Draw(btn)
            rrect(bd, [8, 8, 412, 182], 60, fill=col, outline=INK, width=8)
            paste_center(btn, emoji_img(ch), 115, 95, scale=0.36)
            bd.text((205, 95), label, font=font(IMPACT, 110), fill=fg, anchor="lm")
            paste_center(img, btn, W / 2 + (k * 2 - 1) * 245, 1160, scale=bp * beat)

    c0 = cues["comment"] - 0.1
    if lt > c0:
        a = ease_back(prog(lt, c0, 0.45))
        bar = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        bd = ImageDraw.Draw(bar)
        rrect(bd, [110, 1340, W - 110, 1460], 60, fill=(255, 255, 255, 235))
        emoji_text(bar, W / 2, 1400, "💬", "COMMENT BELOW", font(IMPACT, 80), INK, 76, stroke=0)
        paste_center(img, bar, W / 2, H / 2 + (1 - a) * 60, alpha=clamp(a * 2))
        bounce = abs(math.sin(lt * 5)) * 26
        paste_center(img, emoji_img("👇"), W - 150, 1500 + bounce, scale=0.3 * a)
        paste_center(img, emoji_img("👇"), 150, 1500 + bounce, scale=0.3 * a)


def shake_offset(t, revs):
    since = min((t - rt for rt in revs if t >= rt), default=9)
    if since > 0.35:
        return 0, 0
    amp = 22 * (1 - since / 0.35)
    rng = random.Random(int(t * FPS))
    return int(rng.uniform(-amp, amp)), int(rng.uniform(-amp, amp))


def render_frame(scenes, revs, total, t):
    scene = next(s for s in reversed(scenes) if t >= s["start"])
    lt = t - scene["start"]
    sky = scene.get("sky", -0.2)
    img = make_background(sky).copy()
    draw_ambient(img, t, 1.0 if sky < 1 else 0.3)
    hz = [s for s in scenes if "cue" in s]
    if scene["id"] == "hook":
        v_hook(img, scene, lt)
    elif scene["id"] == "rules":
        v_rules(img, scene, lt)
    elif scene["id"] == "end":
        v_end(img, scene, lt)
    else:
        idx = hz.index(scene)
        prev = hz[idx - 1]["nope"] if idx else 0.0
        v_hazard(img, scene, lt, idx, prev)
        prize_pill(img)
    captions(img, scene, lt)
    progress_bar(img, t, total)

    # quick flash on scene change and on every hazard
    flash_at = [scene["start"]] if scene is not scenes[0] else []
    flash_at += revs
    since = min((t - ft for ft in flash_at if t >= ft), default=9)
    if since < 0.12:
        img.alpha_composite(Image.new("RGBA", (W, H), (255, 255, 255, int(130 * (1 - since / 0.12)))))
    dx, dy = shake_offset(t, revs)
    if dx or dy:
        moved = Image.new("RGBA", (W, H), INK + (255,))
        moved.paste(img, (dx, dy))
        img = moved
    return img.convert("RGB")


def main():
    global SPOT
    scenes, total = load_timeline()
    revs = reveals(scenes)
    SPOT = make_spotlight()
    OUT.mkdir(parents=True, exist_ok=True)

    if "--preview" in sys.argv:
        times = [float(x) for x in sys.argv[sys.argv.index("--preview") + 1:]]
        for t in times:
            render_frame(scenes, revs, total, t).save(OUT / f"preview_{t:05.1f}.png")
        print("scene starts:", [(s["id"], round(s["start"], 2)) for s in scenes], "total", round(total, 2))
        print("reveals:", [round(rt, 2) for rt in revs])
        return

    audio = build_audio(scenes, total)
    out = OUT / "one_million_one_night_daintree.mp4"
    ff = subprocess.Popen([
        "ffmpeg", "-y", "-v", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
        "-i", str(audio),
        "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out),
    ], stdin=subprocess.PIPE)
    frames = int(total * FPS)
    for i in range(frames):
        ff.stdin.write(render_frame(scenes, revs, total, i / FPS).tobytes())
        if i % 150 == 0:
            print(f"frame {i}/{frames}", file=sys.stderr)
    ff.stdin.close()
    ff.wait()
    print(out)


if __name__ == "__main__":
    main()
