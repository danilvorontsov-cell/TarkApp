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
    Path('C:/Users/danil/Downloads/tarkapp_icon_source.png'),
    Path('C:/Users/danil/Desktop/tarkapp_icon_source.png'),
]


def find_source_image() -> Path | None:
    for p in POSSIBLE_SOURCES:
        try:
            if p.exists() and p.is_file():
                return p
        except Exception:
            pass
    return None


def auto_crop_graphite_logo(img: Image.Image) -> Image.Image:
    """
    Detects the outer light background and crops the central graphite square.
    """
    rgb_img = img.convert('RGB')
    w, h = rgb_img.size

    # Sample corners to determine background color
    corners = [
        rgb_img.getpixel((2, 2)),
        rgb_img.getpixel((w - 3, 2)),
        rgb_img.getpixel((2, h - 3)),
        rgb_img.getpixel((w - 3, h - 3)),
    ]
    bg_r = sum(c[0] for c in corners) / 4.0
    bg_g = sum(c[1] for c in corners) / 4.0
    bg_b = sum(c[2] for c in corners) / 4.0

    print(f"Detected background color: RGB({bg_r:.1f}, {bg_g:.1f}, {bg_b:.1f})")

    # Scan for bounding box of dark/graphite region (pixels significantly different from bg or dark)
    min_x, min_y, max_x, max_y = w, h, 0, 0
    found_any = False

    pixels = rgb_img.load()
    for y in range(h):
        for x in range(w):
            r, g, b = pixels[x, y]
            # Color difference from background
            diff = abs(r - bg_r) + abs(g - bg_g) + abs(b - bg_b)
            # Or dark pixel check
            is_dark = (r < 75 and g < 75 and b < 75)
            if diff > 45 or is_dark:
                found_any = True
                if x < min_x: min_x = x
                if y < min_y: min_y = y
                if x > max_x: max_x = x
                if y > max_y: max_y = y

    if not found_any or max_x <= min_x or max_y <= min_y:
        print("Warning: could not detect dark boundary, using full image.")
        return rgb_img

    print(f"Crop box detected: ({min_x}, {min_y}, {max_x}, {max_y}), size: {max_x - min_x}x{max_y - min_y}")

    # Make crop box square while preserving center
    cw = max_x - min_x
    ch = max_y - min_y
    side = max(cw, ch)
    mid_x = (min_x + max_x) // 2
    mid_y = (min_y + max_y) // 2

    crop_left = max(0, mid_x - side // 2)
    crop_top = max(0, mid_y - side // 2)
    crop_right = min(w, crop_left + side)
    crop_bottom = min(h, crop_top + side)

    # Adjust if clamped at borders
    if crop_right - crop_left < side:
        crop_left = max(0, crop_right - side)
    if crop_bottom - crop_top < side:
        crop_top = max(0, crop_bottom - side)

    cropped = rgb_img.crop((crop_left, crop_top, crop_right, crop_bottom))
    return cropped


def generate_synthesized_icon() -> Image.Image:
    """
    Fallback generator if source image is not yet placed by the user.
    Creates a high-resolution Dark Nordic 1024x1024 icon:
    Graphite background #12161A, rounded card #1E252B, border #2C363F,
    and crisp Onsen Mint #5FEDC5 branding.
    """
    size = 1024
    img = Image.new('RGBA', (size, size), (18, 22, 26, 255))
    draw = ImageDraw.Draw(img)

    # Inner soft graphite rounded square
    margin = 56
    draw.rounded_rectangle(
        [margin, margin, size - margin, size - margin],
        radius=180,
        fill=(30, 37, 43, 255),
        outline=(44, 54, 63, 255),
        width=12,
    )

    # Subtle inner gradient / glow
    glow = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse(
        [size // 4, size // 4, 3 * size // 4, 3 * size // 4],
        fill=(95, 237, 197, 24)
    )
    glow = glow.filter(ImageFilter.GaussianBlur(80))
    img = Image.alpha_composite(img, glow)
    draw = ImageDraw.Draw(img)

    # Graduation cap / Sparkle icon above text
    cap_center_x = size // 2
    cap_top_y = 300
    # Diamond cap top
    draw.polygon(
        [
            (cap_center_x, cap_top_y - 65),
            (cap_center_x + 150, cap_top_y),
            (cap_center_x, cap_top_y + 65),
            (cap_center_x - 150, cap_top_y),
        ],
        fill=(95, 237, 197, 255)
    )
    # Skullcap underneath
    draw.chord(
        [cap_center_x - 85, cap_top_y, cap_center_x + 85, cap_top_y + 90],
        start=0,
        end=180,
        fill=(66, 220, 163, 255)
    )
    # Tassel
    draw.line([(cap_center_x + 130, cap_top_y + 8), (cap_center_x + 160, cap_top_y + 80)], fill=(255, 255, 255, 220), width=6)
    draw.ellipse([cap_center_x + 152, cap_top_y + 75, cap_center_x + 168, cap_top_y + 95], fill=(255, 255, 255, 240))

    # Font setup
    font = None
    for font_path in ['C:/Windows/Fonts/segoeuib.ttf', 'C:/Windows/Fonts/arialbd.ttf']:
        if os.path.exists(font_path):
            try:
                font = ImageFont.truetype(font_path, 138)
                break
            except Exception:
                pass
    if not font:
        font = ImageFont.load_default()

    # "TarkApp" text
    text = "TarkApp"
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_x = (size - text_w) // 2
    text_y = 520

    # Draw shadow
    draw.text((text_x + 2, text_y + 4), text, font=font, fill=(0, 0, 0, 140))
    # Draw Mint text
    draw.text((text_x, text_y), text, font=font, fill=(95, 237, 197, 255))

    # Subtitle pill: "ESTONIA"
    sub_font = None
    for font_path in ['C:/Windows/Fonts/segoeuib.ttf', 'C:/Windows/Fonts/arialbd.ttf']:
        if os.path.exists(font_path):
            try:
                sub_font = ImageFont.truetype(font_path, 34)
                break
            except Exception:
                pass

    if sub_font:
        sub_text = "ÕPIME KOOS"
        sub_bbox = draw.textbbox((0, 0), sub_text, font=sub_font)
        sub_w = sub_bbox[2] - sub_bbox[0]
        sub_x = (size - sub_w) // 2
        sub_y = 690
        # Pill background
        pill_pad_x = 28
        pill_pad_y = 10
        draw.rounded_rectangle(
            [sub_x - pill_pad_x, sub_y - pill_pad_y, sub_x + sub_w + pill_pad_x, sub_y + (sub_bbox[3] - sub_bbox[1]) + pill_pad_y + 4],
            radius=20,
            fill=(42, 52, 61, 255),
            outline=(95, 237, 197, 160),
            width=2,
        )
        draw.text((sub_x, sub_y), sub_text, font=sub_font, fill=(148, 163, 184, 255))

    return img.convert('RGB')


def create_adaptive_foreground(base_img: Image.Image) -> Image.Image:
    """
    Android Adaptive Icon Foreground:
    Standard canvas is 1024x1024 RGBA.
    Android launcher masks can clip to circle, squircle, or rounded rect.
    The safe zone is the central 66% circle (diameter ~676px).
    We scale the emblem to fit within 680x680 and place it strictly in the center.
    """
    canvas_size = 1024
    safe_size = 680

    foreground = Image.new('RGBA', (canvas_size, canvas_size), (0, 0, 0, 0))

    # Resize base image to fit safe zone
    emblem = base_img.convert('RGBA')
    emblem = emblem.resize((safe_size, safe_size), Image.Resampling.LANCZOS)

    # Optional: rounded corner mask for emblem so it looks elegant in any launcher
    mask = Image.new('L', (safe_size, safe_size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle([0, 0, safe_size, safe_size], radius=150, fill=255)

    emblem.putalpha(mask)

    offset = (canvas_size - safe_size) // 2
    foreground.paste(emblem, (offset, offset), emblem)
    return foreground


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

    # Remove conflicting background images if present
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
    if src_path:
        print(f"Found source icon at: {src_path}")
        raw_img = Image.open(src_path)
        base_img = auto_crop_graphite_logo(raw_img)
    else:
        print("Source file 'tarkapp_icon_source.png' not found in workspace or user folders.")
        print("Generating crisp Dark Nordic branded TarkApp icon...")
        base_img = generate_synthesized_icon()

    # 1. Standard App Icon (1024x1024)
    icon_1024 = base_img.resize((1024, 1024), Image.Resampling.LANCZOS)
    icon_path = ASSETS_DIR / 'icon.png'
    icon_1024.convert('RGB').save(icon_path, format='PNG', optimize=True)
    print(f"Generated: {icon_path} (1024x1024)")

    # 2. Android Adaptive Foreground Icon (1024x1024 with safe zone)
    adaptive_foreground = create_adaptive_foreground(base_img)
    adaptive_path = ASSETS_DIR / 'adaptive-icon.png'
    adaptive_foreground.save(adaptive_path, format='PNG', optimize=True)
    print(f"Generated: {adaptive_path} (1024x1024 safe zone)")

    # Also keep android-icon-foreground.png in sync
    android_fg_path = ASSETS_DIR / 'android-icon-foreground.png'
    adaptive_foreground.save(android_fg_path, format='PNG', optimize=True)
    print(f"Generated: {android_fg_path} (1024x1024 safe zone)")

    # 3. Splash Icon (512x512)
    splash_path = ASSETS_DIR / 'splash-icon.png'
    splash_icon = base_img.resize((512, 512), Image.Resampling.LANCZOS)
    splash_icon.save(splash_path, format='PNG', optimize=True)
    print(f"Generated: {splash_path} (512x512)")

    # 4. Favicon (48x48)
    favicon_path = ASSETS_DIR / 'favicon.png'
    favicon = base_img.resize((48, 48), Image.Resampling.LANCZOS)
    favicon.save(favicon_path, format='PNG', optimize=True)
    print(f"Generated: {favicon_path} (48x48)")

    # 5. Update app.json
    update_app_json()
    print("All app icons generated and app.json updated successfully!")


if __name__ == '__main__':
    main()
