import sys
import os
import math
import random
import datetime
import logging
from typing import List, Dict, Any, Tuple, Optional, Set

from PIL import Image, ImageDraw, ImageFont, ImageChops

# --- CONFIGURATION ---

WIDTH, HEIGHT = 1080, 1920
CENTER_X = WIDTH // 2
MARGIN_X = 60
PATTERN_SIZE = (800, 975)
FOOTER_URL = "mooseses/TunesBack"

class Colors:
    DARK_BG = "#292929"
    LIGHT_BG = "#efefeb"
    PLACEHOLDER = "#333333"
    TEXT_GREY = "#B3B3B3"
    
    @staticmethod
    def get_age_color(age: int) -> str:
        if age < 30: return "#96c90d"
        if age < 40: return "#dbb603"
        if age < 50: return "#9891fe"
        if age < 80: return "#fe4635"
        return "#f1a2bd"

# --- ASSET MANAGEMENT ---

class AssetManager:
    """Centralizes access to Fonts and Images with Frozen App Support."""
    
    _fonts = {
        'black': "CircularSpotifyText-Black.otf",
        'bold': "CircularSpotifyText-Bold.otf",
        'medium': "CircularSpotifyText-Medium.otf",
        'book': "CircularSpotifyText-Book.otf",
        'light': "CircularSpotifyText-Light.otf"
    }
    
    # Common system fonts available on Linux (in order of preference)
    _linux_fallback_fonts = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",  # Arch Linux path
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/usr/share/fonts/noto/NotoSans-Bold.ttf",
        "/usr/share/fonts/noto/NotoSans-Regular.ttf",
    ]
    
    _font_cache = {}  # Cache loaded fonts to avoid repeated file access

    @staticmethod
    def get_base_path():
        """
        Returns the correct base path for assets whether running from source
        or as a compiled executable (PyInstaller/Flet).
        """
        if getattr(sys, 'frozen', False):
            # Running as compiled app
            # PyInstaller extracts to sys._MEIPASS
            return os.path.join(sys._MEIPASS, "assets")
        else:
            # Running from source
            return os.path.join(os.path.dirname(__file__), "assets")

    @classmethod
    def get_font_path(cls, weight: str):
        # Helper to construct full font path
        filename = cls._fonts.get(weight, cls._fonts['book'])
        return os.path.join(cls.get_base_path(), "fonts", "Spotify-Circular-Font", filename)

    @classmethod
    def _get_fallback_font(cls, size: int) -> ImageFont.FreeTypeFont:
        """Try to load a system TrueType font as fallback (Linux-friendly)."""
        # Check cache first
        cache_key = ('fallback', size)
        if cache_key in cls._font_cache:
            return cls._font_cache[cache_key]
        
        # Try Linux system fonts
        for font_path in cls._linux_fallback_fonts:
            if os.path.exists(font_path):
                try:
                    font = ImageFont.truetype(font_path, size)
                    cls._font_cache[cache_key] = font
                    logging.info(f"Using fallback font: {font_path}")
                    return font
                except Exception:
                    continue
        
        # Try Pillow 10.0+ default (returns TrueType font)
        try:
            font = ImageFont.load_default(size=size)
            cls._font_cache[cache_key] = font
            return font
        except TypeError:
            # Older Pillow doesn't support size parameter
            pass
        
        # Last resort: basic default (may not support all text operations)
        logging.warning("No TrueType fallback font found, text rendering may be limited")
        return ImageFont.load_default()

    @classmethod
    def get_font(cls, size: int, weight: str = 'book') -> ImageFont.FreeTypeFont:
        # Check cache first
        cache_key = (weight, size)
        if cache_key in cls._font_cache:
            return cls._font_cache[cache_key]
        
        try:
            # Use the robust path resolver
            path = cls.get_font_path(weight)
            font = ImageFont.truetype(path, size)
            cls._font_cache[cache_key] = font
            return font
        except OSError as e:
            logging.error(f"Font not found at {path}: {e}")
            return cls._get_fallback_font(size)

    @classmethod
    def get_icon(cls, is_light_theme: bool) -> Image.Image:
        filename = "spo_icon_dark.png" if is_light_theme else "spo_icon_light.png"
        path = os.path.join(cls.get_base_path(), filename)
        if os.path.exists(path):
            return Image.open(path).convert("RGBA")
        logging.warning(f"Icon not found at {path}")
        return None

# --- DRAWING UTILITIES ---

class DrawUtils:
    @staticmethod
    def _safe_textlength(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> float:
        """Safely get text length, with fallback for bitmap fonts."""
        result = 0.0
        try:
            result = draw.textlength(text, font)
        except (AttributeError, TypeError):
            # Fallback for bitmap fonts that don't support textlength
            try:
                bbox = draw.textbbox((0, 0), text, font=font)
                result = bbox[2] - bbox[0]
            except Exception:
                pass
        
        # If we still don't have a valid result, estimate based on font size and character count
        if result <= 0:
            try:
                # Try to get font size for better estimation
                font_size = getattr(font, 'size', None)
                if font_size:
                    result = len(text) * font_size * 0.6  # Approximate character width
                else:
                    result = len(text) * 20  # Fallback estimate
            except Exception:
                result = len(text) * 20
        
        return max(result, 1.0)  # Never return 0 or negative
    
    @staticmethod
    def _safe_textbbox(draw: ImageDraw.ImageDraw, xy: Tuple[int, int], text: str, 
                       font: ImageFont.FreeTypeFont, anchor: str = None, 
                       stroke_width: int = 0) -> Tuple[int, int, int, int]:
        """Safely get text bounding box, with fallback for bitmap fonts."""
        try:
            return draw.textbbox(xy, text, font=font, anchor=anchor, stroke_width=stroke_width)
        except Exception:
            # Fallback: estimate bounding box
            try:
                w = DrawUtils._safe_textlength(draw, text, font)
                h = 20  # Default height estimate
                if hasattr(font, 'size'):
                    h = font.size
                elif hasattr(font, 'getbbox'):
                    bbox = font.getbbox(text)
                    if bbox:
                        h = bbox[3] - bbox[1]
                return (xy[0], xy[1], xy[0] + int(w), xy[1] + int(h))
            except Exception:
                return (xy[0], xy[1], xy[0] + len(text) * 10, xy[1] + 20)
    
    @staticmethod
    def truncate(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: float) -> str:
        if DrawUtils._safe_textlength(draw, text, font) <= max_width: 
            return text
        ellipsis = "..."
        target = max_width - DrawUtils._safe_textlength(draw, ellipsis, font)
        while len(text) > 0 and DrawUtils._safe_textlength(draw, text, font) > target:
            text = text[:-1]
        return text + ellipsis

    @staticmethod
    def draw_flat_text(target_img: Image.Image, xy: Tuple[int, int], text: str, 
                       font: ImageFont.FreeTypeFont, fill: Any, stretch_factor: float = 1.3, 
                       anchor: str = None, stroke_width: int = 0, stroke_fill: Any = None, 
                       force_width: int = None, kerning: int = 0) -> Tuple[int, int]:
        """
        Renders text. Draws directly for standard text to preserve quality. 
        Uses an intermediate layer for manual kerning or stretching.
        """
        # Path 1: Standard High-Quality Text (No effects)
        if kerning == 0 and stretch_factor == 1.0 and force_width is None:
            draw = ImageDraw.Draw(target_img)
            try:
                draw.text(xy, text, font=font, fill=fill, anchor=anchor, stroke_width=stroke_width, stroke_fill=stroke_fill)
            except TypeError:
                # Fallback for fonts that don't support anchor/stroke
                draw.text(xy, text, font=font, fill=fill)
            bbox = DrawUtils._safe_textbbox(draw, xy, text, font, anchor, stroke_width)
            return bbox[2]-bbox[0], bbox[3]-bbox[1]

        # Path 2: Custom Text (Stretched/Tightened)
        dummy = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        
        # Calculate Dimensions
        if kerning == 0:
            w_raw = DrawUtils._safe_textlength(dummy, text, font)
        else:
            w_raw = 0
            char_widths = []
            for char in text:
                cw = DrawUtils._safe_textlength(dummy, char, font)
                char_widths.append(cw)
                w_raw += cw + kerning
            w_raw = max(1, w_raw - kerning if w_raw > 0 else 1)

        bbox = DrawUtils._safe_textbbox(dummy, (0, 0), text, font, stroke_width=stroke_width)
        h_raw = bbox[3] - bbox[1] + 20 

        # Render Layer
        txt_layer = Image.new("RGBA", (max(1, int(w_raw)), max(1, h_raw)), (0, 0, 0, 0))
        d = ImageDraw.Draw(txt_layer)
        
        try:
            if kerning == 0:
                d.text((0, 0), text, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill)
            else:
                cx = 0
                for i, char in enumerate(text):
                    d.text((cx, 0), char, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill)
                    cx += char_widths[i] + kerning
        except TypeError:
            # Fallback for fonts that don't support stroke
            if kerning == 0:
                d.text((0, 0), text, font=font, fill=fill)
            else:
                cx = 0
                for i, char in enumerate(text):
                    d.text((cx, 0), char, font=font, fill=fill)
                    cx += char_widths[i] + kerning

        # Stretch & Paste
        new_w = force_width if force_width else max(1, int(w_raw * stretch_factor))
        stretched = txt_layer.resize((int(new_w), max(1, h_raw)), resample=Image.BICUBIC)

        x, y = xy
        if anchor:
            if "m" in anchor[0]: x -= new_w // 2
            elif "r" in anchor[0]: x -= new_w    
            if "m" in anchor[1]: y -= h_raw // 2
            elif "b" in anchor[1]: y -= h_raw    

        target_img.paste(stretched, (int(x), int(y)), stretched)
        return new_w, h_raw

# --- PATTERN GENERATORS ---

class PatternGenerator:
    @staticmethod
    def _apply_wave(img: Image.Image, amp=30, freq=0.01) -> Image.Image:
        out = Image.new("RGB", img.size, (255, 255, 255))
        pix_in, pix_out = img.load(), out.load()
        w, h = img.size
        for y in range(h):
            shift = int(amp * math.sin(y * freq))
            for x in range(w):
                pix_out[x, y] = pix_in[(x - shift) % w, y]
        return out

    @staticmethod
    def weezer() -> Image.Image:
        img = Image.new("RGB", PATTERN_SIZE, Colors.DARK_BG)
        draw = ImageDraw.Draw(img)
        rw, rh = PATTERN_SIZE[0] / 17, PATTERN_SIZE[1] / 3
        for r in range(3):
            for c in range(17):
                if (r + c) % 2 == 0:
                    draw.rectangle([c*rw, r*rh, c*rw+rw+1, r*rh+rh+1], fill=Colors.LIGHT_BG)
        return img

    @staticmethod
    def paramore() -> Image.Image:
        img = Image.new("RGB", PATTERN_SIZE, Colors.DARK_BG)
        draw = ImageDraw.Draw(img)
        cols, rows, r = 5, 6, 40
        sp_x, sp_y = (PATTERN_SIZE[0]-2*r)/(cols-1), (PATTERN_SIZE[1]-2*r)/(rows-1)
        for row in range(rows):
            y = r + row * sp_y
            for col in range(cols):
                draw.ellipse([r+col*sp_x-r, y-r, r+col*sp_x+r, y+r], fill=Colors.LIGHT_BG)
            if row < rows - 1:
                for ci in range(cols - 1):
                    xi, yi = r + ci*sp_x + sp_x/2, y + sp_y/2
                    draw.ellipse([xi-r, yi-r, xi+r, yi+r], fill=Colors.LIGHT_BG)
        return img

    @staticmethod
    def sabrina() -> Image.Image:
        img = Image.new("RGB", PATTERN_SIZE, Colors.LIGHT_BG)
        draw = ImageDraw.Draw(img)
        cx, cy, curr_r = 860, PATTERN_SIZE[1] // 2, 1000
        is_blk = True
        while curr_r > 0:
            fill = Colors.DARK_BG if is_blk else Colors.LIGHT_BG
            draw.ellipse([cx-curr_r, cy-curr_r, cx+curr_r, cy+curr_r], fill=fill)
            curr_r -= 1000/24
            is_blk = not is_blk
        return img

    @staticmethod
    def jessie() -> Image.Image:
        base = Image.new("RGB", PATTERN_SIZE, Colors.LIGHT_BG)
        draw = ImageDraw.Draw(base)
        sz = 100
        for r in range(PATTERN_SIZE[1]//sz+2):
            for c in range(PATTERN_SIZE[0]//sz+2):
                if (r+c) % 2 == 1:
                    draw.rectangle([c*sz, r*sz, c*sz+sz, r*sz+sz], fill=Colors.DARK_BG)
        return PatternGenerator._apply_wave(base, 100, 0.008)

    @staticmethod
    def geometric_illusion_v2() -> Image.Image:
        w, h = 260, 130
        base = Image.new("RGB", (w, h), Colors.LIGHT_BG)
        inv = Image.new("RGB", (w, h), Colors.DARK_BG)
        db, di = ImageDraw.Draw(base), ImageDraw.Draw(inv)
        
        sw, period = 38, 78
        for x in range(-55 % period - period, w, period):
            db.rectangle([x, 0, x + sw, h], fill=Colors.DARK_BG)
            di.rectangle([x, 0, x + sw, h], fill=Colors.LIGHT_BG)
            
        mask = Image.new("L", (w, h), 0)
        dm = ImageDraw.Draw(mask)
        cx, cy, tx, ty = -w*0.4, -h*2.6, w*0.35, h*0.2
        r = math.hypot(tx - cx, ty - cy)
        thick = sw * 1.8
        dm.ellipse([cx - (r+thick/2), cy - (r+thick/2), cx + (r+thick/2), cy + (r+thick/2)], fill=255)
        dm.ellipse([cx - (r-thick/2), cy - (r-thick/2), cx + (r-thick/2), cy + (r-thick/2)], fill=0)
        return Image.composite(inv, base, mask)

    @staticmethod
    def op_art_ovals(scale: float = 1.0) -> Image.Image:
        W, H = 460, 700
        c_bg, c_fg = Colors.LIGHT_BG, Colors.DARK_BG
        sw = 55
        
        base = Image.new("RGB", (W, H), c_bg)
        inv = Image.new("RGB", (W, H), c_fg)
        db, di = ImageDraw.Draw(base), ImageDraw.Draw(inv)
        
        for x in range(sw, W, sw * 2):
            db.rectangle([x, 0, min(x + sw, W), H], fill=c_fg)
            di.rectangle([x, 0, min(x + sw, W), H], fill=c_bg)

        mask = Image.new("L", (W, H), 0)
        dm = ImageDraw.Draw(mask)
        
        ox, oy = W + 390, H // 2 - 35
        orx, ory = 850, 430
        dm.ellipse([ox - orx, oy - ory, ox + orx, oy + ory], fill=255)
        
        ix, iy = W + 570, H // 2 - 35
        irx, iry = 905, 360
        dm.ellipse([ix - irx, iy - iry, ix + irx, iy + iry], fill=0)

        final = Image.composite(inv, base, mask)
        if scale != 1.0:
            final = final.resize((int(W * scale), int(H * scale)), resample=Image.BICUBIC)
        return final

# --- CARD RENDERER ---

class CardRenderer:
    def __init__(self, bg_color: str = Colors.DARK_BG):
        self.img = Image.new("RGBA", (WIDTH, HEIGHT), bg_color)
        self.draw = ImageDraw.Draw(self.img)
        self.bg_color = bg_color
        self.is_light = (bg_color == Colors.LIGHT_BG)

    def add_header(self, text: str, y_pos: int = 115, size: int = 60, bg_box: str = None, text_col: str = None):
        font = AssetManager.get_font(size, 'black')
        col = text_col if text_col else (Colors.DARK_BG if bg_box else (Colors.DARK_BG if self.is_light else Colors.LIGHT_BG))
        
        if bg_box:
            dummy = ImageDraw.Draw(Image.new("L", (1,1)))
            text_width = DrawUtils._safe_textlength(dummy, text, font)
            box_w = max(text_width * 1.3 + 60, 200)  # Ensure minimum width
            box_h = 90
            bx = (WIDTH - box_w) // 2
            self.draw.rectangle((bx, y_pos, bx + box_w, y_pos + box_h), fill=bg_box)
            y_pos += (box_h // 2) + 12
            DrawUtils.draw_flat_text(self.img, (CENTER_X, y_pos), text, font, col, 1.3, "mm", kerning=-2)
        else:
            DrawUtils.draw_flat_text(self.img, (CENTER_X, y_pos), text, font, col, 1.3, "mt", kerning=-2)

    def add_footer(self):
        font = AssetManager.get_font(50, 'bold')
        color = Colors.DARK_BG if self.is_light else Colors.TEXT_GREY
        
        logo = AssetManager.get_icon(self.is_light)
        if logo:
            logo = logo.resize((105, 105), Image.Resampling.LANCZOS)
            self.img.paste(logo, (60, HEIGHT - 150), logo)
            
        w = DrawUtils._safe_textlength(self.draw, FOOTER_URL, font)
        self.draw.text((WIDTH - w - 60, HEIGHT - 120), FOOTER_URL, font=font, fill=color)

    def get_image(self) -> Image.Image:
        self.add_footer()
        return self.img

# --- CARD GENERATION LOGIC ---

def draw_top_albums(items: List[Dict]) -> Image.Image:
    card = CardRenderer(Colors.LIGHT_BG)
    card.add_header("My Top Albums", y_pos=80, bg_box=Colors.DARK_BG, text_col="#ddba13")
    
    # Background & Grid
    cy, gap = 280, 10
    eff_margin = MARGIN_X + 20
    total_w = WIDTH - (eff_margin * 2)
    w_big = (total_w - gap) // 2
    w_small = (total_w - 2*gap) // 3
    
    pat = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,0))
    pd = ImageDraw.Draw(pat)
    sp_x, r = WIDTH / 5, 60
    for row in range(8):
        y = cy + row * (w_big + w_small + gap) / 7
        count, offset = (5, sp_x/2) if row % 2 == 0 else (6, 0)
        for c in range(count):
            cx = c * sp_x + offset
            pd.ellipse([cx-r, y-r, cx+r, y+r], fill=Colors.DARK_BG)
    card.img.paste(pat, (0, 0), pat)

    card.draw.rectangle((eff_margin, cy, eff_margin + total_w, cy + w_big + gap + w_small), fill=Colors.DARK_BG)
    coords = [
        (eff_margin, cy, w_big, w_big), (eff_margin + w_big + gap, cy, w_big, w_big),
        (eff_margin, cy + w_big + gap, w_small, w_small),
        (eff_margin + w_small + gap, cy + w_big + gap, w_small, w_small),
        (eff_margin + (w_small + gap)*2, cy + w_big + gap, w_small, w_small)
    ]
    
    for i, (x, y, w, h) in enumerate(coords):
        if i >= len(items): break
        if img := items[i].get('image'):
            card.img.paste(img.resize((int(w), int(h))), (int(x), int(y)))
        else:
            card.draw.rectangle((x, y, x+w, y+h), fill=Colors.PLACEHOLDER)
        
        ts = 60
        card.draw.rectangle((x+w-ts, y+h-ts, x+w, y+h), fill=Colors.LIGHT_BG)
        DrawUtils.draw_flat_text(card.img, (x+w-ts/2, y+h-ts/2), str(i+1), AssetManager.get_font(40, 'black'), Colors.DARK_BG, 1.3, "mm", kerning=0)

    # List
    ly = cy + w_big + gap + w_small + 100
    for i, item in enumerate(items[:5]):
        y = ly + (i * 120)
        DrawUtils.draw_flat_text(card.img, (eff_margin, y), str(i+1), AssetManager.get_font(50, 'black'), Colors.DARK_BG, 1.3, "lt", kerning=0)
        
        nm = DrawUtils.truncate(card.draw, item['name'], AssetManager.get_font(45, 'black'), 750)
        DrawUtils.draw_flat_text(card.img, (eff_margin + 60, y), nm, AssetManager.get_font(45, 'black'), Colors.DARK_BG, 1.2, "lt", kerning=0)
        
        sub = DrawUtils.truncate(card.draw, item.get('sub', ''), AssetManager.get_font(35), 750)
        card.draw.text((eff_margin + 60, y+55), sub, font=AssetManager.get_font(35), fill="#444")
        
    return card.get_image()

def draw_top_genres(genres: List[str]) -> Image.Image:
    card = CardRenderer(Colors.LIGHT_BG)
    
    # Background
    pat = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,0))
    pd = ImageDraw.Draw(pat)
    for x, y, r in [(850, 1100, 60), (980, 1250, 70), (800, 1350, 50), (1020, 1450, 65), (900, 1600, 55), (750, 1700, 45), (950, 950, 55)]:
        pd.ellipse((x-r, y-r, x+r, y+r), fill=Colors.DARK_BG)
    for x, y, r in [(700, 1450, 50), (850, 1550, 60), (650, 1650, 45), (800, 1750, 55), (950, 1700, 65), (1050, 1600, 50)]:
        pd.ellipse((x-r, y-r, x+r, y+r), fill="#fe4635")
    pd.arc((100, 1750, 900, 1950), 180, 360, fill=Colors.DARK_BG, width=3)
    pd.line((300, 1850, 1000, 1700), fill=Colors.DARK_BG, width=3)
    card.img.paste(pat, (0,0), pat)

    # Bubbles
    box_w, box_x = 780, 220
    assets = []
    f_src = AssetManager.get_font(300, 'black')
    genre_kerning = -2

    for g in genres[:5]:
        d = ImageDraw.Draw(Image.new("RGBA", (1,1)))
        
        # Manual width calc
        w_text = 0
        char_widths = []
        for char in g:
            cw = DrawUtils._safe_textlength(d, char, f_src)
            char_widths.append(cw)
            w_text += cw + genre_kerning
        w_text = max(1, w_text - genre_kerning if w_text > 0 else 1)
        
        bb = DrawUtils._safe_textbbox(d, (0,0), g, f_src)
        h = bb[3]-bb[1]+20
        
        txt = Image.new("RGBA", (int(w_text), h), (0,0,0,0))
        d_txt = ImageDraw.Draw(txt)
        
        cx = 0
        for i, char in enumerate(g):
            d_txt.text((cx, 0), char, font=f_src, fill=Colors.LIGHT_BG)
            cx += char_widths[i] + genre_kerning
        
        squished = txt.resize((int(w_text*1.3), h), resample=Image.BICUBIC)
        target_w = box_w - 10
        ratio = target_w / squished.width
        new_h = int(h * ratio)
        if new_h > 230:
            ratio = 230 / h
            target_w = int(squished.width * ratio)
            new_h = 230
            
        final_txt = squished.resize((int(target_w), int(new_h)), resample=Image.BICUBIC)
        box = Image.new("RGBA", (int(target_w + 10 if new_h == 230 else box_w), int(new_h + 60)), Colors.DARK_BG)
        box.paste(final_txt, (5, 30), final_txt)
        assets.append(box)

    # Layout
    gap_size = 35 
    DrawUtils.draw_flat_text(card.img, (CENTER_X, (HEIGHT - sum(a.height + gap_size for a in assets)) // 2 - 100), "My Top Genres", AssetManager.get_font(60, 'black'), Colors.DARK_BG, 1.3, "mt", kerning=-2)
    
    cy = (HEIGHT - sum(a.height + gap_size for a in assets)) // 2 + 20
    for i, box in enumerate(assets):
        DrawUtils.draw_flat_text(card.img, (box_x - 30, cy + box.height//2), str(i+1), AssetManager.get_font(100, 'black'), Colors.DARK_BG, 1.4, "rm", kerning=-2)
        card.img.paste(box, (box_x, int(cy)))
        cy += box.height + gap_size
        
    return card.get_image()

def draw_listening_age(age: int, label: str) -> Image.Image:
    card = CardRenderer(Colors.LIGHT_BG)
    DrawUtils.draw_flat_text(card.img, (CENTER_X, 550), "My Listening Age", AssetManager.get_font(60, 'black'), Colors.DARK_BG, 1.3, "mm", kerning=-2)
    DrawUtils.draw_flat_text(card.img, (CENTER_X, 900), str(age), AssetManager.get_font(500, 'black'), Colors.get_age_color(age), 1.4, "mm", stroke_width=4, stroke_fill=Colors.DARK_BG, kerning=0)
    
    # Era Text
    cur = datetime.datetime.now().year
    peak = (cur - age) + 18
    dec = (peak // 10) * 10
    prefix = "Early" if peak%10 < 4 else ("Mid" if peak%10 < 7 else "Late")
    txt_parts = [("Since I was into music from ", 'book'), ("the ", 'book'), (f"{prefix} ", 'black'), (f"{str(dec)[-2:]}s", 'black')]
    
    total_w = sum(DrawUtils._safe_textlength(card.draw, t, AssetManager.get_font(45, w)) for t, w in txt_parts)
    cx = (WIDTH - total_w) / 2
    for txt, weight in txt_parts:
        font = AssetManager.get_font(45, weight)
        DrawUtils.draw_flat_text(card.img, (cx, 1300), txt, font, Colors.DARK_BG, 1.0, "lm", kerning=0)
        cx += DrawUtils._safe_textlength(card.draw, txt, font)
        
    return card.get_image()

def draw_top_songs(items: List[Dict]) -> Image.Image:
    card = CardRenderer(Colors.DARK_BG)
    pat = PatternGenerator.geometric_illusion_v2().resize((int(260*1.9), int(130*1.9)), Image.Resampling.LANCZOS)
    card.img.paste(pat, (0,0))
    card.add_header("My Top Songs", y_pos=310, bg_box=Colors.LIGHT_BG)

    sy = 570
    for i, item in enumerate(items[:5]):
        y = sy + (i * 230)
        DrawUtils.draw_flat_text(card.img, (120, y), str(i+1), AssetManager.get_font(100, 'black'), Colors.LIGHT_BG, 1.3, "mm", kerning=0)
        
        if item.get('image'):
            card.img.paste(item['image'].resize((180, 180)), (220, y - 90))
        else:
            card.draw.rectangle((220, y - 90, 400, y + 90), fill=Colors.PLACEHOLDER)
            
        nm = DrawUtils.truncate(card.draw, item['name'], AssetManager.get_font(55, 'black'), (WIDTH - 490)/1.15)
        DrawUtils.draw_flat_text(card.img, (440, y - 20), nm, AssetManager.get_font(55, 'black'), Colors.LIGHT_BG, 1.15, "lm", kerning=-2)
        
        sub = DrawUtils.truncate(card.draw, item.get('sub', ''), AssetManager.get_font(40), WIDTH - 490)
        card.draw.text((440, y + 45), sub, font=AssetManager.get_font(40), fill=Colors.LIGHT_BG)
        
    return card.get_image()

def draw_top_song_single(item: Dict) -> Image.Image:
    card = CardRenderer(Colors.DARK_BG)
    pat = PatternGenerator.op_art_ovals(scale=1.3)
    card.img.paste(pat, (WIDTH - pat.width, 0))

    sz, y = 655, 245
    if item.get('image'):
        card.img.paste(item['image'].resize((sz, sz)), ((WIDTH-sz)//2, y))
    else:
        card.draw.rectangle(((WIDTH-sz)//2, y, (WIDTH+sz)//2, y+sz), fill=Colors.PLACEHOLDER)
        
    DrawUtils.draw_flat_text(card.img, (CENTER_X, y+sz+150), "My Top Song", AssetManager.get_font(50, 'black'), Colors.LIGHT_BG, 1.4, "mm", kerning=-2)
    
    safe_w = WIDTH - 120
    nm = DrawUtils.truncate(card.draw, item['name'], AssetManager.get_font(90, 'black'), safe_w / 1.4) 
    DrawUtils.draw_flat_text(card.img, (CENTER_X, y+sz+280), nm, AssetManager.get_font(90, 'black'), Colors.LIGHT_BG, 1.4, "mm", kerning=-2)
    
    sub = DrawUtils.truncate(card.draw, item.get('sub', ''), AssetManager.get_font(50), safe_w)
    card.draw.text((CENTER_X, y+sz+380), sub, font=AssetManager.get_font(50), fill=Colors.LIGHT_BG, anchor="mm")
    
    DrawUtils.draw_flat_text(card.img, (CENTER_X, y+sz+500), "Total Plays", AssetManager.get_font(40, 'medium'), Colors.LIGHT_BG, 1.0, "mm", kerning=0)
    val = f"{int(item.get('count', 0)):,}"
    DrawUtils.draw_flat_text(card.img, (CENTER_X, y+sz+580), val, AssetManager.get_font(80, 'black'), Colors.LIGHT_BG, 1.3, "mm", kerning=0)
    
    return card.get_image()

def draw_minutes_card(minutes: int) -> Image.Image:
    card = CardRenderer(Colors.DARK_BG)
    DrawUtils.draw_flat_text(card.img, (CENTER_X, 600), "My Minutes Listened", AssetManager.get_font(60, 'black'), Colors.LIGHT_BG, 1.3, "mm", kerning=-2)
    
    val_str = f"{minutes:,}"
    digits = len(str(minutes))
    dynamic_width = min(WIDTH, int((WIDTH / 4) * max(2, digits))) 
    
    DrawUtils.draw_flat_text(card.img, (CENTER_X, 850), val_str, AssetManager.get_font(300, 'black'), 
                             "#9690fd", 1.0, "mm", stroke_width=5, stroke_fill=Colors.LIGHT_BG, 
                             force_width=dynamic_width, kerning=0)
    
    DrawUtils.draw_flat_text(card.img, (CENTER_X, 1050), f"That's {int(minutes / 1440)} days.", AssetManager.get_font(50, 'medium'), Colors.LIGHT_BG, 1.0, "mm", kerning=0)
    return card.get_image()

def draw_summary_card(data: Dict[str, Any]) -> Image.Image:
    # Pattern
    p_name = random.choice(["weezer", "paramore", "sabrina", "jessie"])
    is_dark = p_name in ["weezer", "paramore"]
    card = CardRenderer(Colors.DARK_BG if is_dark else Colors.LIGHT_BG)
    card.img.paste(getattr(PatternGenerator, p_name)(), (WIDTH - 800, 0))
    c_txt, c_sub = (Colors.LIGHT_BG, "#BBB") if is_dark else (Colors.DARK_BG, "#444")

    # Background Year
    yr = data.get('year_label', "2025")
    f_yr = AssetManager.get_font(290, 'black')
    
    dummy = ImageDraw.Draw(Image.new("L", (1,1)))
    chars = []
    x = 16
    for c in yr:
        w = DrawUtils._safe_textlength(dummy, c, f_yr)
        chars.append((c, x, w))
        x += w - 47
    
    mask = Image.new("L", (max(1, int(x + 50)), 350), 0)
    dm = ImageDraw.Draw(mask)
    for c, cx, _ in chars: dm.text((cx, 10), c, font=f_yr, fill=255)
    
    dilated = mask.copy()
    dd = ImageDraw.Draw(dilated)
    for c, cx, _ in chars:
        try:
            dd.text((cx, 10), c, font=f_yr, fill=255, stroke_width=6, stroke_fill=255)
        except TypeError:
            # Fallback for fonts that don't support stroke
            dd.text((cx, 10), c, font=f_yr, fill=255)
    outline = ImageChops.subtract(dilated, mask)
    
    fill_col = Colors.get_age_color(data.get('age_data', {}).get('age', 25))
    final_yr = Image.new("RGBA", mask.size, (0,0,0,0))
    df = ImageDraw.Draw(final_yr)
    final_yr.paste(c_txt, (0,0), outline)
    for c, cx, _ in chars: df.text((cx, 10), c, font=f_yr, fill=fill_col)
    
    try:
        bbox = final_yr.getbbox()
        if bbox:
            final_yr = final_yr.crop(bbox)
    except Exception as e:
        logging.warning(f"Could not crop year image: {e}")
    
    final_yr = final_yr.resize((max(1, int(final_yr.width * 1.6)), max(1, final_yr.height)), Image.BICUBIC)
    rotated = final_yr.rotate(90, expand=True)
    card.img.paste(rotated, (10, 0), rotated)

    # Top Artist
    ax, ay, asz = 220, 110, 750
    card.draw.rectangle((ax-6, ay-6, ax+asz+6, ay+asz+6), fill=c_txt)
    if art := data.get('top_artist', {}).get('image'):
        card.img.paste(art.resize((asz, asz)), (ax, ay))
    else:
        card.draw.rectangle((ax, ay, ax+asz, ay+asz), fill="#222")

    # Lists
    y = ay + asz + 180
    def draw_list(x, title, items):
        card.draw.text((x, y), title, font=AssetManager.get_font(40, 'medium'), fill=c_sub)
        for i, item in enumerate(items[:5]):
            nm = DrawUtils.truncate(card.draw, item['name'], AssetManager.get_font(40, 'bold'), 450)
            card.draw.text((x, y+60+i*55), f"{i+1}  {nm}", font=AssetManager.get_font(40, 'bold'), fill=c_txt)
            
    draw_list(MARGIN_X, "Top Artists", data.get('top_artists_list', []))
    draw_list(CENTER_X + 30, "Top Songs", data.get('top_songs', []))
    
    # Stats
    ys = y + 420
    card.draw.text((MARGIN_X, ys), "Minutes Listened", font=AssetManager.get_font(40, 'medium'), fill=c_sub)
    card.draw.text((MARGIN_X, ys+60), f"{data.get('total_minutes',0):,}", font=AssetManager.get_font(80, 'black'), fill=c_txt)
    card.draw.text((CENTER_X + 30, ys), "Top Genre", font=AssetManager.get_font(40, 'medium'), fill=c_sub)
    card.draw.text((CENTER_X + 30, ys+60), data.get('genres', ["Unknown"])[0], font=AssetManager.get_font(80, 'black'), fill=c_txt)
    
    return card.get_image()

# --- ORCHESTRATOR ---

def generate_card_stack(data: Dict[str, Any]) -> List[Image.Image]:
    cards = []
    
    if data.get('top_albums'):
        logging.info("Generating: Top Albums")
        img = draw_top_albums(data['top_albums'])
        img.info['card_name'] = "Top_Albums"
        cards.append(img)

    if data.get('genres'):
        logging.info("Generating: Genres")
        img = draw_top_genres(data['genres'])
        img.info['card_name'] = "Top_Genres"
        cards.append(img)

    if data.get('age_data'):
        logging.info("Generating: Listening Age")
        img = draw_listening_age(data['age_data']['age'], data['age_data']['label'])
        img.info['card_name'] = "Listening_Age"
        cards.append(img)

    if data.get('top_songs'):
        logging.info("Generating: Top Songs List")
        img1 = draw_top_songs(data['top_songs'])
        img1.info['card_name'] = "Top_Songs_List"
        cards.append(img1)
        
        logging.info("Generating: Top Song Single")
        img2 = draw_top_song_single(data['top_songs'][0])
        img2.info['card_name'] = "Top_Song_Single"
        cards.append(img2)

    if data.get('total_minutes'):
        logging.info("Generating: Minutes Listened")
        img = draw_minutes_card(data['total_minutes'])
        img.info['card_name'] = "Minutes_Listened"
        cards.append(img)

    logging.info("Generating: Summary Card")
    img = draw_summary_card(data)
    img.info['card_name'] = "Summary"
    cards.append(img)
    
    return cards

def save_card_stack(images: List[Image.Image], output_path: str, indices: Optional[Set[int]] = None) -> int:
    if not os.path.exists(output_path):
        os.makedirs(output_path)
    
    count = 0
    save_indices = indices if indices is not None else range(len(images))
    
    for i in save_indices:
        if i < len(images):
            try:
                img = images[i]
                base_name = img.info.get('card_name', f"Wrapped_{i+1}")
                ts = datetime.datetime.now().strftime("%H%M%S")
                filename = f"TunesBack_{base_name}_{ts}.jpg"
                full_path = os.path.join(output_path, filename)
                img.convert("RGB").save(full_path, "JPEG", quality=95)
                logging.info(f"Saved: {full_path}")
                count += 1
            except Exception as e:
                logging.error(f"Failed to save image {i}: {e}")
                
    return count