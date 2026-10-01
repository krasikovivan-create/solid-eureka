#!/usr/bin/env python3
"""Оживление фото: «живая» 2.5D-анимация коридора музея.

    python animate.py                    # берёт photo.jpeg из текущей папки
    python animate.py путь/к/фото.jpg    # любое другое фото
    python animate.py --no-open          # не открывать видео в конце

Пайплайн: апскейл x2 (Real-ESRGAN) -> маска человека (rembg) -> заливка фона
за человеком (cv2.inpaint) -> карта глубины (Depth Anything V2 Small) ->
анимация (наезд + параллакс, человек — неподвижный слой, световое пятно,
каустика на полу, вода в аквариуме, пылинки) -> MP4 / MP4 9:16 / GIF.
"""

# ============================ НАСТРОЙКИ ============================
INPUT = "photo.jpeg"
OUTPUT_DIR = "output"

DURATION = 7.0            # секунды (цикл бесшовный: последний кадр переходит в первый)
FPS = 30
UPSCALE = 2               # апскейл исходника
ESRGAN_BLEND = 0.85       # доля Real-ESRGAN в апскейле (остальное — Lanczos, для естественной текстуры)
MAX_PIXELS = 1080 * 1920  # предел рабочего разрешения (H.264 level 4.x — открывается на любом телефоне)

# Камера. Человек всегда неподвижен и не деформируется; двигается только фон.
ZOOM = 0.08               # сила «наезда»: ближние к камере части фона приближаются, дальние слегка уходят
PARALLAX = 0.016          # сила бокового параллакса по глубине (доля ширины кадра)
SWAY_Y = 0.35             # вертикальная составляющая покачивания (доля от горизонтальной)
PERSON_FOLLOW_ZOOM = 0.0  # 0 = человек полностью неподвижен; 1 = масштабируется вместе с «камерой»

# Эффекты (0 = выключить)
LIGHT_PULSE = 0.35        # пульсация розово-фиолетового пятна у надписи
CAUSTICS = 0.18           # водные блики на полу
CAUSTIC_SCALE = 2.5       # мельче/крупнее узор бликов (больше = мельче)
WATER_SHIMMER = 0.45      # мерцание воды в окне-аквариуме
DUST_COUNT = 18           # количество пылинок
DUST_BRIGHTNESS = 0.85    # яркость пылинок

# Маска человека: пробуются все модели, берётся та, чей контур лучше совпадает со скачком глубины
MASK_MODELS = ("isnet-general-use", "u2net_human_seg", "birefnet-portrait")
MASK_FEATHER = 2.0        # мягкость края маски, px (в рабочем разрешении)
PERSON_RING = 1           # px исходного фона вокруг человека в его слое (прячет шов)
HOLE_EXTRA = 10           # с какого отступа от маски берутся пиксели для заливки фона, px

GIF_WIDTH = 240           # ширина превью-GIF
GIF_FPS = 12
SAVE_DEBUG = True         # сохранять промежуточные карты в output/debug
# ===================================================================

import argparse
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import warnings

import cv2
import numpy as np
from PIL import Image, ImageOps

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(HERE, "models")
ESRGAN_URL = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-general-x4v3.pth"
DEPTH_HF_MODEL = "depth-anything/Depth-Anything-V2-Small-hf"
DEPTH_ONNX_URL = ("https://github.com/fabio-sim/Depth-Anything-ONNX/releases/download/"
                  "v2.0.0/depth_anything_v2_vits_dynamic.onnx")
T0 = time.time()


def log(msg):
    print(f"[{time.time() - T0:6.1f}s] {msg}", flush=True)


def fetch(url, name):
    path = os.path.join(MODELS_DIR, name)
    if not os.path.exists(path):
        os.makedirs(MODELS_DIR, exist_ok=True)
        log(f"скачиваю {name} ...")
        urllib.request.urlretrieve(url, path + ".part")
        os.replace(path + ".part", path)
    return path


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def ffmpeg_exe():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def save_debug(name, img):
    if not SAVE_DEBUG:
        return
    d = os.path.join(OUTPUT_DIR, "debug")
    os.makedirs(d, exist_ok=True)
    if img.dtype != np.uint8:
        img = np.clip(img * 255, 0, 255).astype(np.uint8)
    if img.ndim == 3:
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    cv2.imwrite(os.path.join(d, name), img)


# ----------------------------- 1. загрузка -----------------------------
def load_image(path):
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    return np.array(im)


# ----------------------------- 2. апскейл ------------------------------
def esrgan_upscale(img):
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    class SRVGGNetCompact(nn.Module):  # архитектура realesr-general-x4v3
        def __init__(self, nf=64, nc=32, up=4):
            super().__init__()
            self.up = up
            layers = [nn.Conv2d(3, nf, 3, 1, 1), nn.PReLU(nf)]
            for _ in range(nc):
                layers += [nn.Conv2d(nf, nf, 3, 1, 1), nn.PReLU(nf)]
            layers += [nn.Conv2d(nf, 3 * up * up, 3, 1, 1)]
            self.body = nn.ModuleList(layers)
            self.upsampler = nn.PixelShuffle(up)

        def forward(self, x):
            out = x
            for layer in self.body:
                out = layer(out)
            return self.upsampler(out) + F.interpolate(x, scale_factor=self.up, mode="nearest")

    torch.set_num_threads(os.cpu_count() or 4)
    net = SRVGGNetCompact()
    state = torch.load(fetch(ESRGAN_URL, "realesr-general-x4v3.pth"), map_location="cpu", weights_only=True)
    net.load_state_dict(state.get("params", state.get("params_ema", state)))
    net.eval()

    h, w = img.shape[:2]
    x = torch.from_numpy(img.astype(np.float32) / 255).permute(2, 0, 1)[None]
    out = np.zeros((h * 4, w * 4, 3), np.float32)
    tile, pad = 256, 12
    with torch.inference_mode():
        for y0 in range(0, h, tile):
            for x0 in range(0, w, tile):
                ya, yb = max(0, y0 - pad), min(h, y0 + tile + pad)
                xa, xb = max(0, x0 - pad), min(w, x0 + tile + pad)
                o = net(x[:, :, ya:yb, xa:xb])[0].permute(1, 2, 0).numpy()
                ty, tx = (y0 - ya) * 4, (x0 - xa) * 4
                th, tw = min(tile, h - y0) * 4, min(tile, w - x0) * 4
                out[y0 * 4:y0 * 4 + th, x0 * 4:x0 * 4 + tw] = o[ty:ty + th, tx:tx + tw]
    out = np.clip(out, 0, 1)
    return cv2.resize(out, (w * UPSCALE, h * UPSCALE), interpolation=cv2.INTER_AREA)


def lanczos_upscale(img):
    up = cv2.resize(img.astype(np.float32) / 255, None, fx=UPSCALE, fy=UPSCALE,
                    interpolation=cv2.INTER_LANCZOS4)
    blur = cv2.GaussianBlur(up, (0, 0), 1.2)
    return np.clip(up + 0.45 * (up - blur), 0, 1)  # лёгкая резкость (unsharp mask)


def upscale(img):
    lz = lanczos_upscale(img)
    try:
        sr = esrgan_upscale(img)
        log("апскейл x%d: Real-ESRGAN (realesr-general-x4v3)" % UPSCALE)
        out = ESRGAN_BLEND * sr + (1 - ESRGAN_BLEND) * lz
    except Exception as e:  # нет torch / не скачались веса — простой вариант
        log(f"Real-ESRGAN недоступен ({e.__class__.__name__}: {e}); апскейл Lanczos + резкость")
        out = lz
    h, w = out.shape[:2]
    k = min(1.0, (MAX_PIXELS / (h * w)) ** 0.5)
    nw, nh = int(w * k) // 2 * 2, int(h * k) // 2 * 2  # чётные размеры для yuv420p
    if (nw, nh) != (w, h):
        out = cv2.resize(out, (nw, nh), interpolation=cv2.INTER_AREA)
    return out.astype(np.float32)


# ------------------------- 3. маска человека ---------------------------
def fill_holes(b):
    inv = (b == 0).astype(np.uint8)
    h, w = b.shape
    ff = inv.copy()
    mask = np.zeros((h + 2, w + 2), np.uint8)
    for sx, sy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if ff[sy, sx]:
            cv2.floodFill(ff, mask, (sx, sy), 2)
    return np.where(ff == 1, 1, b).astype(np.uint8)


def clean_mask(m):
    # гистерезис: уверенные пиксели + примыкающие к ним полупрозрачные (ноги, руки)
    strong = (m >= 128).astype(np.uint8)
    weak = (m >= 50).astype(np.uint8)
    n, lab = cv2.connectedComponents(weak, connectivity=8)
    ids = np.unique(lab[strong > 0])
    b = np.isin(lab, ids[ids > 0]).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(b, 8)
    if n <= 1:
        return b
    areas = st[1:, cv2.CC_STAT_AREA]
    keep = np.zeros(n, bool)
    keep[1:] = areas >= 0.12 * areas.max()
    b = fill_holes(keep[lab].astype(np.uint8))
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    b = cv2.morphologyEx(b, cv2.MORPH_CLOSE, k)
    return cv2.morphologyEx(b, cv2.MORPH_OPEN, k)


def mask_depth_score(b, depth):
    """Насколько контур маски совпадает со скачком глубины (у хорошей маски — сильно)."""
    w = b.shape[1]
    inner = cv2.erode(b, np.ones((5, 5), np.uint8))
    ring = (dilate(b, max(3, int(0.03 * w))) > 0) & (dilate(b, max(2, int(0.008 * w))) == 0)
    if inner.sum() < 50 or ring.sum() < 50:
        return 0.0
    di, dr = depth[inner > 0], depth[ring]
    q1, q3 = np.percentile(di, [25, 75])
    return abs(np.median(di) - np.median(dr)) / (q3 - q1 + 0.03)


def person_mask(img01, depth):
    from rembg import new_session, remove
    pil = Image.fromarray((img01 * 255).astype(np.uint8))
    total = img01.shape[0] * img01.shape[1]
    best, best_score = None, -1.0
    for name in MASK_MODELS:
        try:
            m = np.array(remove(pil, session=new_session(name), only_mask=True))
        except Exception as e:
            log(f"rembg {name}: ошибка {e}")
            continue
        b = clean_mask(m)
        frac = b.sum() / total
        top_touch = b[: max(2, b.shape[0] // 200)].mean()
        score = mask_depth_score(b, depth) * (1 - top_touch) if 0.005 < frac < 0.7 else 0.0
        log(f"rembg {name}: маска {frac * 100:.1f}% кадра, совпадение с глубиной {score:.2f}")
        if score > best_score:
            best, best_score, best_name = b, score, name
    if best is None or best_score <= 0.3:
        log("человек не найден — анимирую весь кадр как фон")
        return np.zeros(img01.shape[:2], np.uint8)
    log(f"маска человека: {best_name}")
    return best


def dilate(b, r):
    if r <= 0:
        return b.copy()
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    return cv2.dilate(b, k)


# ------------------------ 4. фон за человеком --------------------------
def inpaint_background(img01, hole):
    u8 = (img01 * 255).astype(np.uint8)
    bgr = cv2.cvtColor(u8, cv2.COLOR_RGB2BGR)
    # грубая заливка на 1/4 разрешения (меньше «потёков»), затем точная на полном
    h, w = hole.shape
    s = 4
    small = cv2.resize(bgr, (w // s, h // s), interpolation=cv2.INTER_AREA)
    hs = (cv2.resize(hole, (w // s, h // s), interpolation=cv2.INTER_NEAREST) > 0).astype(np.uint8)
    hs = dilate(hs, 1)
    coarse = cv2.inpaint(small, hs, 6, cv2.INPAINT_TELEA)
    coarse = cv2.resize(coarse, (w, h), interpolation=cv2.INTER_CUBIC)
    pre = np.where(hole[..., None] > 0, coarse, bgr)
    band = (hole > 0) & (cv2.erode(hole, np.ones((3, 3), np.uint8), iterations=12) == 0)
    fine = cv2.inpaint(pre, band.astype(np.uint8), 5, cv2.INPAINT_TELEA)
    out = cv2.cvtColor(fine, cv2.COLOR_BGR2RGB).astype(np.float32) / 255
    # зерно, как у остального кадра
    g = cv2.cvtColor(img01, cv2.COLOR_RGB2GRAY)
    hf = g - cv2.GaussianBlur(g, (0, 0), 1.5)
    sigma = 1.4826 * np.median(np.abs(hf[hole == 0])) if (hole == 0).any() else 0.0
    rng = np.random.default_rng(1)
    noise = rng.normal(0, sigma, hole.shape).astype(np.float32)
    out += (hole > 0)[..., None] * noise[..., None]
    return np.clip(out, 0, 1)


# --------------------------- 5. глубина --------------------------------
def depth_transformers(img01):
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "15")
    os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "10")
    from transformers import pipeline
    pipe = pipeline("depth-estimation", model=DEPTH_HF_MODEL, device=-1)
    out = pipe(Image.fromarray((img01 * 255).astype(np.uint8)))
    d = np.asarray(out["predicted_depth"], dtype=np.float32).squeeze()
    return d


def depth_onnx(img01):
    import onnxruntime as ort
    sess = ort.InferenceSession(fetch(DEPTH_ONNX_URL, "depth_anything_v2_vits_dynamic.onnx"),
                                providers=["CPUExecutionProvider"])
    h, w = img01.shape[:2]
    k = 518 / min(h, w)
    nh, nw = max(14, round(h * k / 14) * 14), max(14, round(w * k / 14) * 14)
    x = cv2.resize(img01, (nw, nh), interpolation=cv2.INTER_CUBIC)
    x = (x - np.array([0.485, 0.456, 0.406], np.float32)) / np.array([0.229, 0.224, 0.225], np.float32)
    x = x.transpose(2, 0, 1)[None].astype(np.float32)
    return sess.run(None, {sess.get_inputs()[0].name: x})[0].squeeze()


def estimate_depth(img01):
    """Относительная близость 0..1 (1 = ближе к камере)."""
    h, w = img01.shape[:2]
    for name, fn in (("Depth Anything V2 Small (transformers)", depth_transformers),
                     ("Depth Anything V2 Small (ONNX)", depth_onnx)):
        try:
            d = fn(img01)
            d = cv2.resize(d.astype(np.float32), (w, h), interpolation=cv2.INTER_CUBIC)
            lo, hi = np.percentile(d, 1), np.percentile(d, 99)
            log(f"глубина: {name}")
            return np.clip((d - lo) / max(hi - lo, 1e-6), 0, 1).astype(np.float32), name
        except Exception as e:
            msg = str(e).splitlines()[0][:120] if str(e) else ""
            log(f"глубина: {name} недоступна ({e.__class__.__name__}: {msg})")
    log("глубина: простой вертикальный градиент")
    y = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    return np.repeat(y, w, axis=1), "вертикальный градиент"


def background_depth(depth, person, w):
    """Глубина фона без человека: дырку под человеком заполняем окружающей глубиной."""
    h = depth.shape[0]
    s = 4
    ds = cv2.resize(depth, (w // s, h // s), interpolation=cv2.INTER_AREA)
    hole = cv2.resize(dilate(person, int(0.025 * w)), (w // s, h // s), interpolation=cv2.INTER_NEAREST)
    ds = cv2.inpaint((ds * 65535).astype(np.uint16), (hole > 0).astype(np.uint8), 8,
                     cv2.INPAINT_TELEA).astype(np.float32) / 65535
    ds = cv2.GaussianBlur(ds, (0, 0), 0.006 * w)
    return cv2.resize(ds, (w, h), interpolation=cv2.INTER_CUBIC)


# ----------------------- поиск областей сцены --------------------------
def find_vanishing_point(depth_bg, person, w, h):
    far = depth_bg <= np.percentile(depth_bg[person == 0] if (person == 0).any() else depth_bg, 3)
    ys, xs = np.nonzero(far)
    if len(xs) == 0:
        return np.array([w / 2, h * 0.42])
    vx, vy = np.median(xs), np.median(ys)
    return np.array([np.clip(vx, 0.25 * w, 0.75 * w), np.clip(vy, 0.15 * h, 0.65 * h)], np.float32)


def largest_component(b, score=None):
    n, lab, st, _ = cv2.connectedComponentsWithStats(b.astype(np.uint8), 8)
    if n <= 1:
        return None, None
    if score is None:
        vals = st[1:, cv2.CC_STAT_AREA].astype(np.float64)
    else:
        vals = np.bincount(lab.ravel(), weights=score.ravel(), minlength=n)[1:]
    i = int(np.argmax(vals)) + 1
    return (lab == i).astype(np.uint8), st[i]


def detect_floor(img01, depth_bg, vp, hole, w, h):
    yy = np.arange(h, dtype=np.float32)[:, None] * np.ones((1, w), np.float32)
    ds = cv2.GaussianBlur(depth_bg, (0, 0), 0.012 * w)
    gx = cv2.Sobel(ds, cv2.CV_32F, 1, 0, ksize=5)
    gy = cv2.Sobel(ds, cv2.CV_32F, 0, 1, ksize=5)
    vert = gy / (np.abs(gx) + np.abs(gy) + 1e-6)
    hsv = cv2.cvtColor((img01 * 255).astype(np.uint8), cv2.COLOR_RGB2HSV)
    hue = hsv[..., 0].astype(np.float32)
    blue = 1 - smoothstep(25, 45, np.abs(hue - 110))
    below = smoothstep(vp[1] + 0.03 * h, vp[1] + 0.10 * h, yy)
    score = smoothstep(0.25, 0.65, vert) * below * (0.55 + 0.45 * blue)
    score[dilate(hole, 4) > 0] = np.maximum(score[dilate(hole, 4) > 0], below[dilate(hole, 4) > 0] * 0.6)
    b = (score > 0.4).astype(np.uint8)
    b = cv2.morphologyEx(b, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    # оставляем то, что касается низа кадра
    n, lab, st, _ = cv2.connectedComponentsWithStats(b, 8)
    bottom_ids = set(np.unique(lab[int(h * 0.97):, :])) - {0}
    b = np.isin(lab, list(bottom_ids)).astype(np.uint8) if bottom_ids else np.zeros_like(b)
    if b.sum() < 0.03 * w * h:  # запасной вариант — трапеция от точки схода к низу кадра
        log("пол: по глубине не найден, беру трапецию от точки схода")
        b = np.zeros((h, w), np.uint8)
        top = vp[1] + 0.08 * h
        pts = np.array([[vp[0] - 0.08 * w, top], [vp[0] + 0.08 * w, top], [w, h], [0, h]], np.int32)
        cv2.fillPoly(b, [pts], 1)
    b = fill_holes(cv2.morphologyEx(b, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8)))
    soft = cv2.GaussianBlur(b.astype(np.float32), (0, 0), 0.02 * w)
    return soft * below


def detect_light_spot(img01, exclude, w, h):
    hsv = cv2.cvtColor((img01 * 255).astype(np.uint8), cv2.COLOR_RGB2HSV)
    H, S, V = [hsv[..., i].astype(np.float32) for i in range(3)]
    pink = ((H >= 125) | (H <= 6)) & (S >= 50) & (V >= 100) & (exclude == 0)
    pink[int(h * 0.8):] = False
    pink = cv2.morphologyEx(pink.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    comp, st = largest_component(pink, score=S * V / 65025.0)
    if comp is None or comp.sum() < 0.002 * w * h:
        return None
    area = comp.sum()
    sig = 0.35 * np.sqrt(area)
    soft = cv2.GaussianBlur(comp.astype(np.float32) * (V / 255.0), (0, 0), sig)
    soft /= soft.max() + 1e-6
    color = img01[comp > 0].mean(0)
    color = color / (color.max() + 1e-6)
    glow = cv2.GaussianBlur(soft, (0, 0), sig * 1.2)
    glow /= glow.max() + 1e-6
    # яркое ядро почти не трогаем (иначе пересвет), «дышит» ореол вокруг него
    room = (0.25 + 0.75 * np.clip(1 - img01.max(2), 0, 1) / 0.6).clip(0, 1).astype(np.float32)
    x, y, bw, bh = st[0], st[1], st[2], st[3]
    log(f"световое пятно: x={x}..{x + bw}, y={y}..{y + bh}, цвет={np.round(color, 2)}")
    return {"soft": soft, "glow": glow, "room": room, "color": color.astype(np.float32)}


def detect_aquarium(img01, exclude, person, w, h):
    hsv = cv2.cvtColor((img01 * 255).astype(np.uint8), cv2.COLOR_RGB2HSV)
    H, S, V = [hsv[..., i].astype(np.float32) for i in range(3)]
    local = cv2.GaussianBlur(V, (0, 0), 0.08 * w)
    free = exclude == 0
    seed = (H >= 75) & (H <= 112) & (S >= 60) & (V >= 90) & (V > local + 20) & free
    seed = cv2.morphologyEx(seed.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(seed, 8)
    best, best_score = None, 0.0
    for i in range(1, n):
        x, y, bw, bh, area = st[i]
        if not (0.001 * w * h < area < 0.2 * w * h):
            continue
        comp = (lab == i).astype(np.uint8)
        fill = area / max(cv2.contourArea(cv2.convexHull(cv2.findNonZero(comp))), 1)
        sc = area * fill * V[comp > 0].mean()
        if fill > 0.45 and sc > best_score:
            best, best_score = comp, sc
    if best is None:
        return None
    # окно часто разрезано человеком: присоединяем куски по другую сторону от него,
    # если промежуток между ними закрыт человеком (окно продолжается за ним)
    broad = (H >= 75) & (H <= 125) & (S >= 40) & (V >= 110) & (V > local + 15) & free
    broad = cv2.morphologyEx(broad.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(broad, 8)
    occl = dilate(person, int(0.02 * w)) > 0
    union = best.copy()
    for _ in range(3):
        ux, uy, uw, uh = cv2.boundingRect(cv2.findNonZero(union))
        grown = False
        for i in range(1, n):
            x, y, bw, bh, area = st[i]
            if area < 0.0005 * w * h or (union[lab == i] > 0).all():
                continue
            ov = min(y + bh, uy + uh) - max(y, uy)
            if ov < 0.5 * min(bh, uh) or abs(y - uy) > 0.03 * h:
                continue
            g0, g1 = (ux + uw, x) if x >= ux + uw else ((x + bw, ux) if x + bw <= ux else (0, 0))
            rows = slice(max(y, uy), min(y + bh, uy + uh))
            cover = occl[rows, g0:g1].mean() if g1 > g0 else 1.0
            if cover >= 0.6:
                union |= (lab == i).astype(np.uint8)
                grown = True
        if not grown:
            break
    m = np.zeros((h, w), np.uint8)
    cv2.fillPoly(m, [cv2.convexHull(cv2.findNonZero(union))], 1)
    # отступаем внутрь от рамы окна, чтобы рябь не «гнула» её
    m = cv2.erode(m, np.ones((3, 3), np.uint8), iterations=max(2, int(0.018 * w)))
    soft = cv2.GaussianBlur(m.astype(np.float32), (0, 0), 0.006 * w + 1)
    x, y, bw, bh = cv2.boundingRect(cv2.findNonZero(m))
    log(f"окно-аквариум: x={x}..{x + bw}, y={y}..{y + bh}")
    return {"soft": soft, "bbox": (x, y, bw, bh)}


# ------------------------- процедурные эффекты --------------------------
def caustic_pattern(u, v, ph):
    """Водные блики (итеративное искажение координат, как в классическом шейдере каустики).
    ph — фаза цикла 0..2π; все множители времени целые -> узор бесшовно зацикливается."""
    px, py = (u * 2 * np.pi).astype(np.float32), (v * 2 * np.pi).astype(np.float32)
    ix, iy = px, py
    c = np.ones_like(px)
    for mult, off in ((1, 0.7), (-1, 2.9), (2, 4.1), (-1, 1.6), (1, 5.3)):
        t = ph * mult + off
        ix, iy = px + np.cos(t - ix) + np.sin(t + iy), py + np.sin(t - iy) + np.cos(t + ix)
        c += 1.0 / np.sqrt((1.25 / (np.sin(ix + t) + 1e-6)) ** 2 + (1.25 / (np.cos(iy + t) + 1e-6)) ** 2)
    c = np.abs(1.17 - (c / 5) ** 1.4) ** 8
    return np.clip((c - 0.06) / 0.75, 0, 1)


class Effects:
    def __init__(self, plate, depth_bg, person_hole, vp, w, h):
        self.plate = plate
        self.w, self.h = w, h
        excl = dilate(person_hole, 6)
        self.floor = detect_floor(plate, depth_bg, vp, person_hole, w, h) if CAUSTICS > 0 else None
        floor_b = (self.floor > 0.3).astype(np.uint8) if self.floor is not None else np.zeros((h, w), np.uint8)
        self.spot = detect_light_spot(plate, excl | floor_b, w, h) if LIGHT_PULSE > 0 else None
        spot_b = (self.spot["soft"] > 0.25).astype(np.uint8) if self.spot else np.zeros((h, w), np.uint8)
        self.aqua = detect_aquarium(plate, excl | floor_b | spot_b, person_hole, w, h) if WATER_SHIMMER > 0 else None
        if self.spot is None and LIGHT_PULSE > 0:
            log("световое пятно не найдено — эффект пропущен")
        if self.aqua is None and WATER_SHIMMER > 0:
            log("окно-аквариум не найдено — эффект пропущен")

        # плоскостные координаты пола для каустики (перспектива: Z ~ 1/(y - горизонт))
        if self.floor is not None:
            ys, xs = np.nonzero(self.floor > 0.02)
            self.fy0, self.fy1 = ys.min(), ys.max() + 1
            self.fx0, self.fx1 = xs.min(), xs.max() + 1
            # узор считаем на половинном разрешении (он плавный) — в 4 раза быстрее
            self.fsize = (self.fx1 - self.fx0, self.fy1 - self.fy0)
            hy, hx = np.mgrid[self.fy0:self.fy1:2, self.fx0:self.fx1:2].astype(np.float32)
            hdy = np.maximum(hy - vp[1], 0.04 * h)
            self.fu = (hx - vp[0]) / hdy * CAUSTIC_SCALE
            self.fv = 0.55 * h / hdy * CAUSTIC_SCALE
            yy = np.mgrid[self.fy0:self.fy1, self.fx0:self.fx1][0].astype(np.float32)
            near = smoothstep(0.06 * h, 0.30 * h, yy - vp[1])
            self.fw = (self.floor[self.fy0:self.fy1, self.fx0:self.fx1] * near)[..., None]
            lum = plate[self.fy0:self.fy1, self.fx0:self.fx1].mean(2, keepdims=True)
            self.flum = 0.55 + 0.9 * lum
            save_debug("floor_mask.png", self.floor)
        if self.spot is not None:
            save_debug("light_spot_mask.png", self.spot["soft"])
        if self.aqua is not None:
            x, y, bw, bh = self.aqua["bbox"]
            pad = 6
            self.ax0, self.ay0 = max(0, x - pad), max(0, y - pad)
            self.ax1, self.ay1 = min(w, x + bw + pad), min(h, y + bh + pad)
            ay, ax = np.mgrid[self.ay0:self.ay1, self.ax0:self.ax1].astype(np.float32)
            self.agrid = (ax, ay)
            self.am = self.aqua["soft"][self.ay0:self.ay1, self.ax0:self.ax1][..., None]
            save_debug("aquarium_mask.png", self.aqua["soft"])

    def apply(self, ph):
        out = self.plate.copy()
        if self.spot is not None:
            wave = 0.65 * np.sin(2 * ph) + 0.35 * np.sin(3 * ph + 0.9)  # -1..1, среднее 0
            k = LIGHT_PULSE * wave * self.spot["soft"] * self.spot["room"]
            out = out * (1 + k)[..., None] + (LIGHT_PULSE * 0.12 * max(wave, 0.0)) * \
                (self.spot["glow"] * self.spot["room"])[..., None] * self.spot["color"]
        if self.aqua is not None:
            ax, ay = self.agrid
            sc = max(self.w, self.h) / 1000.0
            dx = 0.8 * sc * (0.6 * np.sin(ay / (9 * sc) + 2 * ph) + 0.4 * np.sin((ax + ay) / (14 * sc) - 3 * ph))
            dy = 0.6 * sc * (0.6 * np.cos(ax / (11 * sc) - 2 * ph) + 0.4 * np.sin((ax - ay) / (17 * sc) + ph))
            reg = cv2.remap(self.plate, ax + dx, ay + dy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
            rip = caustic_pattern((ax - ax.mean()) / (40 * sc), (ay - ay.mean()) / (40 * sc), ph)
            rays = 0.5 + 0.5 * np.sin((ax * 0.5 + ay) / (22 * sc) - ph * 2)
            mod = 1 + WATER_SHIMMER * (0.55 * (rip - 0.25) + 0.35 * (rays - 0.5))
            reg = reg * mod[..., None] + WATER_SHIMMER * 0.12 * rip[..., None] * np.array([0.6, 1.0, 1.0], np.float32)
            sl = (slice(self.ay0, self.ay1), slice(self.ax0, self.ax1))
            out[sl] = out[sl] * (1 - self.am) + reg * self.am
        if self.floor is not None:
            c = cv2.resize(caustic_pattern(self.fu, self.fv, ph), self.fsize, interpolation=cv2.INTER_LINEAR)[..., None]
            light = CAUSTICS * c * self.fw * self.flum * np.array([0.65, 0.92, 1.0], np.float32)
            sl = (slice(self.fy0, self.fy1), slice(self.fx0, self.fx1))
            out[sl] = 1 - (1 - np.clip(out[sl], 0, 1)) * (1 - np.clip(light, 0, 1))
        return out


class Dust:
    def __init__(self, w, h, person, d_ref, n):
        rng = np.random.default_rng(42)
        sc = max(w, h) / 1000.0
        ys, xs = np.nonzero(person)
        head = None
        if len(ys):
            top, bot = ys.min(), ys.max()
            hy = top + 0.2 * (bot - top)
            hx = xs[ys < hy].mean() if (ys < hy).any() else xs.mean()
            head = (hx, top, hy, 0.12 * w)
        self.p = []
        for i in range(n):
            front = i % 3 == 0
            for _ in range(50):
                x, y = rng.uniform(0.05 * w, 0.95 * w), rng.uniform(0.05 * h, 0.9 * h)
                if not (front and head and abs(x - head[0]) < head[3] and head[1] - 0.05 * h < y < head[2] + 0.03 * h):
                    break
            big = rng.random() < 0.18
            self.p.append(dict(
                x=x, y=y, front=front,
                r=(rng.uniform(5, 9) if big else rng.uniform(2.0, 3.6)) * sc,
                a=(0.35 if big else 1.0) * rng.uniform(0.5, 1.0),
                ax=rng.uniform(8, 30) * sc, ay=rng.uniform(10, 40) * sc,
                kx=int(rng.integers(1, 3)), ky=int(rng.integers(1, 3)),
                fx=rng.uniform(0, 6.3), fy=rng.uniform(0, 6.3),
                kt=int(rng.integers(1, 4)), ft=rng.uniform(0, 6.3),
                depth=(1.0 if front else rng.uniform(0.2, 0.7)) - d_ref,
                col=np.array([[1.0, 0.95, 0.85], [0.85, 0.95, 1.0], [1.0, 0.85, 0.97]][i % 3], np.float32),
            ))

    def draw(self, img, ph, front, par):
        h, w = img.shape[:2]
        for p in self.p:
            if p["front"] != front:
                continue
            x = p["x"] + p["ax"] * np.sin(p["kx"] * ph + p["fx"]) + p["depth"] * par[0]
            y = p["y"] + p["ay"] * np.sin(p["ky"] * ph + p["fy"]) + p["depth"] * par[1]
            a = DUST_BRIGHTNESS * p["a"] * (0.55 + 0.45 * np.sin(p["kt"] * ph + p["ft"]))
            R = int(np.ceil(p["r"] * 5)) + 1
            x0, x1 = int(max(0, x - R)), int(min(w, x + R + 1))
            y0, y1 = int(max(0, y - R)), int(min(h, y + R + 1))
            if x1 <= x0 or y1 <= y0:
                continue
            gy, gx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
            d2 = (gx - x) ** 2 + (gy - y) ** 2
            g = (np.exp(-d2 / (2 * (p["r"] * 0.6) ** 2)) + 0.22 * np.exp(-d2 / (2 * (p["r"] * 1.8) ** 2))) * a
            sl = img[y0:y1, x0:x1]
            img[y0:y1, x0:x1] = 1 - (1 - sl) * (1 - g[..., None] * p["col"])


# ------------------------------ камера ---------------------------------
class Camera:
    def __init__(self, depth_bg, d_ref, center, w, h):
        self.D = depth_bg - d_ref         # >0 ближе человека, <0 дальше
        self.c = center
        self.w, self.h = w, h
        gy, gx = np.mgrid[0:h, 0:w].astype(np.float32)
        self.s0 = self._overscan()
        # постоянный кроп кадра (запас под движение фона): выход -> координаты исходника
        self.qx, self.qy = self._crop(gx, gy, self.s0)
        self.Dq = cv2.remap(self.D, self.qx, self.qy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        log(f"камера: центр наезда={np.round(center).astype(int)}, запас кадра={(self.s0 - 1) * 100:.1f}%")

    def _crop(self, gx, gy, s0):
        cx0, cy0 = self.w / 2, self.h / 2
        return (cx0 + (gx - cx0) / s0).astype(np.float32), (cy0 + (gy - cy0) / s0).astype(np.float32)

    def params(self, ph):
        z = ZOOM * 0.5 * (1 - np.cos(ph))
        px = PARALLAX * self.w * np.sin(ph)
        py = PARALLAX * self.w * SWAY_Y * np.sin(2 * ph) * 0.5
        return z, px, py

    def _warp(self, ph, qx, qy, D):
        z, px, py = self.params(ph)
        S = 1 + z * (PERSON_FOLLOW_ZOOM + D)
        mx = self.c[0] + (qx - self.c[0]) / S - D * px
        my = self.c[1] + (qy - self.c[1]) / S - D * py
        return mx.astype(np.float32), my.astype(np.float32)

    def maps(self, ph):
        return self._warp(ph, self.qx, self.qy, self.Dq)

    def person_maps(self, ph):
        z, _, _ = self.params(ph)
        S = 1 + z * PERSON_FOLLOW_ZOOM
        return ((self.c[0] + (self.qx - self.c[0]) / S).astype(np.float32),
                (self.c[1] + (self.qy - self.c[1]) / S).astype(np.float32))

    def _overscan(self):
        # подбираем минимальный кроп, при котором фон нигде не «выезжает» за край
        gx, gy = np.meshgrid(np.linspace(0, self.w - 1, 48, dtype=np.float32),
                             np.linspace(0, self.h - 1, 96, dtype=np.float32))
        s = 1.0
        for _ in range(8):
            qx, qy = self._crop(gx, gy, s)
            D = cv2.remap(self.D, qx, qy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
            over = 0.0
            for ph in np.linspace(0, 2 * np.pi, 36, endpoint=False):
                mx, my = self._warp(ph, qx, qy, D)
                over = max(over, (-mx.min()) / self.w, (mx.max() - (self.w - 1)) / self.w,
                           (-my.min()) / self.h, (my.max() - (self.h - 1)) / self.h)
            if over <= 0:
                break
            s *= 1 + 2 * over + 0.002
        return min(s, 1.2)


# ------------------------------ вывод ----------------------------------
class VideoWriter:
    def __init__(self, path, w, h):
        cmd = [ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", f"{w}x{h}", "-r", str(FPS), "-i", "-",
               "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
               "-profile:v", "high", "-movflags", "+faststart", path]
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    def write(self, frame_u8):
        self.p.stdin.write(np.ascontiguousarray(frame_u8).tobytes())

    def close(self):
        self.p.stdin.close()
        if self.p.wait() != 0:
            raise RuntimeError("ffmpeg завершился с ошибкой")


def to_9x16(frame01, W=1080, H=1920):
    h, w = frame01.shape[:2]
    k = max(W / w, H / h)
    bg = cv2.resize(frame01, (int(np.ceil(w * k)), int(np.ceil(h * k))), interpolation=cv2.INTER_LINEAR)
    y0, x0 = (bg.shape[0] - H) // 2, (bg.shape[1] - W) // 2
    bg = bg[y0:y0 + H, x0:x0 + W]
    small = cv2.resize(bg, (W // 8, H // 8), interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (0, 0), 6)
    bg = cv2.resize(small, (W, H), interpolation=cv2.INTER_LINEAR) * 0.55
    k = min(W / w, H / h)
    fw, fh = int(round(w * k)) // 2 * 2, int(round(h * k)) // 2 * 2
    fg = cv2.resize(frame01, (fw, fh), interpolation=cv2.INTER_CUBIC if k > 1 else cv2.INTER_AREA)
    x0, y0 = (W - fw) // 2, (H - fh) // 2
    # мягкая тень по краю основного кадра
    sh = np.zeros((H, W), np.float32)
    sh[y0:y0 + fh, x0:x0 + fw] = 1
    sh = cv2.GaussianBlur(sh, (0, 0), 18)
    bg *= (1 - 0.45 * sh)[..., None]
    bg[y0:y0 + fh, x0:x0 + fw] = fg
    return bg


def make_gif(mp4, gif):
    ff = ffmpeg_exe()
    for width, fps, colors in ((GIF_WIDTH, GIF_FPS, 128), (int(GIF_WIDTH * 0.85), 10, 96), (180, 10, 64)):
        vf = (f"fps={fps},scale={width}:-2:flags=lanczos,split[a][b];"
              f"[a]palettegen=max_colors={colors}:stats_mode=diff[p];"
              f"[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle")
        subprocess.run([ff, "-y", "-loglevel", "error", "-i", mp4, "-vf", vf, "-loop", "0", gif], check=True)
        if os.path.getsize(gif) <= 6 * 1024 * 1024:
            break
    return os.path.getsize(gif)


def extract_qa_frames(mp4, n_frames):
    """Кадры начала / середины / конца для проверки качества + общий лист."""
    d = os.path.join(OUTPUT_DIR, "qa")
    os.makedirs(d, exist_ok=True)
    ff = ffmpeg_exe()
    names = []
    for label, idx in (("start", 0), ("middle", n_frames // 2), ("end", n_frames - 1)):
        p = os.path.join(d, f"frame_{label}.png")
        subprocess.run([ff, "-y", "-loglevel", "error", "-i", mp4, "-vf", f"select=eq(n\\,{idx})",
                        "-vframes", "1", p], check=True)
        names.append(p)
    ims = [cv2.imread(p) for p in names]
    sheet = np.concatenate([cv2.resize(i, (i.shape[1] // 2, i.shape[0] // 2)) for i in ims], axis=1)
    cv2.imwrite(os.path.join(d, "contact_sheet.jpg"), sheet, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return names


def open_file(path):
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif os.name == "nt":
            os.startfile(path)  # noqa
        elif shutil.which("xdg-open"):
            subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            log("xdg-open не найден (нет графического окружения) — откройте файл вручную: " + path)
            return False
        return True
    except Exception as e:
        log(f"не удалось открыть видео автоматически: {e}")
        return False


# ------------------------------- main ----------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", nargs="?", default=INPUT)
    ap.add_argument("--no-open", action="store_true", help="не открывать видео после рендера")
    args = ap.parse_args()
    if not os.path.exists(args.input):
        sys.exit(f"Не найден файл {args.input}. Положите фото рядом со скриптом как {INPUT} "
                 f"или передайте путь: python animate.py путь/к/фото.jpg")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    src = load_image(args.input)
    log(f"исходник {args.input}: {src.shape[1]}x{src.shape[0]}")
    img = upscale(src)
    h, w = img.shape[:2]
    log(f"рабочее разрешение: {w}x{h}")
    save_debug("01_upscaled.png", img)

    depth, depth_name = estimate_depth(img)
    person = person_mask(img, depth)
    sc = max(w, h) / 2000.0
    ring = max(1, int(round(PERSON_RING * sc)))
    feather = MASK_FEATHER * sc
    alpha = cv2.GaussianBlur(dilate(person, ring).astype(np.float32), (0, 0), feather) if person.any() \
        else np.zeros((h, w), np.float32)
    hole = dilate(person, ring + int(3 * feather) + int(HOLE_EXTRA * sc)) if person.any() else person
    save_debug("02_person_alpha.png", alpha)

    plate = img.copy()
    if person.any():
        # заливка берёт цвета снаружи широкой зоны (без «ореола» человека),
        # но в кадр идёт только под самим человеком — вокруг остаётся исходный фон
        under = cv2.GaussianBlur(dilate(person, ring + 2).astype(np.float32), (0, 0), feather)[..., None]
        plate = img * (1 - under) + inpaint_background(img, hole) * under
    save_debug("03_background_plate.png", plate)

    d_ref = float(np.median(depth[cv2.erode(person, np.ones((9, 9), np.uint8)) > 0])) if person.sum() > 100 \
        else float(np.median(depth))
    depth_bg = background_depth(depth, person, w) if person.any() else cv2.GaussianBlur(depth, (0, 0), 0.006 * w)
    save_debug("04_depth.png", depth)
    save_debug("05_depth_background.png", depth_bg)
    vp = find_vanishing_point(depth_bg, person, w, h)
    log(f"глубина человека={d_ref:.2f}, точка схода={np.round(vp).astype(int)}")

    fx = Effects(plate, depth_bg, hole, vp, w, h)
    cam = Camera(depth_bg, d_ref, vp, w, h)
    dust = Dust(w, h, person, d_ref, DUST_COUNT)

    if SAVE_DEBUG:
        ov = img.copy()
        if fx.floor is not None:
            ov = ov * (1 - 0.5 * fx.floor[..., None]) + 0.5 * fx.floor[..., None] * np.array([0, 1, 0.3])
        if fx.spot is not None:
            ov = ov * (1 - 0.5 * fx.spot["soft"][..., None]) + 0.5 * fx.spot["soft"][..., None] * np.array([1, 0, 1])
        if fx.aqua is not None:
            ov = ov * (1 - 0.6 * fx.aqua["soft"][..., None]) + 0.6 * fx.aqua["soft"][..., None] * np.array([0, 1, 1])
        ov = ov * (1 - 0.5 * alpha[..., None]) + 0.5 * alpha[..., None] * np.array([1, 0.6, 0])
        cv2.circle(ov, tuple(int(v) for v in vp), int(8 * sc), (1, 1, 0), -1)
        save_debug("06_regions_overlay.png", np.clip(ov, 0, 1))

    n = int(round(DURATION * FPS))
    out_main = os.path.join(OUTPUT_DIR, "animation.mp4")
    out_916 = os.path.join(OUTPUT_DIR, "animation_9x16.mp4")
    v1, v2 = VideoWriter(out_main, w, h), VideoWriter(out_916, 1080, 1920)

    person_static = PERSON_FOLLOW_ZOOM == 0
    if person_static:
        pmx, pmy = cam.person_maps(0.0)
        P = cv2.remap(img, pmx, pmy, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
        A = cv2.remap(alpha, pmx, pmy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)[..., None]
    first = prev = None
    diffs = []
    log(f"рендер {n} кадров ({DURATION:g} c, {FPS} fps)...")
    for i in range(n):
        ph = 2 * np.pi * i / n
        plate_fx = fx.apply(ph)
        mx, my = cam.maps(ph)
        frame = cv2.remap(plate_fx, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        frame = np.clip(frame, 0, 1)
        _, px, py = cam.params(ph)
        dust.draw(frame, ph, False, (px, py))
        if not person_static:
            pmx, pmy = cam.person_maps(ph)
            P = cv2.remap(img, pmx, pmy, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
            A = cv2.remap(alpha, pmx, pmy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)[..., None]
        frame = frame * (1 - A) + P * A
        dust.draw(frame, ph, True, (px, py))
        frame = np.clip(frame, 0, 1)
        u8 = (frame * 255 + 0.5).astype(np.uint8)
        v1.write(u8)
        v2.write((np.clip(to_9x16(frame), 0, 1) * 255 + 0.5).astype(np.uint8))
        if prev is not None:
            diffs.append(np.abs(u8.astype(np.int16) - prev).mean())
        if first is None:
            first = u8.astype(np.int16)
        prev = u8.astype(np.int16)
        if (i + 1) % 30 == 0 or i == n - 1:
            log(f"  кадр {i + 1}/{n}")
    v1.close()
    v2.close()
    seam = np.abs(first - prev).mean()
    log(f"бесшовность: разница последний->первый = {seam:.2f}, средняя между соседними = {np.mean(diffs):.2f}")

    gif = os.path.join(OUTPUT_DIR, "preview.gif")
    size = make_gif(out_main, gif)
    log(f"GIF-превью: {size / 1024 / 1024:.1f} МБ")
    qa = extract_qa_frames(out_main, n)
    log("кадры для проверки: " + ", ".join(qa))
    for p in (out_main, out_916, gif):
        log(f"готово: {p} ({os.path.getsize(p) / 1024 / 1024:.1f} МБ)")
    log(f"карта глубины: {depth_name}")
    if not args.no_open:
        open_file(os.path.abspath(out_main))


if __name__ == "__main__":
    main()
