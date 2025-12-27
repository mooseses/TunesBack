from __future__ import annotations

import sys
import os
import threading
import traceback
import datetime
import base64
import platform
import urllib.parse
import urllib.request
import logging
import subprocess
from pathlib import Path
from typing import Optional, Tuple, Dict, List, Set, Any
from dataclasses import dataclass, field
from collections import defaultdict
from io import BytesIO

# --- Third-party Imports ---
import flet as ft
import pandas as pd
import mutagen
from PIL import Image
from dateutil import parser

# --- Local Imports ---
sys.path.insert(0, str(Path(__file__).parent / "libpytunes"))
try:
    from libpytunes import Library
except ImportError:
    print("Error: libpytunes not found. Please ensure the submodule is present.")
    Library = None

import generate_wrapped
import listening_age_algorithm

# ==========================================
# CONFIGURATION & THEME
# ==========================================

APP_NAME = "TunesBack"
IS_WINDOWS = platform.system() == "Windows"
IS_MACOS = platform.system() == "Darwin"
IS_LINUX = platform.system() == "Linux"

class Theme:
    SIDEBAR_BG = "surfaceVariant"
    CONTENT_BG = "background"
    CARD_BG = "secondaryContainer"
    SUBTEXT = "outline"
    
    PAD_LEFT = 50
    PAD_RIGHT = 30
    KPI_HEIGHT = 140
    SIDEBAR_WIDTH = 320
    BUTTON_HEIGHT = 50
    TOGGLE_WIDTH = 280
    
    MS_TO_HOURS = 3.6e6
    MS_TO_MINS = 60000
    MS_TO_DAYS = 8.64e7
    
    UNIT_HOURS = "Hours"
    UNIT_MINUTES = "Minutes"
    UNIT_DAYS = "Days"

# ==========================================
# LOGGING SETUP
# ==========================================

class StreamToLogger(object):
    def __init__(self, logger, log_level=logging.INFO):
        self.logger = logger
        self.log_level = log_level

    def write(self, buf):
        for line in buf.rstrip().splitlines():
            self.logger.log(self.log_level, line.rstrip())

    def flush(self):
        pass

def get_log_path() -> str:
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        log_dir = os.path.join(base, APP_NAME, "Logs")
    elif system == "Darwin":
        log_dir = os.path.expanduser(f"~/Library/Logs/{APP_NAME}")
    else:
        log_dir = os.path.expanduser(f"~/.cache/{APP_NAME}/logs")
    
    os.makedirs(log_dir, exist_ok=True)
    return os.path.join(log_dir, "tunesback.log")

def configure_dynamic_logging(enable: bool, mode: str = 'w'):
    logger = logging.getLogger()
    
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()

    if enable:
        try:
            log_file = get_log_path()
            file_handler = logging.FileHandler(log_file, mode=mode, encoding='utf-8')
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s')
            file_handler.setFormatter(formatter)
            
            logger.addHandler(file_handler)
            logger.setLevel(logging.INFO)
            
            sys.stdout = StreamToLogger(logger, logging.INFO)
            sys.stderr = StreamToLogger(logger, logging.ERROR)
            
            action = "Overwriting" if mode == 'w' else "Appending to"
            logging.info(f"--- LOG START ({action} log file) ---")
        except Exception as e:
            print(f"Failed to setup logging: {e}")
    else:
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__
        logger.addHandler(logging.NullHandler())
        logger.setLevel(logging.CRITICAL)

# ==========================================
# DATA MODELS
# ==========================================

@dataclass
class EntityStats:
    count: int = 0
    time: float = 0.0
    skip: int = 0
    added: Optional[datetime.datetime] = None
    location: Optional[str] = None
    year: Optional[int] = None
    pids: Set[str] = field(default_factory=set) 

@dataclass
class LibraryData:
    artists: Dict[str, EntityStats] = field(default_factory=lambda: defaultdict(EntityStats))
    albums: Dict[Tuple[str, str], EntityStats] = field(default_factory=lambda: defaultdict(EntityStats))
    songs: Dict[Tuple[str, str], EntityStats] = field(default_factory=lambda: defaultdict(EntityStats))
    genres: Dict[str, EntityStats] = field(default_factory=lambda: defaultdict(EntityStats))
    years: Dict[int, EntityStats] = field(default_factory=lambda: defaultdict(EntityStats)) 
    master_pid_map: Dict[str, Dict] = field(default_factory=dict)
    total_time: float = 0.0
    error: Optional[str] = None

# ==========================================
# UTILITIES
# ==========================================

def resolve_path(file_uri: str) -> Optional[str]:
    if not file_uri:
        return None
        
    try:
        parsed = urllib.parse.urlparse(file_uri)
        host = parsed.netloc
        local_path = urllib.request.url2pathname(parsed.path)
        
        if IS_WINDOWS and host and host.lower() != 'localhost':
            if not local_path.startswith("\\"):
                local_path = "\\" + local_path
            path = f"\\\\{host}{local_path}"
            return path
        
        # Linux GVFS handling for network shares (SMB/CIFS)
        if IS_LINUX and host and host.lower() != 'localhost':
            # GVFS mounts network shares at /run/user/<uid>/gvfs/smb-share:server=<host>,share=<share>/...
            clean_path = local_path.lstrip(os.sep)
            parts = clean_path.split(os.sep)
            
            if parts:
                share_name_from_uri = parts[0]  # Original share name from URI (e.g., "Media Library")
                rest_of_path = os.sep.join(parts[1:]) if len(parts) > 1 else ""
                
                # Normalize share name for matching (lowercase, various encodings)
                share_name_normalized = share_name_from_uri.lower()
                share_name_encoded = share_name_normalized.replace(" ", "%20")
                share_name_url_encoded = urllib.parse.quote(share_name_normalized, safe='')
                
                # Try common GVFS mount locations
                uid = os.getuid()
                gvfs_base = f"/run/user/{uid}/gvfs"
                
                candidates = []
                
                # First, scan the GVFS directory for ANY mount with matching share name
                # This handles the case where hostname in XML differs from IP in mount
                if os.path.isdir(gvfs_base):
                    try:
                        for mount_name in os.listdir(gvfs_base):
                            if mount_name.startswith("smb-share:"):
                                # Parse the mount name to extract share
                                # Format: smb-share:server=<ip>,share=<share>
                                mount_lower = mount_name.lower()
                                
                                # Check if share name matches (try various encodings)
                                share_match = False
                                for share_variant in [share_name_encoded, share_name_normalized, share_name_url_encoded]:
                                    if f",share={share_variant}" in mount_lower or f":share={share_variant}" in mount_lower:
                                        share_match = True
                                        break
                                
                                if share_match:
                                    candidate = os.path.join(gvfs_base, mount_name, rest_of_path)
                                    if os.path.exists(candidate):
                                        return candidate
                                    candidates.append(candidate)
                    except OSError:
                        pass
                
                # Fallback: try exact host match (original behavior)
                share_variants = [share_name_encoded, share_name_normalized, share_name_url_encoded]
                for share in share_variants:
                    gvfs_path = os.path.join(gvfs_base, f"smb-share:server={host},share={share}", rest_of_path)
                    candidates.append(gvfs_path)
                    # Also try with lowercase host
                    gvfs_path_lower = os.path.join(gvfs_base, f"smb-share:server={host.lower()},share={share}", rest_of_path)
                    if gvfs_path_lower not in candidates:
                        candidates.append(gvfs_path_lower)
                
                # Also try the legacy ~/.gvfs location
                legacy_gvfs = os.path.expanduser("~/.gvfs")
                if os.path.isdir(legacy_gvfs):
                    for share in share_variants:
                        candidates.append(os.path.join(legacy_gvfs, f"{share} on {host}", rest_of_path))
                
                # Try /media and /mnt mounts as well
                for mount_base in ["/media", f"/media/{os.environ.get('USER', '')}", "/mnt"]:
                    if os.path.isdir(mount_base):
                        candidates.append(os.path.join(mount_base, *parts))
                
                for c in candidates:
                    if os.path.exists(c):
                        return c
                
                # Return the first GVFS candidate even if it doesn't exist (for logging purposes)
                if candidates:
                    return candidates[0]
            
        if IS_MACOS:
            is_network = (host and host.lower() != 'localhost') or file_uri.startswith("//")
            if is_network:
                clean_path = local_path.lstrip(os.sep)
                parts = clean_path.split(os.sep)
                
                candidates = [local_path]
                if parts:
                    candidates.append(os.path.join("/Volumes", *parts))
                    if len(parts) > 1:
                        candidates.append(os.path.join("/Volumes", *parts[1:]))
                    
                    likely_share = parts[0]
                    if likely_share and os.path.isdir("/Volumes"):
                        for vol in os.listdir("/Volumes"):
                            if vol.startswith(likely_share):
                                candidates.append(os.path.join("/Volumes", vol, *parts[1:]))

                for c in candidates:
                    if os.path.exists(c): 
                        return c
                
                if parts: return os.path.join("/Volumes", *parts)

        return local_path if os.path.exists(local_path) else local_path

    except Exception as e:
        logging.warning(f"Path resolution error for {file_uri}: {e}")
        return None

def extract_art_from_file(file_uri: str) -> Optional[Image.Image]:
    path = resolve_path(file_uri)
    
    if not path:
        return None
    
    if not os.path.exists(path):
        logging.warning(f"ArtExtraction: File not found: {path}")
        return None
        
    try:
        f = mutagen.File(path)
        if f is None: return None
        
        art_data = None
        if hasattr(f, 'tags') and f.tags:
            for key in f.tags.keys():
                if key.startswith('APIC:'): 
                    art_data = f.tags[key].data
                    break
                elif key == 'covr': 
                    art_data = f.tags['covr'][0]
                    break
                    
        if not art_data and hasattr(f, 'pictures') and f.pictures: 
            art_data = f.pictures[0].data
            
        if art_data: 
            return Image.open(BytesIO(art_data)).convert("RGBA")
            
    except Exception as ex:
        logging.warning(f"ArtExtraction: Exception for {path}: {ex}")
    
    return None

def get_xml_files_in_folder(folder_path: str) -> List[Dict]:
    valid_files = []
    if not os.path.isdir(folder_path):
        return valid_files
    
    logging.info(f"Scanning directory: {folder_path}")
    
    for f in os.listdir(folder_path):
        if not f.endswith('.xml'): continue
        try:
            dt = parser.parse(os.path.splitext(f)[0], fuzzy=True)
            valid_files.append({
                'label': dt.strftime('%Y-%m-%d'),
                'date': dt,
                'path': os.path.join(folder_path, f),
                'file': f
            })
        except:
            continue
            
    valid_files.sort(key=lambda x: x['date'])
    
    seen = defaultdict(int)
    for item in valid_files:
        seen[item['label']] += 1
        if seen[item['label']] > 1:
            item['label'] = f"{item['label']} ({seen[item['label']]})"
            
    logging.info(f"Found {len(valid_files)} valid XML snapshots.")
    return valid_files

# ==========================================
# ANALYTICS ENGINE
# ==========================================

class LibraryAnalytics:
    @staticmethod
    def split_artists(artist_str: str) -> List[str]:
        if not artist_str: return ["Unknown"]
        temp = artist_str.replace(',', '|').replace('&', '|')
        parts = [p.strip() for p in temp.split('|') if p.strip()]
        return parts if parts else ["Unknown"]

    @staticmethod
    def parse_date(date_val) -> Optional[datetime.datetime]:
        if not date_val: return None
        if isinstance(date_val, datetime.datetime): return date_val
        try:
            return parser.parse(str(date_val))
        except:
            return None

    @staticmethod
    def _update_stat(stats_obj: EntityStats, plays: int, play_ms: float, skips: int, 
                     pid: str, location: str, date_added: datetime.datetime, year: int):
        stats_obj.count += plays
        stats_obj.time += play_ms
        stats_obj.skip += skips
        
        if location and (not stats_obj.location or plays > 0):
            stats_obj.location = location
        if date_added:
            stats_obj.added = date_added
        if year:
            stats_obj.year = year
        if pid:
            stats_obj.pids.add(pid)

    @classmethod
    def parse_xml(cls, xml_path: str) -> LibraryData:
        logging.info(f"LibraryAnalytics: Starting XML parse for: {xml_path}")
        data = LibraryData()
        
        if Library is None:
            data.error = "libpytunes library missing."
            logging.error(data.error)
            return data
            
        try:
            lib = Library(xml_path)
            logging.info("LibraryAnalytics: XML loaded into memory. Processing songs...")
        except Exception as e:
            msg = f"Failed to parse XML: {str(e)}"
            logging.error(msg)
            data.error = msg
            return data

        count_items, skipped_items = 0, 0
        
        for song in lib.songs.values():
            if song.podcast or song.movie or song.has_video:
                skipped_items += 1
                continue
            
            count_items += 1
            plays = song.play_count or 0
            skips = song.skip_count or 0
            length = song.length or 0
            play_ms = plays * length
            
            if plays == 0 and skips == 0 and not song.date_added:
                continue

            raw_artist = song.artist or "Unknown"
            album_artist = song.album_artist or raw_artist 
            album = song.album or "Unknown"
            song_name = song.name or "Unknown"
            genre = song.genre
            pid = song.persistent_id
            date_added = cls.parse_date(song.date_added)

            data.total_time += play_ms
            if pid:
                data.master_pid_map[pid] = {'count': plays, 'time': play_ms, 'skip': skips}

            cls._update_stat(data.songs[(song_name, raw_artist)], plays, play_ms, skips, pid, song.location, date_added, song.year)
            cls._update_stat(data.albums[(album, album_artist)], plays, play_ms, skips, pid, song.location, date_added, song.year)
            
            for ind_art in cls.split_artists(raw_artist):
                cls._update_stat(data.artists[ind_art], plays, play_ms, skips, pid, song.location, date_added, song.year)

            if genre:
                cls._update_stat(data.genres[genre], plays, play_ms, skips, pid, song.location, date_added, song.year)
            if song.year and song.year > 1900:
                cls._update_stat(data.years[song.year], plays, play_ms, skips, pid, song.location, date_added, song.year)
        
        logging.info(f"Parsed Items: {count_items} | Skipped: {skipped_items}")
        logging.info(f"Stats: Songs: {len(data.songs)} | Artists: {len(data.artists)} | Albums: {len(data.albums)}")
        return data

    @staticmethod
    def calculate_diff(new_stats: EntityStats, old_master_map: Dict[str, Dict], 
                       old_entity_stats: Optional[EntityStats] = None) -> Dict[str, Any]:
        old_count, old_time, old_skip = 0, 0.0, 0

        if old_entity_stats:
            old_count = old_entity_stats.count
            old_time = old_entity_stats.time
            old_skip = old_entity_stats.skip
        else:
            for pid in new_stats.pids:
                if pid in old_master_map:
                    old_data = old_master_map[pid]
                    old_count += old_data['count']
                    old_time += old_data['time']
                    old_skip += old_data['skip']

        return {
            'diff_time': new_stats.time - old_time,
            'diff_count': new_stats.count - old_count,
            'diff_skip': new_stats.skip - old_skip,
            'old_count_ref': old_count, 
            'has_id_match': old_count > 0 
        }

    @classmethod
    def process_stats(cls, new_lib: LibraryData, old_lib: Optional[LibraryData] = None, 
                      start_date: Optional[datetime.datetime] = None, 
                      unit: str = Theme.UNIT_HOURS, current_year: int = 2025) -> Tuple:
        
        logging.info("LibraryAnalytics: Starting differential analysis...")
        
        divisor = Theme.MS_TO_HOURS
        if unit == Theme.UNIT_MINUTES: divisor = Theme.MS_TO_MINS
        elif unit == Theme.UNIT_DAYS: divisor = Theme.MS_TO_DAYS

        old_master = old_lib.master_pid_map if old_lib else {}
        old_total_time = old_lib.total_time if old_lib else 0.0
        
        diff_total = (new_lib.total_time - old_total_time) / divisor
        new_plays_total = sum(s.count for s in new_lib.songs.values())
        old_plays_total = sum(s.count for s in old_lib.songs.values()) if old_lib else 0
        diff_plays = new_plays_total - old_plays_total
        
        logging.info(f"Stats: Time Growth: {diff_total:.2f} {unit} | Play Count Diff: {diff_plays}")

        results = defaultdict(list)

        def _process_category(category_dict, old_category_dict, list_key, label_keys):
            for key, stats in category_dict.items():
                old_stats_obj = old_category_dict.get(key) if old_category_dict else None
                diffs = cls.calculate_diff(stats, old_master, old_stats_obj)
                
                row = {
                    'Value': diffs['diff_time'] / divisor,
                    'Count': int(diffs['diff_count']),
                    'Location': stats.location 
                }
                
                if isinstance(label_keys, list):
                    for i, k in enumerate(label_keys):
                        row[k] = key[i] if isinstance(key, tuple) else key
                else:
                    row[label_keys] = key

                if diffs['diff_time'] > 0:
                    results[list_key].append(row)
                
                if list_key == 'song':
                    if diffs['diff_skip'] > 0:
                        row_skip = row.copy()
                        row_skip['Value'] = diffs['diff_skip']
                        results['skip'].append(row_skip)
                    
                    if diffs['diff_count'] > 0:
                        is_new = False
                        if start_date and stats.added:
                            added_dt = stats.added.replace(tzinfo=None) if stats.added.tzinfo else stats.added
                            start_dt_naive = start_date.replace(tzinfo=None) if start_date.tzinfo else start_date
                            if added_dt > start_dt_naive and not diffs['has_id_match']:
                                is_new = True
                        elif diffs['old_count_ref'] == 0 and not diffs['has_id_match']:
                            is_new = True
                            
                        if is_new:
                            results['new'].append(row)

        _process_category(new_lib.artists, old_lib.artists if old_lib else None, 'art', 'Artist')
        _process_category(new_lib.albums, old_lib.albums if old_lib else None, 'alb', ['Album', 'Artist'])
        _process_category(new_lib.songs, old_lib.songs if old_lib else None, 'song', ['Song', 'Artist'])
        _process_category(new_lib.genres, old_lib.genres if old_lib else None, 'gen', 'Genre')
        _process_category(new_lib.years, old_lib.years if old_lib else None, 'year', 'Year')
        
        genre_df = pd.DataFrame(results['gen'])
        top_genres = genre_df.sort_values('Count', ascending=False).head(10)['Genre'].tolist() if not genre_df.empty else []

        plays_per_year = {y: stats.count for y, stats in new_lib.years.items() if stats.count > 0}
        calculated_age = listening_age_algorithm.calculate_listening_age(plays_per_year=plays_per_year, current_year=current_year)
        
        logging.info(f"Analysis Complete. Calculated Listening Age: {calculated_age}")
        
        return (
            diff_total, diff_plays,
            pd.DataFrame(results['art']), pd.DataFrame(results['alb']),
            pd.DataFrame(results['song']), pd.DataFrame(results['gen']),
            pd.DataFrame(results['new']), pd.DataFrame(results['skip']),
            pd.DataFrame(results['year']),
            top_genres, calculated_age
        )

# ==========================================
# UI HELPER FUNCTIONS
# ==========================================

def create_slider_row(label: str, slider: ft.Slider) -> ft.Row:
    return ft.Row([
        ft.Text(label, size=12, width=50),
        ft.Container(content=slider, expand=True)
    ], alignment="center", spacing=5)

def create_kpi_card(content: ft.Control) -> ft.Container:
    return ft.Container(
        content=content, bgcolor=Theme.CARD_BG, padding=15, border_radius=12,
        expand=1, alignment=ft.alignment.center, height=Theme.KPI_HEIGHT
    )

def draw_list_item(rank: int, label: str, sub_label: str, value: float, count: int, 
                   unit: str, color: str, is_skip_list: bool=False, art_src_b64: str = None, 
                   is_circular: bool = False) -> ft.Container:
    
    stats_text = f"{int(value)} skips" if is_skip_list else f"{value:,.1f} {unit} • {int(count)} plays"
    
    left_row = [ft.Text(f"{rank}.", weight="bold", color="primary", width=30, size=16)]
    
    if art_src_b64:
        radius = 50 if is_circular else 8
        left_row.append(ft.Image(src_base64=art_src_b64, width=45, height=45, border_radius=radius, fit=ft.ImageFit.COVER))
    
    left_row.append(
        ft.Column([
            ft.Text(str(label), weight="bold", size=15, overflow="ellipsis", no_wrap=True),
            ft.Text(sub_label, size=12, color=Theme.SUBTEXT, overflow="ellipsis", no_wrap=True) if sub_label else ft.Container()
        ], spacing=2, expand=True)
    )

    return ft.Container(
        content=ft.Row([
            ft.Row(left_row, expand=True, spacing=10),
            ft.Container(
                content=ft.Text(stats_text, weight="bold", size=13),
                bgcolor="secondaryContainer", padding=ft.padding.symmetric(horizontal=10, vertical=5), border_radius=10
            )
        ], alignment="spaceBetween"),
        padding=10, bgcolor="surface", border_radius=10, border=ft.border.all(1, "outlineVariant")
    )

# ==========================================
# MAIN APPLICATION CONTROLLER
# ==========================================

class TunesBackApp:
    def __init__(self, page: ft.Page):
        self.page = page
        
        self.files = []
        self.full_labels = []
        self.data_frames = {k: pd.DataFrame() for k in ["art", "alb", "song", "gen", "new", "skip", "year"]}
        self.wrapped_data = {"genres": [], "age": 0} 
        self.cached_sorted = {}
        self.art_cache = {} 
        self.generated_images = []
        self.selected_indices = set() 
        
        self.lib_start: Optional[LibraryData] = None
        self.lib_end: Optional[LibraryData] = None
        self.is_compare_mode = False
        
        self.analysis_thread: Optional[threading.Thread] = None
        self.cancel_analysis = False
        
        self.current_tab = "song" 
        self.visible_tabs = {"song", "alb", "art", "gen"} 
        self.all_tabs_config = [
            ("song", "Songs", "music_note"),
            ("alb", "Albums", "album"),
            ("art", "Artists", "mic"), 
            ("gen", "Genres", "category"), 
            ("new", "New Finds", "new_releases"), 
            ("skip", "Skipped", "fast_forward"),
            ("year", "Years", "calendar_month") 
        ]
        
        self._build_ui()

    # --- UI INITIALIZATION REGION ---

    def _build_ui(self):
        self._init_sidebar_controls()
        self._init_main_view_controls()
        self._init_modals()
        self._layout_structure()

    def _init_sidebar_controls(self):
        self.txt_path = ft.Text("", size=11, color=Theme.SUBTEXT, overflow="ellipsis", max_lines=2, visible=False)
        self.txt_file_count = ft.Text("", size=11, color="primary", weight="bold", visible=False)
        self.btn_select = ft.ElevatedButton("Select Folder", icon="folder", width=float("inf"), height=Theme.BUTTON_HEIGHT, on_click=self.open_file_picker)
        
        self.dd_start = ft.Dropdown(
            label="Start Date / Single Library", text_size=14, label_style=ft.TextStyle(size=14),
            dense=True, border="outline", border_color=Theme.SUBTEXT, border_radius=10,
            disabled=True, width=Theme.TOGGLE_WIDTH, on_change=self.on_start_changed
        )
        self.dd_end = ft.Dropdown(
            label="End Date", text_size=14, label_style=ft.TextStyle(size=14),
            dense=True, border="outline", border_color=Theme.SUBTEXT, border_radius=10,
            disabled=True, expand=True
        )
        self.cb_compare = ft.Checkbox(label="Compare", value=True, disabled=True, on_change=self.on_compare_changed)
        
        self.sl_art = ft.Slider(min=5, max=100, value=15, divisions=19, label="{value}", disabled=True)
        self.sl_alb = ft.Slider(min=5, max=100, value=15, divisions=19, label="{value}", disabled=True)
        self.sl_song = ft.Slider(min=5, max=100, value=25, divisions=19, label="{value}", disabled=True)
        self.sl_gen = ft.Slider(min=5, max=50, value=10, divisions=9, label="{value}", disabled=True) 
        self.sl_year = ft.Slider(min=5, max=50, value=10, divisions=9, label="{value}", disabled=True) 
        
        self.cb_album_art = ft.Checkbox(label="Show Album Art (Slow)", value=False, disabled=True)
        self.cb_logging = ft.Checkbox(label="Enable Debug Logging", value=False)
        self.btn_open_logs = ft.IconButton(icon="EXIT_TO_APP", icon_size=20, tooltip="Open Log Folder", on_click=self.open_log_folder)
        
        self.seg_unit = ft.SegmentedButton(
            selected={Theme.UNIT_HOURS},
            segments=[ft.Segment(value=v, label=ft.Text(l)) for v, l in [(Theme.UNIT_HOURS, "Hrs"), (Theme.UNIT_MINUTES, "Mins"), (Theme.UNIT_DAYS, "Days")]],
            disabled=True, on_change=self.on_unit_changed, width=Theme.TOGGLE_WIDTH
        )
        self.seg_sort = ft.SegmentedButton(
            selected={"count"},
            segments=[ft.Segment(value="count", label=ft.Text("Plays")), ft.Segment(value="time", label=ft.Text("Time"))],
            disabled=True, on_change=self.update_results_ui, width=Theme.TOGGLE_WIDTH
        )

        self.btn_run = ft.ElevatedButton("Generate Recap", icon="bar_chart", style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8), padding=20), expand=True, disabled=True, on_click=self.run_analysis)
        self.btn_cancel = ft.ElevatedButton("Cancel", icon="close", color="error", style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8), padding=20), expand=True, visible=False, on_click=self.cancel_analysis_handler)
        self.btn_reset = ft.IconButton(icon="refresh", tooltip="Reset View", disabled=True, on_click=self.reset_view)
        self.btn_theme = ft.IconButton(icon="light_mode", icon_size=18, tooltip="Toggle Theme", on_click=self.toggle_theme)

        self.file_picker = ft.FilePicker(on_result=self.on_folder_picked)
        self.dir_picker = ft.FilePicker(on_result=self.on_save_wrapped_dir)
        self.page.overlay.extend([self.file_picker, self.dir_picker])

    def _init_main_view_controls(self):
        self.btn_minimize = ft.IconButton(icon="remove", icon_size=14, on_click=self.minimize_app)
        self.btn_close = ft.IconButton(icon="close", icon_size=14, on_click=self.close_app)
        self.txt_app_title = ft.Text("TunesBack", weight="bold", size=14, color=Theme.SUBTEXT, opacity=0, animate_opacity=300)

        self.tabs_row = ft.Row(spacing=0, scroll="auto", expand=True)
        self.btn_wrapped = ft.ElevatedButton(
            content=ft.Row([ft.Icon("auto_awesome"), ft.Text("Generate Wrapped Cards")], alignment="center", spacing=10),
            bgcolor="tertiary", color="onTertiary", style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)), height=40, visible=False, on_click=self.start_wrapped_generation
        )
        self.btn_edit_tabs = ft.IconButton(icon="edit", tooltip="Edit Visible Tabs", icon_size=20, visible=False, on_click=self.open_tab_editor)
        self.list_results = ft.ListView(expand=True, spacing=10, padding=ft.padding.symmetric(horizontal=10, vertical=10))
        
        self.kpi_growth = ft.Text("0.0", size=32, weight="bold", color="primary")
        self.kpi_growth_u = ft.Text(f"{Theme.UNIT_HOURS} Growth", size=14, weight="bold", color=Theme.SUBTEXT)
        self.kpi_plays = ft.Text("0", size=32, weight="bold", color="primary")
        self.kpi_plays_u = ft.Text("New Plays", size=14, weight="bold", color=Theme.SUBTEXT)
        self.card_vals = [ft.Text("-", size=16, weight="bold", overflow="ellipsis", text_align="center", no_wrap=True) for _ in range(3)]
        self.card_subs = [ft.Text("-", size=11, color=Theme.SUBTEXT, text_align="center") for _ in range(3)]
        
        self.txt_loading_status = ft.Text("Crunching numbers...", size=16, weight="bold", color=Theme.SUBTEXT)

    def _init_modals(self):
        self.tab_editor_col = ft.Column()
        self.tab_editor_modal = ft.Container(
            content=ft.Container(
                content=ft.Column([
                    ft.Text("Select Tabs to Display", size=18, weight="bold"),
                    self.tab_editor_col,
                    ft.Row([ft.TextButton("Close", on_click=lambda e: self.toggle_tab_editor(False)), ft.FilledButton("Save", on_click=self.save_tab_preferences)], alignment="end")
                ], spacing=20, tight=True),
                padding=25, bgcolor="surface", border_radius=12, width=350, shadow=ft.BoxShadow(blur_radius=20, color="black")
            ), bgcolor=ft.Colors.with_opacity(0.6, "black"), alignment=ft.alignment.center, visible=False, expand=True
        )

        self.modal_title = ft.Text("Error", weight="bold", size=20)
        self.modal_text = ft.Text("Msg")
        self.modal_container = ft.Container(
            content=ft.Container(
                content=ft.Column([
                    self.modal_title, self.modal_text,
                    ft.Row([ft.TextButton("OK", on_click=lambda e: self.toggle_modal(False))], alignment="end")
                ], spacing=10, tight=True),
                padding=25, bgcolor="surface", border_radius=12, width=350, shadow=ft.BoxShadow(blur_radius=20, color=ft.Colors.with_opacity(0.5, "black"))
            ), bgcolor=ft.Colors.with_opacity(0.6, "black"), alignment=ft.alignment.center, visible=False, expand=True
        )
        
        self.wrapped_grid = ft.Row(scroll="auto", expand=True, spacing=30) 
        self.wrapped_modal = ft.Container(
             content=ft.Container(
                content=ft.Column([
                    ft.Container(content=self.wrapped_grid, expand=True), 
                    ft.Row([
                        ft.TextButton("Close", on_click=lambda e: self.toggle_wrapped_modal(False)),
                        ft.Row([
                            ft.OutlinedButton("Save Selected", icon="download", on_click=lambda e: self.save_images(selected_only=True)),
                            ft.OutlinedButton("Save All", icon="download", on_click=lambda e: self.save_images(selected_only=False))
                        ])
                    ], alignment="spaceBetween")
                ], spacing=10),
                padding=20, bgcolor="surface", border_radius=15, width=1200, height=580, shadow=ft.BoxShadow(blur_radius=30, color="black")
            ), bgcolor=ft.Colors.with_opacity(0.85, "black"), alignment=ft.alignment.center, visible=False, expand=True
        )

    def _layout_structure(self):
        self._render_tabs()

        self.view_welcome = ft.Container(
            content=ft.Column([
                ft.Text("👋", size=60), ft.Text("Welcome to TunesBack", size=24, weight="bold"),
                ft.Text("Select a folder containing your library snapshots to begin.", size=14, color=Theme.SUBTEXT),
            ], horizontal_alignment="center", alignment="center", spacing=10),
            alignment=ft.alignment.center, expand=True, visible=True, padding=ft.padding.only(bottom=60)
        )

        self.view_loading = ft.Container(
            content=ft.Column([ft.ProgressRing(width=50, height=50, stroke_width=4), self.txt_loading_status], horizontal_alignment="center", alignment="center", spacing=20),
            alignment=ft.alignment.center, expand=True, visible=False, padding=ft.padding.only(bottom=60)
        )

        kpi_row = ft.Row([
            create_kpi_card(ft.Column([ft.Text("Top Artist", size=10, color=Theme.SUBTEXT), self.card_vals[0], self.card_subs[0]], horizontal_alignment="center", alignment=ft.MainAxisAlignment.CENTER, spacing=2)),
            create_kpi_card(ft.Column([ft.Text("Top Album", size=10, color=Theme.SUBTEXT), self.card_vals[1], self.card_subs[1]], horizontal_alignment="center", alignment=ft.MainAxisAlignment.CENTER, spacing=2)),
            create_kpi_card(ft.Column([ft.Text("Top Song", size=10, color=Theme.SUBTEXT), self.card_vals[2], self.card_subs[2]], horizontal_alignment="center", alignment=ft.MainAxisAlignment.CENTER, spacing=2)),
        ], spacing=15, expand=True)

        header_row = ft.Row([
            ft.Container(content=ft.Column([ft.Column([self.kpi_growth, self.kpi_growth_u], spacing=0), ft.Column([self.kpi_plays, self.kpi_plays_u], spacing=0)], alignment="spaceBetween", spacing=0), height=Theme.KPI_HEIGHT, alignment=ft.alignment.center_left),
            ft.Container(width=40), kpi_row
        ], alignment="start", vertical_alignment="center")

        self.view_dash = ft.Column([
            ft.Container(padding=ft.padding.only(left=Theme.PAD_LEFT, right=Theme.PAD_RIGHT), 
                         content=ft.Column([ft.Container(height=10), header_row, ft.Container(height=20), 
                                            ft.Row([ft.Row([self.tabs_row, self.btn_edit_tabs], spacing=5, expand=True), self.btn_wrapped], alignment="spaceBetween", vertical_alignment="center"), 
                                            ft.Container(height=10)])),
            ft.Container(padding=ft.padding.only(left=Theme.PAD_LEFT, right=Theme.PAD_RIGHT, bottom=10), 
                         content=ft.Container(content=self.list_results, bgcolor=ft.Colors.with_opacity(0.05, "black"), border_radius=10, border=ft.border.all(1, "outlineVariant"), expand=True), expand=True)
        ], expand=True, visible=False, spacing=0)

        self.exp_sliders = ft.Container(
            border=ft.border.all(1, Theme.SUBTEXT), border_radius=10, opacity=0.5,
            content=ft.ExpansionTile(
                title=ft.Container(content=ft.Text("Item Limits", size=14), padding=ft.padding.only(left=5)),
                controls=[ft.Container(content=ft.Column([
                    create_slider_row("Artists", self.sl_art), create_slider_row("Albums", self.sl_alb), 
                    create_slider_row("Songs", self.sl_song), create_slider_row("Genres", self.sl_gen),
                    create_slider_row("Years", self.sl_year) 
                ], spacing=-5), padding=ft.padding.only(bottom=10, left=10, right=10))],
                initially_expanded=False, tile_padding=ft.padding.symmetric(horizontal=5), shape=ft.RoundedRectangleBorder(radius=10), collapsed_shape=ft.RoundedRectangleBorder(radius=10), bgcolor=ft.Colors.TRANSPARENT
            )
        )

        sidebar_content = ft.Column([
            ft.Row([ft.Text("SETTINGS", size=12, weight="bold", color=Theme.SUBTEXT), self.btn_theme], alignment="spaceBetween"), ft.Divider(),
            ft.Text("Source", size=12, weight="bold"), self.btn_select, self.txt_path, self.txt_file_count, ft.Divider(),
            ft.Text("Period", size=12, weight="bold"), ft.Column([self.dd_start, ft.Row([self.dd_end, self.cb_compare], alignment="spaceBetween", vertical_alignment="center")], spacing=20), ft.Divider(),
            self.exp_sliders, self.cb_album_art, ft.Row([self.cb_logging, self.btn_open_logs], spacing=0, alignment=ft.MainAxisAlignment.START), ft.Divider(),
            ft.Text("Units & Ranking", size=12, weight="bold"), ft.Column([ft.Text("Time Unit", size=11, color=Theme.SUBTEXT), self.seg_unit, ft.Text("Rank By", size=11, color=Theme.SUBTEXT), self.seg_sort], spacing=5),
            ft.Container(height=20), ft.Stack([ft.Row([self.btn_run, self.btn_reset], spacing=10), self.btn_cancel]),
        ], spacing=10)

        sidebar_padding = ft.padding.only(left=20, right=20, top=30 if IS_MACOS else 20, bottom=20)
        sidebar = ft.Container(width=Theme.SIDEBAR_WIDTH, bgcolor=Theme.SIDEBAR_BG, content=ft.Column([ft.Container(padding=sidebar_padding, content=sidebar_content)], scroll="auto"))

        window_header = ft.WindowDragArea(content=ft.Container(
            content=ft.Row([self.txt_app_title, ft.Row([self.btn_minimize, self.btn_close], spacing=0) if not IS_MACOS else ft.Container()], alignment="spaceBetween"),
            padding=ft.padding.only(left=Theme.PAD_LEFT, right=20, top=30 if IS_MACOS else 20, bottom=10), bgcolor=Theme.CONTENT_BG
        ))

        self.main_layout = ft.Container(content=ft.Stack([
            ft.Row([sidebar, ft.Container(content=ft.Column([window_header, ft.Container(expand=True, bgcolor=Theme.CONTENT_BG, padding=0, content=ft.Column([ft.Stack([self.view_welcome, self.view_dash, self.view_loading], expand=True)], spacing=0))], spacing=0), expand=True)], expand=True, spacing=0, vertical_alignment="stretch"),
            self.modal_container, self.wrapped_modal, self.tab_editor_modal
        ]), expand=True)

    # --- TAB LOGIC REGION ---

    def _create_custom_tab_button(self, key, label, icon):
        is_selected = (self.current_tab == key)
        style = ft.ButtonStyle(shape=ft.StadiumBorder())
        btn_cls = ft.FilledButton if is_selected else ft.OutlinedButton
        return ft.Container(content=btn_cls(text=label, icon=icon, style=style, on_click=lambda e: self.on_custom_tab_clicked(key)), padding=ft.padding.only(right=10))

    def _render_tabs(self):
        visible_tab_configs = [t for t in self.all_tabs_config if t[0] in self.visible_tabs]
        self.tabs_row.controls = [self._create_custom_tab_button(k, l, i) for k, l, i in visible_tab_configs]
        if self.current_tab not in self.visible_tabs and visible_tab_configs:
            self.current_tab = visible_tab_configs[0][0]

    def on_custom_tab_clicked(self, key):
        self.current_tab = key
        self._render_tabs()
        self.tabs_row.update()
        self.update_results_ui(None)

    # --- MODAL LOGIC REGION ---
    
    def open_tab_editor(self, e):
        def create_cb(key, label):
             disabled = (key == "new" and not self.cb_compare.value)
             return ft.Checkbox(label=label, value=(key in self.visible_tabs), data=key, disabled=disabled)

        self.tab_editor_col.controls = [create_cb(k, l) for k, l, _ in self.all_tabs_config]
        self.toggle_tab_editor(True)
        
    def toggle_tab_editor(self, show):
        self.tab_editor_modal.visible = show
        self.page.update()
        
    def save_tab_preferences(self, e):
        new_set = {cb.data for cb in self.tab_editor_col.controls if cb.value}
        if not new_set:
            self.page.snack_bar = ft.SnackBar(ft.Text("At least one tab must be visible."))
            self.page.snack_bar.open = True
            self.page.update()
            return
        self.visible_tabs = new_set
        self._render_tabs()
        self.tabs_row.update()
        self.update_results_ui(None)
        self.toggle_tab_editor(False)

    def toggle_modal(self, show: bool, title: str = "", msg: str = ""):
        self.modal_container.visible = show
        self.modal_title.value = title
        self.modal_text.value = msg
        self.page.update()

    def toggle_wrapped_modal(self, show: bool):
        self.wrapped_modal.visible = show
        self.page.update()

    # --- ACTION HANDLERS REGION ---

    def minimize_app(self, e):
        self.page.window.minimized = True
        self.page.update()

    def close_app(self, e):
        self.page.window.close()

    def open_log_folder(self, e):
        log_dir = os.path.dirname(get_log_path())
        try:
            logging.info(f"User requested to open log folder: {log_dir}")
            if IS_WINDOWS: os.startfile(log_dir)
            elif IS_MACOS: subprocess.run(["open", log_dir])
            else: subprocess.run(["xdg-open", log_dir])
        except Exception as ex:
            logging.error(f"Failed to open log folder: {ex}")
            self.page.snack_bar = ft.SnackBar(ft.Text(f"Could not open log folder: {ex}"))
            self.page.snack_bar.open = True
            self.page.update()

    def open_file_picker(self, e):
        self.file_picker.get_directory_path()

    def on_folder_picked(self, e: ft.FilePickerResultEvent):
        if not e.path: 
            logging.info("Folder picker cancelled.")
            return
            
        logging.info(f"User selected folder: {e.path}")
        self.txt_path.value = e.path
        self.txt_path.color = Theme.SUBTEXT
        self.txt_path.visible = True
        self.txt_file_count.visible = True
        self.files = get_xml_files_in_folder(e.path)
        
        if self.files:
            self.full_labels = [f['label'] for f in self.files]
            opts = [ft.dropdown.Option(lbl) for lbl in self.full_labels]
            self.dd_start.options = opts
            self.dd_end.options = [ft.dropdown.Option(lbl) for lbl in self.full_labels]
            self.dd_start.value = opts[0].key
            self.dd_end.value = opts[-1].key if len(opts) > 1 else None
            
            is_single = len(self.files) == 1
            self.cb_compare.value = not is_single
            self.cb_compare.disabled = is_single
            self.dd_end.disabled = is_single
            self.txt_file_count.value = "Found 1 snapshot, comparison disabled" if is_single else f"Found {len(self.files)} snapshots"
            
            # Enable controls visually
            self.exp_sliders.opacity = 1.0
            
            for c in [self.dd_start, self.btn_run, self.sl_art, self.sl_alb, self.sl_song, self.sl_gen, self.sl_year, self.seg_unit, self.seg_sort, self.cb_album_art]:
                c.disabled = False
            self.on_start_changed(None)
        else:
            self.txt_path.value = "No dated XML files found."
            self.txt_path.color = "error"
            self.txt_file_count.visible = False
            logging.warning("No XML files found in selected folder.")
        self.page.update()

    def on_compare_changed(self, e):
        logging.info(f"Compare mode changed to: {self.cb_compare.value}")
        self.dd_end.disabled = not self.cb_compare.value
        
        if self.cb_compare.value:
            self.dd_end.value = self.dd_end.options[-1].key if self.dd_end.options else None
        else:
            if self.dd_end.options:
                self.dd_start.value = self.dd_end.options[-1].key
                self.dd_start.update()
            self.dd_end.value = None
            
        self.page.update()

    def on_start_changed(self, e):
        if not self.full_labels: return
        new_end_opts = [ft.dropdown.Option(lbl) for lbl in self.full_labels if lbl != self.dd_start.value]
        self.dd_end.options = new_end_opts
        if self.cb_compare.value and new_end_opts and (not self.dd_end.value or self.dd_end.value == self.dd_start.value):
            self.dd_end.value = new_end_opts[-1].key
        self.dd_end.update()

    def on_unit_changed(self, e):
        if self.lib_start: self._calculate_and_refresh()

    def toggle_theme(self, e):
        self.page.theme_mode = 'light' if self.page.theme_mode == 'dark' else 'dark'
        self.btn_theme.icon = 'dark_mode' if self.page.theme_mode == 'light' else 'light_mode'
        self.page.update()

    def reset_view(self, e):
        logging.info("Resetting view state.")
        self.view_welcome.visible = True
        self.view_dash.visible = False
        self.btn_reset.disabled = True
        self.txt_app_title.opacity = 0
        self.data_frames = {k: pd.DataFrame() for k in ["art", "alb", "song", "gen", "new", "skip", "year"]}
        self.cached_sorted.clear()
        self.art_cache.clear()
        self.lib_start = None
        self.lib_end = None
        self.page.update()

    # --- ANALYSIS LOGIC REGION ---

    def cancel_analysis_handler(self, e):
        self.cancel_analysis = True
        logging.warning("Analysis cancellation requested by user.")
        self.txt_loading_status.value = "Cancelling..."
        self.page.update()

    def run_analysis(self, e):
        if not self.dd_start.value: return
        
        # Set default visible tabs based on analysis mode
        self.visible_tabs = {"song", "alb", "art", "new"} if self.cb_compare.value else {"song", "alb", "art", "gen"}
        self._render_tabs()
        self.tabs_row.update()

        configure_dynamic_logging(self.cb_logging.value, mode='w')
        
        try:
            start_file = next(f for f in self.files if f['label'] == self.dd_start.value)
            if self.cb_compare.value:
                if not self.dd_end.value: return
                end_file = next(f for f in self.files if f['label'] == self.dd_end.value)
                if start_file['date'] > end_file['date']:
                    self.toggle_modal(True, "Invalid Range", "Start Date cannot be after End Date.")
                    return
        except StopIteration:
            self.toggle_modal(True, "Error", "Selected file not found.")
            return

        logging.info("Starting Analysis Thread.")
        self.cancel_analysis = False
        self.analysis_thread = threading.Thread(target=self._run_analysis_thread, daemon=True)
        self.analysis_thread.start()

    def _run_analysis_thread(self):
        try:
            start_file = next(f for f in self.files if f['label'] == self.dd_start.value)
            
            self._set_loading_state(True)
            self.txt_loading_status.value = "Parsing first library..."
            self.page.update()
            
            logging.info(f"Parsing main library: {start_file['path']}")
            self.lib_start = LibraryAnalytics.parse_xml(start_file['path'])
            if self.lib_start.error: raise Exception(self.lib_start.error)
            if self.cancel_analysis: return self._set_loading_state(False)

            self.is_compare_mode = self.cb_compare.value
            self.lib_end = None

            if self.is_compare_mode:
                end_file = next(f for f in self.files if f['label'] == self.dd_end.value)
                self.txt_loading_status.value = "Parsing second library..."
                self.page.update()
                
                logging.info(f"Parsing comparison library: {end_file['path']}")
                self.lib_end = LibraryAnalytics.parse_xml(end_file['path'])
                if self.lib_end.error: raise Exception(self.lib_end.error)
                if self.cancel_analysis: return self._set_loading_state(False)
                
                self.txt_loading_status.value = "Calculating differences..."
            else:
                self.txt_loading_status.value = "Calculating stats..."
            self.page.update()

            self._calculate_and_refresh()
            
            if self.cb_album_art.value:
                self._preload_artwork()
                self.update_results_ui(None)
            
            self._set_loading_state(False)

        except Exception as ex:
            logging.error(f"Critical Analysis Error: {ex}")
            logging.error(traceback.format_exc())
            
            self.toggle_modal(True, "Error", str(ex))
            self._set_loading_state(False)

    def _preload_artwork(self):
        self.txt_loading_status.value = "Pre-loading album artwork..."
        self.page.update()
        logging.info("Starting album art pre-caching...")
        
        unique_locations = set()
        
        for key in ["song", "alb", "new", "skip", "art"]:
            if self.data_frames[key].empty: continue
            
            limit = 10
            if key == "alb": limit = int(self.sl_alb.value)
            elif key == "art": limit = int(self.sl_art.value)
            else: limit = int(self.sl_song.value)
            
            df_top = self.data_frames[key].sort_values("Count", ascending=False).head(limit)
            if "Location" in df_top.columns:
                unique_locations.update(df_top["Location"].dropna().unique())
        
        cache_count = 0
        for loc in unique_locations:
            if self.cancel_analysis: break
            if loc not in self.art_cache:
                pil_img = extract_art_from_file(loc)
                if pil_img:
                    pil_img.thumbnail((100, 100))
                    buffered = BytesIO()
                    pil_img.save(buffered, format="PNG")
                    self.art_cache[loc] = base64.b64encode(buffered.getvalue()).decode()
                    cache_count += 1
        logging.info(f"Pre-caching complete. Cached {cache_count} new images.")

    def _calculate_and_refresh(self):
        start_file = next((f for f in self.files if f['label'] == self.dd_start.value), None)
        start_date = start_file['date'] if start_file else None
        end_year = self.files[-1]['date'].year if self.files else 2025
        unit = list(self.seg_unit.selected)[0]
        
        stats = LibraryAnalytics.process_stats(
            new_lib=self.lib_start if not self.is_compare_mode else self.lib_end,
            old_lib=self.lib_start if self.is_compare_mode else None,
            start_date=start_date,
            unit=unit,
            current_year=end_year
        )
        
        (val_main, val_plays, df_art, df_alb, df_song, df_gen, df_new, df_skip, df_year, top_genres, age) = stats
        
        # Map artist images to their best album cover
        if not df_alb.empty and not df_art.empty:
            best_covers = df_alb.sort_values('Count', ascending=False).drop_duplicates('Artist')
            cover_map = dict(zip(best_covers['Artist'], best_covers['Location']))
            df_art['Location'] = df_art['Artist'].map(cover_map).fillna(df_art['Location'])

        self.wrapped_data = {"genres": top_genres, "age": age}
        self.data_frames = {"art": df_art, "alb": df_alb, "song": df_song, "gen": df_gen, "new": df_new, "skip": df_skip, "year": df_year}
        self.cached_sorted.clear()
        
        prefix = f"{unit} Growth" if self.is_compare_mode else f"Total {unit}"
        self.kpi_growth.value = f"{val_main:,.1f}"
        self.kpi_growth_u.value = prefix
        self.kpi_plays.value = f"{int(val_plays):,}"
        self.kpi_plays_u.value = "New Plays" if self.is_compare_mode else "Total Plays"
        
        self._update_top_cards(unit)
        self.update_results_ui(None)
        self.page.update()

    def _set_loading_state(self, is_loading: bool):
        self.view_loading.visible = is_loading
        self.view_welcome.visible = False
        self.view_dash.visible = not is_loading and bool(self.data_frames["art"].size)
        
        if not is_loading and not self.data_frames["art"].size:
            self.view_welcome.visible = True
        
        self.btn_run.visible = not is_loading
        self.btn_cancel.visible = is_loading
        self.btn_reset.disabled = is_loading
        self.txt_app_title.opacity = 0 if is_loading else 1
        self.btn_wrapped.visible = not is_loading
        self.btn_edit_tabs.visible = not is_loading
        self.btn_wrapped.content = ft.Row([ft.Icon("auto_awesome"), ft.Text("Generate Wrapped Cards")], alignment="center", spacing=10)
        
        if not is_loading:
            self.txt_loading_status.value = "Crunching numbers..."
        self.page.update()

    def _update_top_cards(self, unit: str):
        dfs = [self.data_frames["art"], self.data_frames["alb"], self.data_frames["song"]]
        keys = ["Artist", "Album", "Song"]
        for i, df in enumerate(dfs):
            if df.empty:
                self.card_vals[i].value = "-"
                self.card_subs[i].value = "-"
            else:
                top = df.sort_values('Value', ascending=False).iloc[0]
                self.card_vals[i].value = top[keys[i]]
                self.card_subs[i].value = f"{top['Value']:.1f} {unit} • {int(top['Count'])} plays"

    def update_results_ui(self, e):
        unit = list(self.seg_unit.selected)[0]
        sort_mode = list(self.seg_sort.selected)[0]
        
        configs = {
            "art": (self.data_frames["art"], int(self.sl_art.value), "cyan", "Artist", None, False, True),
            "alb": (self.data_frames["alb"], int(self.sl_alb.value), "purple", "Album", "Artist", False, False),
            "song": (self.data_frames["song"], int(self.sl_song.value), "pink", "Song", "Artist", False, False),
            "gen": (self.data_frames["gen"], int(self.sl_gen.value), "teal", "Genre", None, False, False),
            "new": (self.data_frames["new"], int(self.sl_song.value), "orange", "Song", "Artist", False, False),
            "skip": (self.data_frames["skip"], int(self.sl_song.value), "red", "Song", "Artist", True, False),
            "year": (self.data_frames["year"], int(self.sl_year.value), "blue_grey", "Year", None, False, False), 
        }
        
        if self.current_tab not in configs:
            if self.visible_tabs:
                self.current_tab = [t[0] for t in self.all_tabs_config if t[0] in self.visible_tabs][0]
            else: return
        
        df, limit, color, main_col, sub_col, is_skip, is_circular = configs.get(self.current_tab, configs["art"])
        self.list_results.controls.clear()
        
        if df.empty:
            self.list_results.controls.append(ft.Text("No data to display.", italic=True))
        else:
            cache_key = (self.current_tab, sort_mode)
            if cache_key not in self.cached_sorted:
                sort_col = 'Value' if sort_mode == 'time' or self.current_tab == 'skip' else 'Count'
                if self.current_tab == 'year': sort_col = 'Year'
                self.cached_sorted[cache_key] = df.sort_values(sort_col, ascending=False)
            
            df_sorted = self.cached_sorted[cache_key].head(limit)
            show_art = self.cb_album_art.value and self.current_tab in ["song", "alb", "new", "art"]
            
            for i, row in enumerate(df_sorted.itertuples(), 1):
                lbl = getattr(row, main_col)
                sub = getattr(row, sub_col) if sub_col else ""
                art_b64 = self.art_cache.get(getattr(row, "Location", None)) if show_art else None

                self.list_results.controls.append(
                    draw_list_item(i, lbl, sub, getattr(row, "Value"), getattr(row, "Count"), unit, color, is_skip, art_src_b64=art_b64, is_circular=is_circular)
                )
        self.list_results.update()

    # --- WRAPPED GENERATION REGION ---

    def start_wrapped_generation(self, e):
        self.btn_wrapped.content = ft.Container(content=ft.ProgressRing(width=20, height=20, stroke_width=2, color="onTertiary"), alignment=ft.alignment.center)
        self.btn_wrapped.update()
        configure_dynamic_logging(self.cb_logging.value, mode='a')
        threading.Thread(target=self._generate_wrapped_thread, daemon=True).start()

    def _generate_wrapped_thread(self):
        logging.info("Starting Wrapped Generation...")
        sort_mode = list(self.seg_sort.selected)[0]
        sort_col = 'Value' if sort_mode == 'time' else 'Count'
        current_unit = list(self.seg_unit.selected)[0]
        
        min_multiplier = 60.0 if current_unit == Theme.UNIT_HOURS else (1440.0 if current_unit == Theme.UNIT_DAYS else 1.0)
        
        top_songs = self.data_frames['song'].sort_values(sort_col, ascending=False).head(5).to_dict('records')
        top_albums = self.data_frames['alb'].sort_values(sort_col, ascending=False).head(5).to_dict('records')
        top_artists_list = self.data_frames['art'].sort_values(sort_col, ascending=False).head(5).to_dict('records')
        top_artists = self.data_frames['art'].sort_values(sort_col, ascending=False).head(1).to_dict('records')
        
        total_minutes = int(self.data_frames['song']['Value'].sum() * min_multiplier)

        def get_pil_art(path):
            return extract_art_from_file(path)

        wrapped_context = {
            'top_songs': [{'name': s['Song'], 'sub': s['Artist'], 'image': get_pil_art(s.get('Location')), 'count': s['Count']} for s in top_songs],
            'top_albums': [{'name': a['Album'], 'sub': a['Artist'], 'image': get_pil_art(a.get('Location')), 'minutes': int(a['Value'] * min_multiplier)} for a in top_albums],
            'top_artists_list': [{'name': a['Artist'], 'image': get_pil_art(a.get('Location'))} for a in top_artists_list],
            'genres': self.wrapped_data.get('genres', []),
            'total_minutes': total_minutes
        }

        # Determine year label from appropriate date
        lbl = self.dd_end.value if self.is_compare_mode and self.dd_end.value else self.dd_start.value
        wrapped_context['year_label'] = lbl.split("-")[0] if lbl else "2025"
        
        start_label = self.dd_start.value.split(" ")[0] if self.dd_start.value else "Unknown"
        end_label = self.dd_end.value.split(" ")[0] if (self.is_compare_mode and self.dd_end.value) else "Present"
        
        wrapped_context['age_data'] = {
            'age': self.wrapped_data.get('age', 0),
            'label': f"During {start_label} to {end_label}"
        }

        if top_artists:
            ta = top_artists[0]
            wrapped_context['top_artist'] = {
                'name': ta['Artist'], 
                'minutes': int(ta['Value'] * min_multiplier), 
                'image': get_pil_art(ta.get('Location'))
            }

        logging.info("Context prepared. Invoking generator...")
        
        self.generated_images = generate_wrapped.generate_card_stack(wrapped_context)
            
        logging.info("Wrapped Generation Complete.")
        self._show_wrapped_ui()

    def _show_wrapped_ui(self):
        self.selected_indices.clear()
        controls = []
        
        for i, img in enumerate(self.generated_images):
            buffered = BytesIO()
            img.convert("RGB").save(buffered, format="JPEG", quality=100)
            b64_str = base64.b64encode(buffered.getvalue()).decode()
            
            def on_check(e, idx=i):
                if e.control.value: self.selected_indices.add(idx)
                else: self.selected_indices.discard(idx)
            
            controls.append(ft.Column([
                ft.Container(content=ft.Image(src_base64=b64_str, fit=ft.ImageFit.CONTAIN, border_radius=10), height=450),
                ft.Checkbox(on_change=on_check) 
            ], horizontal_alignment="center", spacing=5))
        
        self.wrapped_grid.controls = controls
        self.btn_wrapped.content = ft.Row([ft.Icon("auto_awesome"), ft.Text("Generate Wrapped Cards")], alignment="center", spacing=10)
        self.btn_wrapped.update()
        self.toggle_wrapped_modal(True)

    def save_images(self, selected_only: bool):
        self.dir_picker.data = selected_only
        self.dir_picker.get_directory_path()

    def on_save_wrapped_dir(self, e: ft.FilePickerResultEvent):
        if not e.path or not self.generated_images: return
        try:
            selected_only = self.dir_picker.data
            indices = self.selected_indices if selected_only else None
            
            if selected_only and not indices:
                self.page.snack_bar = ft.SnackBar(ft.Text("No images selected!"))
                self.page.snack_bar.open = True
                self.page.update()
                return

            count = generate_wrapped.save_card_stack(self.generated_images, e.path, indices)
                    
            self.page.snack_bar = ft.SnackBar(ft.Text(f"Saved {count} images successfully!"))
            self.page.snack_bar.open = True
            self.page.update()
        except Exception as ex:
            logging.error(f"Save failed: {ex}")

# ==========================================
# APP ENTRY POINT
# ==========================================

def main(page: ft.Page):
    page.title = APP_NAME
    page.theme_mode = "system"
    page.padding = 0
    page.window.min_width = 900
    page.window.min_height = 600
    
    is_linux = page.platform == "linux"
    page.window.frameless = False
    page.window.title_bar_hidden = True
    page.window.title_bar_buttons_hidden = is_linux
    page.window.bgcolor = ft.Colors.TRANSPARENT
    page.bgcolor = ft.Colors.TRANSPARENT
    
    app = TunesBackApp(page)
    page.add(app.main_layout)

if __name__ == "__main__":
    ft.app(target=main)