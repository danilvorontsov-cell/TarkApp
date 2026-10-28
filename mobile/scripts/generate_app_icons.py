"""
TarkApp App Icon Generator Script
---------------------------------
Automates:
1. Detecting and auto-cropping 'tarkapp_icon_source.png' (stripping light background, isolating graphite logo).
2. Generating 1024x1024 standard app icon (mobile/assets/icon.png).
3. Generating Android adaptive icon in safe zone (mobile/assets/adaptive-icon.png and android-icon-foreground.png).
4. Ensuring app.json has adaptiveIcon.backgroundColor set to '#12161A'.
"""

import os
import sys
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MOBILE_DIR = REPO_ROOT / 'mobile'
ASSETS_DIR = MOBILE_DIR / 'assets'
APP_JSON_PATH = MOBILE_DIR / 'app.json'

POSSIBLE_SOURCES = [
    REPO_ROOT / 'tarkapp_icon_source.png',
    ASSETS_DIR / 'tarkapp_icon_source.png',
    MOBILE_DIR / 'tarkapp_icon_source.png',
]


def find_source_image() -> Path | None:
    for p in POSSIBLE_SOURCES:
        try:
            if p.exists() and p.is_file():
                return p
        except Exception:
            pass
    return None


def extract_graphite_squircle(img: Image.Image) -> tuple[Image.Image, Image.Image]:
    """
    Finds the central graphite rounded square in the image,
    removes the light background, and returns:
    1. solid_square_1024: Full-bleed 1024x1024 solid graphite icon for standard platforms/iOS.
    2. emblem_rgba_1024: 1024x1024 RGBA with transparent background and squircle in Android safe-zone (680x680).
    """
    rgb_img = img.convert('RGB')
    w, h = rgb_img.size
    mid_x, mid_y = w // 2, h // 2

    # Scan horizontally & vertically for dark graphite boundaries
    # Background is light (sum > 550), graphite is dark (sum < 250)
    dark_xs = [x for x in range(w) if sum(rgb_img.getpixel((x, mid_y))) < 250]
    dark_ys = [y for y in range(h) if sum(rgb_img.getpixel((mid_x, y))) < 250]

    if not dark_xs or not dark_ys:
        print("Warning: unable to locate dark bounds along center axes, falling back to full image.")
        crop = rgb_img
    else:
        left, right = min(dark_xs), max(dark_xs)
        top, bottom = min(dark_ys), max(dark_ys)
        print(f"Detected graphite badge bounds: X=[{left}..{right}] (w={right-left+1}), Y=[{top}..{bottom}] (h={bottom-top+1})")

        # Make crop strictly square
        bw = right - left + 1
        bh = bottom - top + 1
        side = max(bw, bh)
        cx = (left + right) // 2
        cy = (top + bottom) // 2
        c_left = max(0, cx - side // 2)
        c_top = max(0, cy - side // 2)
        c_right = min(w, c_left + side)
        c_bottom = min(h, c_top + side)
        crop = rgb_img.crop((c_left, c_top, c_right, c_bottom))

    cw, ch = crop.size
    crop_rgba = crop.convert('RGBA')
    crop_pixels = crop_rgba.load()

    # Create transparency mask: isolate squircle from outer light background
    mask = Image.new('L', (cw, ch), 255)
    mask_pixels = mask.load()

    # Solid fullbleed version: fill light outer corners with the graphite edge color
    fullbleed = crop.copy()
    fb_pixels = fullbleed.load()
    graphite_fill = (45, 53, 56)

    for y in range(ch):
        for x in range(cw):
            r, g, b, _ = crop_pixels[x, y]
            # Light neutral gray background condition
            is_bg = (r > 160 and g > 160 and b > 160 and abs(r - g) < 25 and abs(g - b) < 25 and abs(r - b) < 25)
            if is_bg:
                mask_pixels[x, y] = 0
                fb_pixels[x, y] = graphite_fill
            else:
                mask_pixels[x, y] = 255

    # 1. Fullbleed 1024x1024 standard icon (solid RGB, no alpha artifacts)
    # Resize with LANCZOS for maximum clarity
    solid_1024 = fullbleed.resize((1024, 1024), Image.Resampling.LANCZOS)

    # 2. Transparent squircle emblem for Android Adaptive Icon safe-zone
    # Smooth the mask boundary slightly for anti-aliasing
    smooth_mask = mask.filter(ImageFilter.GaussianBlur(1.0))
    crop_rgba.putalpha(smooth_mask)

    # Scale emblem to 680x680 (fits within 66% = 676-720 safe zone)
    safe_size = 680
    emblem_safe = crop_rgba.resize((safe_size, safe_size), Image.Resampling.LANCZOS)

    # Place in center of 1024x1024 transparent canvas
    adaptive_canvas = Image.new('RGBA', (1024, 1024), (0, 0, 0, 0))
    offset = (1024 - safe_size) // 2
    adaptive_canvas.paste(emblem_safe, (offset, offset), emblem_safe)

    return solid_1024, adaptive_canvas


def update_app_json():
    """
    Ensures app.json contains adaptiveIcon.backgroundColor = '#12161A'
    and foregroundImage = './assets/adaptive-icon.png'.
    """
    if not APP_JSON_PATH.exists():
        print(f"app.json not found at {APP_JSON_PATH}")
        return

    with open(APP_JSON_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)

    expo = data.get('expo', {})
    android = expo.get('android', {})
    adaptive = android.get('adaptiveIcon', {})

    adaptive['backgroundColor'] = '#12161A'
    adaptive['foregroundImage'] = './assets/adaptive-icon.png'

    if 'backgroundImage' in adaptive:
        del adaptive['backgroundImage']

    android['adaptiveIcon'] = adaptive
    expo['android'] = android
    data['expo'] = expo

    with open(APP_JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write('\n')

    print("Updated mobile/app.json: adaptiveIcon.backgroundColor='#12161A', foregroundImage='./assets/adaptive-icon.png'")


def main():
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    src_path = find_source_image()
    if not src_path:
        print("Error: 'tarkapp_icon_source.png' not found.")
        sys.exit(1)

    print(f"Processing source icon from: {src_path}")
    raw_img = Image.open(src_path)
    solid_1024, adaptive_1024 = extract_graphite_squircle(raw_img)

    # 1. Standard App Icon (1024x1024, RGB)
    icon_path = ASSETS_DIR / 'icon.png'
    solid_1024.convert('RGB').save(icon_path, format='PNG', optimize=True)
    print(f"Generated standard app icon: {icon_path} (1024x1024)")

    # 2. Android Adaptive Foreground Icon (1024x1024 RGBA with safe-zone)
    adaptive_path = ASSETS_DIR / 'adaptive-icon.png'
    adaptive_1024.save(adaptive_path, format='PNG', optimize=True)
    print(f"Generated Android adaptive icon: {adaptive_path} (1024x1024 safe-zone)")

    # Also sync android-icon-foreground.png
    android_fg_path = ASSETS_DIR / 'android-icon-foreground.png'
    adaptive_1024.save(android_fg_path, format='PNG', optimize=True)
    print(f"Generated android-icon-foreground: {android_fg_path} (1024x1024 safe-zone)")

    # 3. Splash Icon (512x512)
    splash_path = ASSETS_DIR / 'splash-icon.png'
    splash_icon = adaptive_1024.resize((512, 512), Image.Resampling.LANCZOS)
    splash_icon.save(splash_path, format='PNG', optimize=True)
    print(f"Generated splash icon: {splash_path} (512x512)")

    # 4. Favicon (48x48)
    favicon_path = ASSETS_DIR / 'favicon.png'
    favicon = solid_1024.resize((48, 48), Image.Resampling.LANCZOS)
    favicon.save(favicon_path, format='PNG', optimize=True)
    print(f"Generated favicon: {favicon_path} (48x48)")

    # 5. Update app.json
    update_app_json()
    print("\nSUCCESS: All icons generated and app.json updated!")


if __name__ == '__main__':
    main()
