"""Синтетическое тестовое фото (замена отсутствующего photo.jpeg).

Рисует узкий вертикальный кадр низкого разрешения: синий коридор музея,
надпись «Озеро Байкал» с розово-фиолетовым пятном, окно-аквариум за ней,
глянцевый синий пол, подсвеченные витрины справа и идущего человека.
Нужен только для проверки animate.py; на реальное фото он не влияет.

    python make_test_photo.py            -> test_photo.jpeg (480x1040)
"""
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H = 960, 2080            # рисуем в 2x, потом уменьшаем
OUT_W, OUT_H = 480, 1040
VP = (500, 900)             # точка схода
rng = np.random.default_rng(7)


def lerp(a, b, t):
    return a + (b - a) * t


def poly(img, pts, color):
    cv2.fillPoly(img, [np.array(pts, np.int32)], color, lineType=cv2.LINE_AA)


def radial(cx, cy, rx, ry):
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    return np.exp(-(((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2))


img = np.zeros((H, W, 3), np.float32)
yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)

# --- потолок / стены / пол (RGB 0..1) ---
ceil = np.clip(0.04 + 0.05 * (yy / VP[1]), 0, 1)[..., None] * np.array([0.35, 0.55, 1.0])
img[:] = ceil
left_wall = np.zeros((H, W), np.uint8)
poly(left_wall, [(0, 0), (VP[0] - 120, VP[1] - 260), (VP[0] - 120, VP[1] + 110), (0, 1500)], 255)
right_wall = np.zeros((H, W), np.uint8)
poly(right_wall, [(W, 0), (VP[0] + 110, VP[1] - 250), (VP[0] + 110, VP[1] + 105), (W, 1460)], 255)
floor = np.zeros((H, W), np.uint8)
poly(floor, [(0, 1500), (VP[0] - 120, VP[1] + 110), (VP[0] + 110, VP[1] + 105), (W, 1460), (W, H), (0, H)], 255)
endwall = np.zeros((H, W), np.uint8)
poly(endwall, [(VP[0] - 120, VP[1] - 260), (VP[0] + 110, VP[1] - 250), (VP[0] + 110, VP[1] + 105), (VP[0] - 120, VP[1] + 110)], 255)

dist = np.clip(np.abs(xx - VP[0]) / W * 2, 0, 1)
wall_col = (0.06 + 0.22 * dist)[..., None] * np.array([0.35, 0.6, 1.0]) + 0.02
for m, col in ((left_wall, wall_col), (right_wall, wall_col * 0.9)):
    a = (m > 0)[..., None]
    img = np.where(a, col, img)
img = np.where((endwall > 0)[..., None], np.array([0.05, 0.10, 0.28]), img)
fd = np.clip((yy - VP[1]) / (H - VP[1]), 0, 1)
floor_col = (0.05 + 0.25 * fd)[..., None] * np.array([0.30, 0.55, 1.0])
img = np.where((floor > 0)[..., None], floor_col, img)

# потолочные светильники
for k in range(7):
    t = (k + 1) / 8.0
    z = t ** 1.8
    cx = lerp(VP[0], W * 0.5, z)
    cy = lerp(VP[1] - 260, -60, z)
    img += radial(cx, cy, 10 + 70 * z, 4 + 22 * z)[..., None] * np.array([0.7, 0.8, 1.0]) * 0.9

# --- витрины справа (тёплая подсветка) ---
for k in range(4):
    t0, t1 = 0.12 + k * 0.22, 0.12 + k * 0.22 + 0.15
    def wx(t): return lerp(VP[0] + 110, W, t ** 1.4)
    def wy_top(t): return lerp(VP[1] - 120, 700, t ** 1.4)
    def wy_bot(t): return lerp(VP[1] + 60, 1380, t ** 1.4)
    pts = [(wx(t0), wy_top(t0)), (wx(t1), wy_top(t1)), (wx(t1), wy_bot(t1)), (wx(t0), wy_bot(t0))]
    m = np.zeros((H, W), np.uint8)
    poly(m, pts, 255)
    mf = cv2.GaussianBlur(m.astype(np.float32) / 255, (0, 0), 2)
    glow = cv2.GaussianBlur(m.astype(np.float32) / 255, (0, 0), 40)
    inner = np.clip(0.55 + 0.45 * np.sin(yy / 23.0 + k), 0, 1)
    img = img * (1 - mf[..., None]) + mf[..., None] * (np.array([1.0, 0.86, 0.62]) * (0.6 + 0.35 * inner)[..., None])
    img += glow[..., None] * np.array([0.5, 0.4, 0.25]) * 0.5

# --- окно-аквариум на левой стене за надписью ---
aq = np.zeros((H, W), np.uint8)
aq_pts = [(250, 760), (372, 800), (372, 1010), (250, 1060)]
poly(aq, aq_pts, 255)
aqf = cv2.GaussianBlur(aq.astype(np.float32) / 255, (0, 0), 1.5)
water = np.clip(0.35 + 0.65 * (1 - (yy - 760) / 300), 0.2, 1)[..., None] * np.array([0.15, 0.85, 0.95])
water += (0.15 * np.sin(xx / 9.0 + yy / 31.0) ** 8)[..., None]
img = img * (1 - aqf[..., None]) + aqf[..., None] * water
for fx, fy, c in ((290, 860, (1.0, 0.55, 0.1)), (335, 930, (1.0, 0.8, 0.2)), (300, 980, (0.9, 0.4, 0.2))):
    f = np.zeros((H, W), np.uint8)
    cv2.ellipse(f, (fx, fy), (12, 6), 10, 0, 360, 255, -1, cv2.LINE_AA)
    img = np.where((f > 0)[..., None] & (aq > 0)[..., None], np.array(c), img)
img += cv2.GaussianBlur(aq.astype(np.float32) / 255, (0, 0), 35)[..., None] * np.array([0.1, 0.45, 0.5]) * 0.7

# --- розово-фиолетовое пятно и надпись «Озеро Байкал» ---
img += radial(190, 600, 210, 150)[..., None] * np.array([0.95, 0.30, 0.85]) * 0.95
txt = Image.new("L", (900, 260), 0)
d = ImageDraw.Draw(txt)
font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 92)
d.text((20, 10), "Озеро", font=font, fill=255)
d.text((20, 120), "Байкал", font=font, fill=255)
src = np.float32([[0, 0], [900, 0], [900, 260], [0, 260]])
dst = np.float32([[30, 470], [370, 545], [370, 660], [30, 700]])
Mt = cv2.getPerspectiveTransform(src, dst)
tw = cv2.warpPerspective(np.array(txt), Mt, (W, H), flags=cv2.INTER_AREA).astype(np.float32) / 255
img = img * (1 - tw[..., None]) + tw[..., None] * np.array([1.0, 0.95, 1.0])

# --- блики на полу (отражения ламп и витрин) ---
refl = np.zeros((H, W, 3), np.float32)
fl = (floor > 0).astype(np.float32)
src_flip = img[::-1].copy()
shift = 2 * 1480 - H
refl_src = np.zeros_like(img)
refl_src[max(0, -shift):] = src_flip[:H - max(0, -shift)] if shift < 0 else src_flip
refl = cv2.GaussianBlur(refl_src, (0, 0), sigmaX=6, sigmaY=22)
img = img + fl[..., None] * refl * 0.35

# --- человек ---
P = np.zeros((H, W, 3), np.float32)
A = np.zeros((H, W), np.uint8)
cx = 515
skin = (0.80, 0.62, 0.52)
hoodie = (0.18, 0.20, 0.23)
jeans = (0.16, 0.22, 0.36)


def part(pts, col, shade=0.0):
    m = np.zeros((H, W), np.uint8)
    poly(m, pts, 255)
    mm = (m > 0)
    c = np.array(col, np.float32)
    s = 1 - shade * np.clip((xx - cx) / 120, -1, 1)
    P[mm] = (c[None] * s[mm][:, None])
    A[mm] = 255


# ноги (шаг: левая чуть вперёд)
part([(cx - 62, 1330), (cx - 6, 1330), (cx - 18, 1780), (cx - 64, 1782)], jeans, 0.25)
part([(cx + 4, 1330), (cx + 62, 1330), (cx + 58, 1745), (cx + 14, 1748)], jeans, 0.25)
# кроссовки
for x0, y0 in ((cx - 70, 1770), (cx + 8, 1735)):
    m = np.zeros((H, W), np.uint8)
    cv2.ellipse(m, (x0 + 30, y0 + 22), (40, 24), 0, 0, 360, 255, -1, cv2.LINE_AA)
    P[m > 0] = (0.92, 0.92, 0.95)
    A[m > 0] = 255
# торс (худи)
part([(cx - 92, 1000), (cx + 92, 1000), (cx + 100, 1080), (cx + 80, 1350), (cx - 80, 1350), (cx - 100, 1080)], hoodie, 0.35)
# руки
part([(cx - 100, 1010), (cx - 70, 1030), (cx - 88, 1320), (cx - 122, 1312)], hoodie, 0.2)
part([(cx + 70, 1030), (cx + 100, 1010), (cx + 126, 1300), (cx + 94, 1310)], hoodie, 0.2)
for hx, hy in ((cx - 106, 1335), (cx + 110, 1325)):
    m = np.zeros((H, W), np.uint8)
    cv2.ellipse(m, (hx, hy), (17, 26), 0, 0, 360, 255, -1, cv2.LINE_AA)
    P[m > 0] = skin
    A[m > 0] = 255
# шея и голова
part([(cx - 22, 950), (cx + 22, 950), (cx + 24, 1005), (cx - 24, 1005)], (0.72, 0.55, 0.46))
m = np.zeros((H, W), np.uint8)
cv2.ellipse(m, (cx, 890), (52, 68), 0, 0, 360, 255, -1, cv2.LINE_AA)
face = m > 0
P[face] = np.array(skin)[None] * (1 - 0.18 * np.clip((xx[face] - cx) / 52, -1, 1))[:, None]
A[face] = 255
hair = np.zeros((H, W), np.uint8)
cv2.ellipse(hair, (cx, 862), (56, 48), 0, 180, 360, 255, -1, cv2.LINE_AA)
cv2.ellipse(hair, (cx, 852), (54, 30), 0, 0, 360, 255, -1, cv2.LINE_AA)
P[hair > 0] = (0.13, 0.09, 0.07)
A[hair > 0] = 255
for ex in (cx - 20, cx + 20):
    cv2.ellipse(P, (ex, 888), (7, 4), 0, 0, 360, (0.12, 0.08, 0.07), -1, cv2.LINE_AA)
    cv2.line(P, (ex - 11, 874), (ex + 10, 872), (0.15, 0.1, 0.08), 3, cv2.LINE_AA)
cv2.line(P, (cx, 893), (cx - 4, 918), (0.6, 0.44, 0.37), 3, cv2.LINE_AA)
cv2.ellipse(P, (cx, 932), (14, 5), 0, 0, 180, (0.55, 0.3, 0.3), 3, cv2.LINE_AA)
# тень от окружающего света по краю фигуры
Af = cv2.GaussianBlur(A.astype(np.float32) / 255, (0, 0), 1.2)
rim = np.clip(Af - cv2.GaussianBlur(Af, (0, 0), 6), 0, 1)
P = P * (0.85 + 0.15 * Af[..., None]) + rim[..., None] * np.array([0.4, 0.5, 1.0]) * 0.6

# отражение человека на глянцевом полу
Pr = P[::-1].copy()
Ar = Af[::-1].copy()
off = 2 * 1792 - H
Pr = np.roll(Pr, off, axis=0)
Ar = np.roll(Ar, off, axis=0)
Ar[: 1792] = 0
Ar = cv2.GaussianBlur(Ar, (0, 0), sigmaX=4, sigmaY=10) * 0.28 * fl
Pr = cv2.GaussianBlur(Pr, (0, 0), sigmaX=4, sigmaY=10)
img = img * (1 - Ar[..., None]) + Pr * Ar[..., None]
# контактная тень под ногами
img *= 1 - 0.45 * radial(cx, 1800, 120, 22)[..., None]
img = img * (1 - Af[..., None]) + P * Af[..., None]

# --- «камерная» деградация: мягкость, шум, виньетка, низкое разрешение, JPEG ---
img = cv2.GaussianBlur(img, (0, 0), 1.0)
vign = 1 - 0.35 * (((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) / 2
img *= vign[..., None]
img = np.clip(img, 0, 1)
img = cv2.resize(img, (OUT_W, OUT_H), interpolation=cv2.INTER_AREA)
img += rng.normal(0, 0.012, img.shape).astype(np.float32)
img = np.clip(img * 255, 0, 255).astype(np.uint8)
Image.fromarray(img).save("test_photo.jpeg", quality=70)
print("saved test_photo.jpeg", img.shape[1], "x", img.shape[0])
