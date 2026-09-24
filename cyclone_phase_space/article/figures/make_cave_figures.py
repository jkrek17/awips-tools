"""Figures 9 and 10: the operational CAVE display, cropped only.

The source files are full-screen captures of the AWIPS D2D display
(2000 x 1125 pixels) taken on the OPC workstation. They are not kept in
the repository; point CPS_CAVE_CAPTURES at the directory that holds
them and run this file. Nothing in the captures is altered beyond
cropping, resizing and the panel labels added along the top edge.

Figure 9  (fig9_cave_lifecycle.jpg): six crops of the HCPSclass field
          around one western Pacific typhoon, GFS runs of 2026-09-19.
Figure 10 (fig10_cave_4panel.jpg): the four-panel procedure at 48 h of
          the 2026-09-20 0600 UTC GFS run, with the sampled values.
Figure 11 (fig11_cave_atlantic.jpg): the North Atlantic four-panel at
          five hours of the 2026-09-24 0600 UTC GFS run, with the shipped
          colormaps (CPS_HartClass, CPS_Asymmetry on HB, CPS_CoreDiverging
          on HVTL and HVTU), one row per hour.
"""
from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
CAPTURES = Path(os.environ.get("CPS_CAVE_CAPTURES", "/tmp/claude-0/-home-user-awips-tools/3a4711f2-52b1-52e4-8d45-df8bae2bffec/scratchpad/shots"))

# Map area of a full-screen capture, excluding window chrome, the color
# bar strip at the top and the product legend text at the bottom.
MAP_X0, MAP_X1 = 205, 1995
MAP_Y0, MAP_Y1 = 118, 1045

# (file, storm x, storm y, panel label)
LIFECYCLE = [
    ("img14.png", 406, 922, "(a) 19/18Z run, 12 h: valid 20 Sep 06Z, class 0"),
    ("img10.png", 406, 875, "(b) 19/18Z run, 30 h: valid 21 Sep 00Z, class 2"),
    ("img08.png", 875, 610, "(c) 19/12Z run, 96 h: valid 23 Sep 12Z, class 4"),
    ("img09.png", 1062, 422, "(d) 19/12Z run, 114 h: valid 24 Sep 06Z, class 3"),
    ("img07.png", 1125, 328, "(e) 19/12Z run, 126 h: valid 24 Sep 18Z, class 0"),
    ("img06.png", 1031, 328, "(f) 19/12Z run, 144 h: valid 25 Sep 12Z, class 1"),
]
W, H = 720, 450

# Atlantic four-panel captures (1500 x 818): file, forecast hour, valid time.
ATLANTIC = [
    ("atl_006.png", "6 h", "24 Sep 12Z"),
    ("atl_054.png", "54 h", "26 Sep 12Z"),
    ("atl_078.png", "78 h", "27 Sep 12Z"),
    ("atl_102.png", "102 h", "28 Sep 12Z"),
    ("atl_126.png", "126 h", "29 Sep 12Z"),
]
# Panel boxes inside those captures (left, top, right, bottom), measured on
# the divider lines: top-left HCPSclass, top-right HB, bottom-left HVTL
# with 850 hPa wind, bottom-right HVTU with 300 hPa wind.
ATL_PANELS = {
    "HCPSclass": (12, 48, 722, 423),
    "HB": (755, 48, 1497, 423),
    "HVTL": (12, 428, 722, 805),
    "HVTU": (755, 428, 1497, 805),
}


def font(size):
    for cand in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",):
        if Path(cand).exists():
            return ImageFont.truetype(cand, size)
    return ImageFont.load_default()


def label(im, text):
    d = ImageDraw.Draw(im, "RGBA")
    f = font(22)
    tw = d.textlength(text, font=f)
    d.rectangle([0, 0, tw + 20, 36], fill=(0, 0, 0, 200))
    d.text((10, 6), text, font=f, fill=(255, 255, 255, 255))


def make_fig9():
    sheet = Image.new("RGB", (W * 3, H * 2), "black")
    for i, (name, cx, cy, text) in enumerate(LIFECYCLE):
        im = Image.open(CAPTURES / name).convert("RGB")
        x0 = min(max(cx - W // 2, MAP_X0), MAP_X1 - W)
        y0 = min(max(cy - H // 2, MAP_Y0), MAP_Y1 - H)
        crop = im.crop((x0, y0, x0 + W, y0 + H))
        label(crop, text)
        sheet.paste(crop, ((i % 3) * W, (i // 3) * H))
    d = ImageDraw.Draw(sheet)
    for k in (1, 2):
        d.line([(k * W, 0), (k * W, H * 2)], fill="white", width=2)
    d.line([(0, H), (W * 3, H)], fill="white", width=2)
    out = HERE / "fig9_cave_lifecycle.jpg"
    sheet.save(out, "JPEG", quality=88)
    print("wrote", out, sheet.size)


def make_fig10():
    im = Image.open(CAPTURES / "img19.png").convert("RGB")
    crop = im.crop((22, 115, 1998, 1075))
    new_w = 1800
    crop = crop.resize((new_w, int(round(crop.size[1] * new_w / crop.size[0]))), Image.LANCZOS)
    out = HERE / "fig10_cave_4panel.jpg"
    crop.save(out, "JPEG", quality=88)
    print("wrote", out, crop.size)


def make_fig11():
    order = ["HCPSclass", "HB", "HVTL", "HVTU"]
    pw, ph = 740, 390
    label_h, left_w = 34, 150
    sheet = Image.new("RGB", (left_w + pw * 4, label_h + ph * len(ATLANTIC)), "white")
    d = ImageDraw.Draw(sheet)
    f_title = font(24)
    f_row = font(22)
    titles = {"HCPSclass": "HCPSclass, MSLP", "HB": "HB (CPS_Asymmetry), MSLP",
              "HVTL": "HVTL, 850 hPa wind", "HVTU": "HVTU, 300 hPa wind"}
    for k, name in enumerate(order):
        d.text((left_w + k * pw + 10, 6), titles[name], font=f_title, fill="black")
    for i, (fname, hour, valid) in enumerate(ATLANTIC):
        im = Image.open(CAPTURES / fname).convert("RGB")
        y0 = label_h + i * ph
        d.text((10, y0 + ph // 2 - 28), hour, font=f_title, fill="black")
        d.text((10, y0 + ph // 2 + 4), valid, font=f_row, fill="black")
        for k, name in enumerate(order):
            crop = im.crop(ATL_PANELS[name]).resize((pw, ph), Image.LANCZOS)
            sheet.paste(crop, (left_w + k * pw, y0))
    d = ImageDraw.Draw(sheet)
    for k in range(1, 4):
        x = left_w + k * pw
        d.line([(x, label_h), (x, sheet.size[1])], fill="white", width=3)
    for i in range(1, len(ATLANTIC)):
        y = label_h + i * ph
        d.line([(left_w, y), (sheet.size[0], y)], fill="white", width=3)
    out = HERE / "fig11_cave_atlantic.jpg"
    sheet.save(out, "JPEG", quality=88)
    print("wrote", out, sheet.size)


if __name__ == "__main__":
    make_fig9()
    make_fig10()
    make_fig11()
