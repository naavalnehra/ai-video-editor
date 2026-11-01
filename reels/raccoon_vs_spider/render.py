"""Render the 'Your raccoon vs our spider' reel (1080x1920, 30fps).

USA (left) vs Australia (right), side by side, five rounds and a winner.
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
OUT = ROOT / "output" / "raccoon_vs_spider"
VO = OUT / "vo"

W, H, FPS = 1080, 1920, 30
SR = 48000
PAD = 0.35  # silence after each scene's line

FONTS = Path("C:/Windows/Fonts")
IMPACT = str(FONTS / "impact.ttf")
BOLD = str(FONTS / "seguibl.ttf")
SEMI = str(FONTS / "segoeuib.ttf")
EMOJI = str(FONTS / "seguiemj.ttf")

USA_BLUE = (52, 92, 210)
USA_RED = (226, 56, 70)
AUS_GREEN = (0, 150, 70)
AUS_GOLD = (255, 205, 0)
NAVY = (12, 30, 90)
WHITE = (255, 255, 255)
INK = (14, 18, 40)
GREY = (150, 150, 165)

SIDE_COL = {"usa": USA_BLUE, "aus": AUS_GREEN}
SIDE_ACCENT = {"usa": USA_RED, "aus": AUS_GOLD}
SIDE_LABEL = {"usa": "USA", "aus": "AUS"}

# panel geometry: two columns with a gutter
PX = {"usa": (40, 520), "aus": (560, 1040)}
PY0, PY1 = 420, 1370
EMOJI_Y = 700

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


def prog(t, start, dur):
    return clamp((t - start) / dur)


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
        if s["id"] == "winner":
            cues["follow"] = cue_time(words, "follow")
        scenes.append({**s, "start": t, "dur": dur, "audio": audio, "words": words, "cue_t": cues})
        t += dur
    return scenes, t


def decode(path):
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
        check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def reveals(scenes):
    """Absolute (time, winner) for every round, used for the running score."""
    return [(s["start"] + s["cue_t"]["reveal"], s["winner"]) for s in scenes if "winner" in s]


def score_at(revs, t):
    sc = {"usa": 0, "aus": 0}
    for rt, side in revs:
        if t >= rt:
            sc[side] += 1
    return sc


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

    rng = np.random.default_rng(11)
    tt = np.arange(n) / SR

    # Sports-broadcast beat: kick on every beat, hat on the off-beats, 120 bpm.
    beat = np.zeros(n, np.float32)
    kl = int(0.28 * SR)
    kt = np.arange(kl) / SR
    kick = np.sin(2 * np.pi * np.cumsum(45 + 90 * np.exp(-kt * 30)) / SR) * np.exp(-kt * 12)
    hl = int(0.06 * SR)
    hat = rng.standard_normal(hl) * np.exp(-np.arange(hl) / SR * 70)
    hat = np.diff(hat, prepend=0)  # crude high-pass
    for k in range(int(total * 2)):
        i = int(k * 0.5 * SR)
        beat[i:i + kl] += 0.16 * kick[:max(0, min(kl, n - i))]
        j = i + int(0.25 * SR)
        beat[j:j + hl] += 0.05 * hat[:max(0, min(hl, n - j))]

    fx = np.zeros(n, np.float32)
    # Whoosh on each scene change.
    wl = int(0.45 * SR)
    env = np.sin(np.linspace(0, np.pi, wl)) ** 2
    for s in scenes[1:]:
        noise = np.convolve(rng.standard_normal(wl), np.ones(6) / 6, mode="same")
        i = max(0, int((s["start"] - 0.2) * SR))
        fx[i:i + wl] += 0.16 * noise * env
    # Impact + two-note "ding" on every point.
    il = int(0.7 * SR)
    it = np.arange(il) / SR
    boom = np.sin(2 * np.pi * np.cumsum(38 + 80 * np.exp(-it * 18)) / SR) * np.exp(-it * 5)
    boom += 0.25 * rng.standard_normal(il) * np.exp(-it * 25)
    ding = np.zeros(il)
    for f0, off in ((988, 0.0), (1480, 0.09)):
        o = int(off * SR)
        ding[o:] += np.sin(2 * np.pi * f0 * it[:il - o]) * np.exp(-it[:il - o] * 7)
    for rt, _ in reveals(scenes):
        i = int(rt * SR)
        fx[i:i + il] += (0.45 * boom + 0.09 * ding)[:max(0, min(il, n - i))]

    # Duck the beat under the voice.
    vol = np.convolve(np.abs(voice), np.ones(2400) / 2400, mode="same")
    duck = 1 - 0.55 * np.clip(vol / (vol.max() * 0.25 + 1e-9), 0, 1)

    mix = voice * 1.0 + beat * duck + fx
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

def make_background():
    """Blue (USA) on the left, green (AUS) on the right, split on a slant."""
    y = np.linspace(0, 1, H)[:, None, None]
    left = np.array([14, 26, 78]) + (np.array([34, 18, 60]) - np.array([14, 26, 78])) * y
    right = np.array([6, 60, 40]) + (np.array([30, 48, 20]) - np.array([6, 60, 40])) * y
    xx = np.arange(W)[None, :]
    yy = np.arange(H)[:, None]
    split = W / 2 + (yy - H / 2) * -0.08
    m = np.clip((xx - split) / 6 + 0.5, 0, 1)[..., None]
    img = left * (1 - m) + right * m
    xv = np.linspace(-1, 1, W)[None, :]
    yv = np.linspace(-1, 1, H)[:, None]
    img *= (1 - 0.35 * np.clip(xv ** 2 + yv ** 2 * 0.6, 0, 1))[..., None]
    return Image.fromarray(img.astype(np.uint8)).convert("RGBA")


random.seed(5)
SPECKS = [(random.uniform(0, W), random.uniform(0, H), random.uniform(2, 6), random.uniform(10, 40))
          for _ in range(60)]


def draw_specks(img, t):
    d = ImageDraw.Draw(img)
    for x, y0, r, speed in SPECKS:
        y = (y0 - t * speed) % H
        d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, 22))


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


def emoji_img(ch, size=320, mirror=False):
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
    if x >= 0 and y >= 0 and x + im.width <= W and y + im.height <= H:
        layer.alpha_composite(im, (x, y))
    else:
        tmp = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        tmp.paste(im, (x, y))
        layer.alpha_composite(tmp)


def draw_flag(d, side, x, y, w):
    """Simplified flags: stripes + canton for the USA, Union Jack + stars for Australia."""
    h = w * 0.55
    if side == "usa":
        for k in range(13):
            d.rectangle([x, y + h * k / 13, x + w, y + h * (k + 1) / 13],
                        fill=USA_RED if k % 2 == 0 else WHITE)
        cw, ch = w * 0.42, h * 7 / 13
        d.rectangle([x, y, x + cw, y + ch], fill=NAVY)
        for r in range(4):
            for c in range(5):
                sx, sy = x + cw * (c + 0.5 + (r % 2) * 0.25) / 5.3, y + ch * (r + 0.6) / 4.3
                d.ellipse([sx - 2, sy - 2, sx + 2, sy + 2], fill=WHITE)
    else:
        d.rectangle([x, y, x + w, y + h], fill=NAVY)
        cw, ch = w / 2, h / 2
        lw = max(2, int(w * 0.05))
        d.line([x, y, x + cw, y + ch], fill=WHITE, width=lw + 3)
        d.line([x + cw, y, x, y + ch], fill=WHITE, width=lw + 3)
        d.line([x, y, x + cw, y + ch], fill=USA_RED, width=max(1, lw - 2))
        d.line([x + cw, y, x, y + ch], fill=USA_RED, width=max(1, lw - 2))
        d.rectangle([x + cw / 2 - lw, y, x + cw / 2 + lw, y + ch], fill=WHITE)
        d.rectangle([x, y + ch / 2 - lw, x + cw, y + ch / 2 + lw], fill=WHITE)
        d.rectangle([x + cw / 2 - lw / 2, y, x + cw / 2 + lw / 2, y + ch], fill=USA_RED)
        d.rectangle([x, y + ch / 2 - lw / 2, x + cw, y + ch / 2 + lw / 2], fill=USA_RED)
        for sx, sy, r in ((0.25, 0.77, 0.09), (0.75, 0.2, 0.05), (0.62, 0.48, 0.05),
                          (0.75, 0.82, 0.05), (0.87, 0.42, 0.05), (0.81, 0.58, 0.03)):
            star(d, x + w * sx, y + h * sy, h * r, WHITE)


def star(d, cx, cy, r, fill, points=7):
    pts = []
    for k in range(points * 2):
        rr = r if k % 2 == 0 else r * 0.45
        a = -math.pi / 2 + k * math.pi / points
        pts.append((cx + math.cos(a) * rr, cy + math.sin(a) * rr))
    d.polygon(pts, fill=fill)


def headline(img, scene, lt):
    p = ease_out(prog(lt, 0.0, 0.4))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    lines = scene["headline"].split("\n")
    size = 150 if len(lines) > 1 else 120
    f = font(IMPACT, size)
    y = (240 if len(lines) > 1 else 205) + (1 - p) * 80
    for ln in lines:
        text_center(d, W / 2 + 6, y + 6, ln, f, (0, 0, 0, 140))
        text_center(d, W / 2, y, ln, f, WHITE)
        y += size * 1.02
    if len(lines) == 1:
        bw = d.textlength(lines[0], font=f) * ease_out(prog(lt, 0.2, 0.4))
        rrect(d, [W / 2 - bw / 2, y + 8, W / 2 + bw / 2, y + 20], 6, fill=AUS_GOLD)
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
    y = 1580 - pop * 20
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x = W / 2 - total / 2
    for w, wd, word in zip(ch, widths, words):
        active = w["start"] - 0.05 <= lt <= w["end"] + 0.12
        d.text((x, y), word, font=f, fill=AUS_GOLD if active else WHITE, anchor="lm",
               stroke_width=8, stroke_fill=(0, 0, 0))
        x += wd + space
    img.alpha_composite(with_alpha(layer, clamp(pop * 1.4)))


def progress_bar(img, t, total):
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 10], fill=(255, 255, 255, 40))
    d.rectangle([0, 0, W * t / total, 10], fill=AUS_GOLD)


def scoreboard(img, revs, t, a):
    if a <= 0:
        return
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    sc = score_at(revs, t)
    rrect(d, [150, 40, W - 150, 150], 55, fill=(0, 0, 0, 170), outline=(255, 255, 255, 60), width=3)
    draw_flag(d, "usa", 195, 72, 84)
    draw_flag(d, "aus", W - 195 - 84, 72, 84)
    d.text((300, 95), "USA", font=font(IMPACT, 60), fill=WHITE, anchor="lm")
    d.text((W - 300, 95), "AUS", font=font(IMPACT, 60), fill=WHITE, anchor="rm")
    text_center(d, W / 2, 95, "–", font(IMPACT, 60), GREY, anchor="mm")
    for side, cx in (("usa", W / 2 - 75), ("aus", W / 2 + 75)):
        last = max((rt for rt, s in revs if s == side and rt <= t), default=-9)
        pop = 1 + 0.6 * (1 - ease_out(prog(t, last, 0.5)))
        col = AUS_GOLD if t - last < 0.8 else WHITE
        text_center(d, cx, 95, str(sc[side]), font(IMPACT, int(72 * pop)), col, stroke=3,
                    anchor="mm")
    img.alpha_composite(with_alpha(layer, a))


# ---------- scene visuals ----------

def draw_panel(img, scene, side, lt):
    x0, x1 = PX[side]
    cx = (x0 + x1) / 2
    data = scene[side]
    enter = scene["cue_t"][side] - 0.15
    reveal = scene["cue_t"]["reveal"]
    won = scene["winner"] == side

    frame_a = ease_out(prog(lt, 0.0, 0.3))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rp = ease_back(prog(lt, reveal, 0.45))
    lift = -16 * rp if won else 0
    col = SIDE_COL[side]
    outline = AUS_GOLD if won and lt >= reveal else (255, 255, 255, 70)
    if won and lt >= reveal:  # gold glow behind the winning panel
        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        rrect(ImageDraw.Draw(glow), [x0 - 10, PY0 - 10 + lift, x1 + 10, PY1 + 10 + lift], 50,
              outline=AUS_GOLD + (int(200 * clamp(rp)),), width=24)
        img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(22)))
    rrect(d, [x0, PY0 + lift, x1, PY1 + lift], 40, fill=col + (110,), outline=outline,
          width=8 if won and lt >= reveal else 3)
    draw_flag(d, side, x0 + 30, PY0 + 28 + lift, 80)
    d.text((x0 + 128, PY0 + 50 + lift), SIDE_LABEL[side], font=font(IMPACT, 54), fill=WHITE,
           anchor="lm")

    p = ease_back(prog(lt, enter, 0.45))
    if lt < enter:  # mystery placeholder until the narrator names it
        pulse = 1 + 0.05 * math.sin(lt * 6)
        text_center(d, cx, EMOJI_Y + lift, "?", font(IMPACT, int(220 * pulse)), (255, 255, 255, 60),
                    anchor="mm")
    else:
        bob = math.sin(lt * 2.4 + (0 if side == "usa" else 1.5)) * 8
        dx = (1 - p) * (-260 if side == "usa" else 260)
        r = 150 * max(0.0, p)
        d.ellipse([cx + dx - r, EMOJI_Y + lift - r, cx + dx + r, EMOJI_Y + lift + r],
                  fill=(255, 255, 255, 45))
        paste_center(layer, emoji_img(data["emoji"], mirror=side == "aus"), cx + dx,
                     EMOJI_Y + bob + lift, scale=0.85 * max(0.0, p), alpha=clamp(p * 2))
        ta = ease_out(prog(lt, enter + 0.25, 0.35))
        sub = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(sub)
        nf = fit_font(sd, data["name"], IMPACT, 68, x1 - x0 - 40)
        text_center(sd, cx, 890 + lift, data["name"], nf, SIDE_ACCENT[side] if side == "aus" else WHITE,
                    stroke=3, anchor="mm")
        for i, st in enumerate(data["stats"]):
            sf = fit_font(sd, st, BOLD, 38, x1 - x0 - 50)
            text_center(sd, cx, 975 + i * 58 + lift, st, sf, WHITE, anchor="mm")
        sd.text((x0 + 30, 1135 + lift), "THREAT", font=font(BOLD, 30), fill=(255, 255, 255, 180),
                anchor="lm")
        bx0, bx1, by = x0 + 30, x1 - 30, 1175 + lift
        rrect(sd, [bx0, by, bx1, by + 44], 22, fill=(0, 0, 0, 120))
        fill = data["threat"] * ease_out(prog(lt, enter + 0.4, 0.9))
        bar_col = USA_RED if data["threat"] > 0.75 else AUS_GOLD
        rrect(sd, [bx0, by, bx0 + max(44, (bx1 - bx0) * fill), by + 44], 22, fill=bar_col)
        layer.alpha_composite(with_alpha(sub, ta))

    if lt >= reveal and not won:  # dim the loser
        dim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        rrect(ImageDraw.Draw(dim), [x0, PY0, x1, PY1], 40,
              fill=(0, 0, 0, int(140 * ease_out(prog(lt, reveal, 0.3)))))
        layer.alpha_composite(dim)
    img.alpha_composite(with_alpha(layer, frame_a))

    if lt >= reveal and won:  # rotated WINNER stamp
        sp = ease_back(prog(lt, reveal, 0.35))
        stamp = Image.new("RGBA", (420, 140), (0, 0, 0, 0))
        st = ImageDraw.Draw(stamp)
        rrect(st, [6, 6, 414, 134], 26, fill=AUS_GOLD, outline=INK, width=8)
        text_center(st, 210, 70, "POINT!", font(IMPACT, 92), INK, anchor="mm")
        paste_center(img, stamp, cx, 1290 + lift, scale=0.9 * (2.2 - 1.2 * sp), alpha=clamp(sp * 2),
                     angle=8 if side == "usa" else -8)


def vs_badge(img, lt, y=EMOJI_Y, start=0.15):
    p = ease_back(prog(lt, start, 0.4))
    if p <= 0:
        return
    pulse = 1 + 0.06 * math.sin(lt * 7)
    r = 78 * p * pulse
    d = ImageDraw.Draw(img)
    d.ellipse([W / 2 - r - 8, y - r - 8, W / 2 + r + 8, y + r + 8], fill=INK)
    d.ellipse([W / 2 - r, y - r, W / 2 + r, y + r], fill=USA_RED, outline=AUS_GOLD, width=6)
    text_center(d, W / 2, y, "VS", font(IMPACT, int(82 * p * pulse) + 1), WHITE, anchor="mm")


def v_round(img, scene, lt):
    for side in ("usa", "aus"):
        draw_panel(img, scene, side, lt)
    if lt < scene["cue_t"]["reveal"] + 0.2:
        vs_badge(img, lt)
    if scene.get("note") and lt > scene["cue_t"]["reveal"] + 0.3:
        a = ease_out(prog(lt, scene["cue_t"]["reveal"] + 0.3, 0.4))
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        text_center(ImageDraw.Draw(layer), W / 2, 1420, scene["note"], font(SEMI, 34),
                    (255, 255, 255, 200))
        img.alpha_composite(with_alpha(layer, a))


def v_hook(img, scene, lt):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    y = 1080
    for side, cx, ch, t0 in (("usa", 270, "🦝", 0.2), ("aus", W - 270, "🕷", 0.55)):
        p = ease_back(prog(lt, t0, 0.5))
        dx = (1 - p) * (-500 if side == "usa" else 500)
        bob = math.sin(lt * 2.6 + t0 * 4) * 10
        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse([cx + dx - 220, y - 220, cx + dx + 220, y + 220],
                                     fill=(255, 255, 255, 70))
        layer.alpha_composite(glow.filter(ImageFilter.GaussianBlur(40)))
        paste_center(layer, emoji_img(ch, mirror=side == "aus"), cx + dx, y + bob, scale=1.05,
                     alpha=clamp(p * 2))
        if p > 0:
            draw_flag(d, side, cx + dx - 70, y + 220, 140)
            text_center(d, cx + dx, y + 320, "AMERICA" if side == "usa" else "AUSTRALIA",
                        font(IMPACT, 64), WHITE, stroke=3)
    img.alpha_composite(layer)
    vs_badge(img, lt, y=y, start=0.9)


random.seed(9)
CONFETTI = [(random.uniform(0, W), random.uniform(-H, 0), random.uniform(160, 420),
             random.uniform(0, math.tau), random.choice([AUS_GREEN, AUS_GOLD, WHITE, (0, 200, 110)]))
            for _ in range(140)]


def v_winner(img, scene, lt):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    # green-and-gold sunburst
    rays = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    rd = ImageDraw.Draw(rays)
    a0 = lt * 0.4
    for k in range(16):
        a = a0 + k * math.tau / 16
        rd.polygon([(W / 2, 930), (W / 2 + math.cos(a) * 1400, 930 + math.sin(a) * 1400),
                    (W / 2 + math.cos(a + 0.18) * 1400, 930 + math.sin(a + 0.18) * 1400)],
                   fill=(AUS_GOLD if k % 2 else AUS_GREEN) + (40,))
    img.alpha_composite(with_alpha(rays, ease_out(prog(lt, 0.0, 0.6))))

    p = ease_back(prog(lt, 0.15, 0.6))
    bounce = abs(math.sin(lt * 3)) * -22
    paste_center(layer, emoji_img("🏆"), W / 2, 900 + bounce, scale=0.95 * max(0.0, p),
                 alpha=clamp(p * 2))
    for side, cx, ch in (("aus", W / 2 - 300, "🦘"), ("aus", W / 2 + 300, "🐊")):
        q = ease_back(prog(lt, 0.6, 0.5))
        paste_center(layer, emoji_img(ch, mirror=cx > W / 2), cx, 990 + math.sin(lt * 4 + cx) * 12,
                     scale=0.5 * max(0.0, q), alpha=clamp(q * 2))

    sp = ease_back(prog(lt, 0.5, 0.5))
    if sp > 0:
        rrect(d, [200, 1150, W - 200, 1300], 60, fill=(0, 0, 0, 170), outline=AUS_GOLD, width=5)
        draw_flag(d, "usa", 240, 1197, 100)
        draw_flag(d, "aus", W - 340, 1197, 100)
        text_center(d, W / 2 - 80, 1225, "2", font(IMPACT, int(110 * sp) + 1), GREY, anchor="mm")
        text_center(d, W / 2, 1225, "–", font(IMPACT, 90), GREY, anchor="mm")
        text_center(d, W / 2 + 80, 1225, "3", font(IMPACT, int(110 * sp) + 1), AUS_GOLD, anchor="mm")

    ft = scene["cue_t"]["follow"] - 0.1
    if lt > ft:
        a = ease_back(prog(lt, ft, 0.5))
        pulse = 1 + 0.04 * math.sin(lt * 8)
        rrect(d, [150, 1390 - 60 * a, W - 150, 1390 + 60 * a], 60, fill=AUS_GOLD)
        text_center(d, W / 2, 1390, "FOLLOW FOR ROUND 2", font(IMPACT, int(72 * a * pulse) + 1), INK,
                    anchor="mm")
    img.alpha_composite(layer)

    conf = ImageDraw.Draw(img)
    for x0, y0, speed, ph, col in CONFETTI:
        y = y0 + lt * speed
        if 0 <= y <= H:
            x = x0 + math.sin(lt * 2 + ph) * 40
            s = 9 + 6 * abs(math.sin(lt * 5 + ph))
            conf.rectangle([x - 9, y - s / 2, x + 9, y + s / 2], fill=col)


def render_frame(bg, scenes, revs, total, t):
    img = bg.copy()
    draw_specks(img, t)
    scene = next(s for s in reversed(scenes) if t >= s["start"])
    lt = t - scene["start"]
    if scene["id"] == "hook":
        v_hook(img, scene, lt)
    elif scene["id"] == "winner":
        v_winner(img, scene, lt)
    else:
        v_round(img, scene, lt)
    if scene["id"] != "hook":
        scoreboard(img, revs, t, 1.0 if scene is not scenes[1] else ease_out(prog(lt, 0, 0.4)))
    headline(img, scene, lt)
    captions(img, scene, lt)
    progress_bar(img, t, total)
    # quick flash on scene change and on every point
    flash_at = [scene["start"]] if scene is not scenes[0] else []
    flash_at += [rt for rt, _ in revs]
    since = min((t - ft for ft in flash_at if t >= ft), default=9)
    if since < 0.12:
        img.alpha_composite(Image.new("RGBA", (W, H), (255, 255, 255, int(120 * (1 - since / 0.12)))))
    return img.convert("RGB")


def main():
    scenes, total = load_timeline()
    revs = reveals(scenes)
    bg = make_background()
    OUT.mkdir(parents=True, exist_ok=True)

    if "--preview" in sys.argv:
        times = [float(x) for x in sys.argv[sys.argv.index("--preview") + 1:]]
        for t in times:
            render_frame(bg, scenes, revs, total, t).save(OUT / f"preview_{t:05.1f}.png")
        print("scene starts:", [(s["id"], round(s["start"], 2)) for s in scenes], "total", round(total, 2))
        print("reveals:", [(round(rt, 2), w) for rt, w in revs])
        return

    audio = build_audio(scenes, total)
    out = OUT / "your_raccoon_vs_our_spider.mp4"
    ff = subprocess.Popen([
        "ffmpeg", "-y", "-v", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
        "-i", str(audio),
        "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out),
    ], stdin=subprocess.PIPE)
    frames = int(total * FPS)
    for i in range(frames):
        ff.stdin.write(render_frame(bg, scenes, revs, total, i / FPS).tobytes())
        if i % 150 == 0:
            print(f"frame {i}/{frames}", file=sys.stderr)
    ff.stdin.close()
    ff.wait()
    print(out)


if __name__ == "__main__":
    main()
