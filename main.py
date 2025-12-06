import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "libpytunes"))

from libpytunes import Library
import flet as ft
import os
import traceback
import pandas as pd
from collections import defaultdict
from dateutil import parser
import threading
from typing import Optional, Tuple, Dict, List, Set, Any
from dataclasses import dataclass, field
from PIL import Image
from io import BytesIO
import mutagen
import datetime

# Import our generator module
import generate_wrapped

# --- THEME CONFIGURATION ---
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
    # Conversions
    MS_TO_HOURS = 3.6e6
    MS_TO_MINS = 60000
    MS_TO_DAYS = 8.64e7
    # Labels
    UNIT_HOURS = "Hours"
    UNIT_MINUTES = "Minutes"
    UNIT_DAYS = "Days"

# --- DATA STRUCTURES ---

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
    master_pid_map: Dict[str, Dict] = field(default_factory=dict)
    total_time: float = 0.0
    error: Optional[str] = None

# --- PARSING LOGIC ---

def split_artists(artist_str: str) -> List[str]:
    if not artist_str: return ["Unknown"]
    temp = artist_str
    for delim in [',', '&']:
        temp = temp.replace(delim, '|')
    parts = [p.strip() for p in temp.split('|') if p.strip()]
    return parts if parts else ["Unknown"]

def parse_date_added(date_val) -> Optional[datetime.datetime]:
    if not date_val: return None
    if isinstance(date_val, datetime.datetime): return date_val
    try:
        return parser.parse(str(date_val))
    except:
        return None

def parse_xml_library(xml_path: str) -> LibraryData:
    data = LibraryData()
    try:
        lib = Library(xml_path)
    except Exception as e:
        data.error = f"Failed to parse: {str(e)}"
        return data

    for song in lib.songs.values():
        if song.podcast or song.movie or song.has_video: continue
        
        plays = song.play_count or 0
        skips = song.skip_count or 0
        length = song.length or 0
        play_ms = plays * length
        
        if plays == 0 and skips == 0 and not song.date_added:
            pass 

        raw_artist = song.artist or "Unknown"
        album_artist = song.album_artist or raw_artist 
        album = song.album or "Unknown"
        song_name = song.name or "Unknown"
        genre = song.genre
        pid = song.persistent_id
        date_added = parse_date_added(song.date_added)

        data.total_time += play_ms

        if pid:
            data.master_pid_map[pid] = {'count': plays, 'time': play_ms, 'skip': skips}

        def update_stat(stats_obj, p_id):
            stats_obj.count += plays
            stats_obj.time += play_ms
            stats_obj.skip += skips
            if song.location and not stats_obj.location:
                stats_obj.location = song.location
            if date_added:
                stats_obj.added = date_added
            if song.year:
                stats_obj.year = song.year
            if p_id:
                stats_obj.pids.add(p_id)

        song_key = (song_name, raw_artist)
        update_stat(data.songs[song_key], pid)

        alb_key = (album, album_artist)
        update_stat(data.albums[alb_key], pid)

        for ind_art in split_artists(raw_artist):
            update_stat(data.artists[ind_art], pid)

        if genre:
            update_stat(data.genres[genre], pid)

    return data

# --- COMPARISON & CALCULATION ENGINE ---

def calculate_entity_diff(
    new_stats: EntityStats, 
    old_master_map: Dict[str, Dict], 
    old_entity_stats: Optional[EntityStats] = None
) -> Dict[str, float]:
    old_count = 0
    old_time = 0.0
    old_skip = 0

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

def process_library_stats(
    new_lib: LibraryData, 
    old_lib: Optional[LibraryData] = None, 
    start_date: Optional[datetime.datetime] = None, 
    unit: str = Theme.UNIT_HOURS,
    current_year: int = 2025
) -> Tuple:
    
    divisor = Theme.MS_TO_HOURS
    if unit == Theme.UNIT_MINUTES: divisor = Theme.MS_TO_MINS
    elif unit == Theme.UNIT_DAYS: divisor = Theme.MS_TO_DAYS

    old_master = old_lib.master_pid_map if old_lib else {}
    old_total_time = old_lib.total_time if old_lib else 0.0

    diff_total = (new_lib.total_time - old_total_time) / divisor
    diff_plays = sum(s.count for s in new_lib.songs.values()) - (sum(s.count for s in old_lib.songs.values()) if old_lib else 0)

    results = {
        'art': [], 'alb': [], 'song': [], 
        'gen': [], 'new': [], 'skip': []
    }

    def process_category(category_dict, old_category_dict, list_key, label_keys):
        for key, stats in category_dict.items():
            old_stats_obj = old_category_dict.get(key) if old_category_dict else None
            
            diffs = calculate_entity_diff(stats, old_master, old_stats_obj)
            
            def create_row(value_num, count_num):
                row = {
                    'Value': value_num,
                    'Count': int(count_num),
                    'Location': stats.location
                }
                if isinstance(label_keys, list):
                    for i, k in enumerate(label_keys):
                        row[k] = key[i] if isinstance(key, tuple) else key
                else:
                    row[label_keys] = key
                return row

            if diffs['diff_time'] > 0:
                results[list_key].append(create_row(diffs['diff_time'] / divisor, diffs['diff_count']))
            
            if list_key == 'song':
                if diffs['diff_skip'] > 0:
                    results['skip'].append(create_row(diffs['diff_skip'], diffs['diff_skip']))
                
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
                        results['new'].append(create_row(diffs['diff_time'] / divisor, diffs['diff_count']))

    process_category(new_lib.artists, old_lib.artists if old_lib else None, 'art', 'Artist')
    process_category(new_lib.albums, old_lib.albums if old_lib else None, 'alb', ['Album', 'Artist'])
    process_category(new_lib.songs, old_lib.songs if old_lib else None, 'song', ['Song', 'Artist'])
    process_category(new_lib.genres, old_lib.genres if old_lib else None, 'gen', 'Genre')

    genre_df = pd.DataFrame(results['gen'])
    top_genres = []
    if not genre_df.empty:
        top_genres = genre_df.sort_values('Count', ascending=False).head(5)['Genre'].tolist()

    total_age_w = 0
    total_age_p = 0
    old_songs = old_lib.songs if old_lib else {}
    
    for key, stats in new_lib.songs.items():
        if not stats.year or stats.year < 1900: continue
        
        old_c = 0
        if key in old_songs: old_c = old_songs[key].count
        else:
             for pid in stats.pids:
                 if pid in old_master: old_c += old_master[pid]['count']

        p_diff = stats.count - old_c
        if p_diff > 0:
            total_age_w += (current_year - stats.year) * p_diff
            total_age_p += p_diff
            
    avg_age = int(total_age_w / total_age_p) if total_age_p > 0 else 0

    return (
        diff_total, diff_plays,
        pd.DataFrame(results['art']),
        pd.DataFrame(results['alb']),
        pd.DataFrame(results['song']),
        pd.DataFrame(results['gen']),
        pd.DataFrame(results['new']),
        pd.DataFrame(results['skip']),
        top_genres, avg_age
    )

# --- UI UTILS ---

def get_files_in_folder(folder_path: str) -> List[Dict]:
    valid_files = []
    if not os.path.isdir(folder_path): return valid_files
    
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
        except: continue
            
    valid_files.sort(key=lambda x: x['date'])
    seen = defaultdict(int)
    for item in valid_files:
        seen[item['label']] += 1
        if seen[item['label']] > 1:
            item['label'] = f"{item['label']} ({seen[item['label']]})"
    return valid_files

def extract_art_from_file(file_uri: str) -> Optional[Image.Image]:
    if not file_uri: return None
    path = file_uri.replace("file://localhost", "").replace("file://", "")
    import urllib.parse
    path = urllib.parse.unquote(path)
    if not os.path.exists(path): return None
    try:
        f = mutagen.File(path)
        if f is None: return None
        art_data = None
        if 'APIC:' in f.tags: 
             for key in f.tags.keys():
                 if key.startswith('APIC:'):
                     art_data = f.tags[key].data
                     break
        elif 'covr' in f.tags: art_data = f.tags['covr'][0]
        elif hasattr(f, 'pictures') and f.pictures: art_data = f.pictures[0].data

        if art_data: return Image.open(BytesIO(art_data)).convert("RGBA")
    except: return None
    return None

# --- FLET UI COMPONENTS ---

def create_slider_row(label: str, slider: ft.Slider) -> ft.Row:
    return ft.Row([
        ft.Text(label, size=12, weight="bold", width=50),
        ft.Container(content=slider, expand=True)
    ], alignment="center", spacing=5)

def create_kpi_card(content: ft.Control) -> ft.Container:
    return ft.Container(
        content=content, bgcolor=Theme.CARD_BG, padding=15, border_radius=12,
        expand=1, alignment=ft.alignment.center, height=Theme.KPI_HEIGHT
    )

def draw_list_item(rank: int, label: str, sub_label: str, value: float, count: int, unit: str, color: str, is_skip_list: bool=False) -> ft.Container:
    stats = f"{int(value)} skips" if is_skip_list else f"{value:,.1f} {unit} • {int(count)} plays"
    return ft.Container(
        content=ft.Row([
            ft.Row([
                ft.Text(f"{rank}.", weight="bold", color="primary", width=30, size=16),
                ft.Column([
                    ft.Text(label, weight="bold", size=15, overflow="ellipsis", no_wrap=True),
                    ft.Text(sub_label, size=12, color=Theme.SUBTEXT, overflow="ellipsis", no_wrap=True) if sub_label else ft.Container()
                ], spacing=2, expand=True),
            ], expand=True),
            ft.Container(
                content=ft.Text(stats, weight="bold", size=13),
                bgcolor="secondaryContainer", padding=ft.padding.symmetric(horizontal=10, vertical=5), border_radius=10
            )
        ], alignment="spaceBetween"),
        padding=15, bgcolor="surface", border_radius=10, border=ft.border.all(1, "outlineVariant")
    )

# --- MAIN APP CLASS ---

class TunesBackApp:
    def __init__(self, page: ft.Page):
        self.page = page
        import platform as plat
        self.is_macos = plat.system().lower() == "darwin"
        
        self.files = []
        self.full_labels = []
        # UI State
        self.data_frames = {k: pd.DataFrame() for k in ["art", "alb", "song", "gen", "new", "skip"]}
        self.wrapped_data = {"genres": [], "age": 0} 
        self.cached_sorted = {}
        
        # Logic State
        self.lib_start: Optional[LibraryData] = None
        self.lib_end: Optional[LibraryData] = None
        self.is_compare_mode = False
        
        self.analysis_thread: Optional[threading.Thread] = None
        self.cancel_analysis = False
        self.generated_images = [] 
        self.current_tab = "art"
        
        self._init_controls()
        self._build_layout()

    def _init_controls(self):
        self.txt_path = ft.Text("", size=11, color=Theme.SUBTEXT, overflow="ellipsis", max_lines=2, visible=False)
        self.txt_file_count = ft.Text("", size=11, color="primary", weight="bold", visible=False)
        self.btn_select = ft.ElevatedButton("Select Folder", icon="folder", width=float("inf"), height=Theme.BUTTON_HEIGHT, on_click=self.open_file_picker)

        self.dd_start = ft.Dropdown(
            label="Start Date / Single Library", 
            text_size=14, 
            label_style=ft.TextStyle(size=14),
            dense=True, 
            border="outline", 
            border_color=Theme.SUBTEXT,
            border_radius=10,
            disabled=True, 
            width=Theme.TOGGLE_WIDTH, 
            on_change=self.on_start_changed
        )
        
        self.dd_end = ft.Dropdown(
            label="End Date", 
            text_size=14, 
            label_style=ft.TextStyle(size=14),
            dense=True, 
            border="outline", 
            border_color=Theme.SUBTEXT,
            border_radius=10,
            disabled=True, 
            expand=True
        )
        
        self.cb_compare = ft.Checkbox(label="Compare", value=True, disabled=True, on_change=self.on_compare_changed)

        self.sl_art = ft.Slider(min=5, max=100, value=15, divisions=19, label="{value}", disabled=True)
        self.sl_alb = ft.Slider(min=5, max=100, value=15, divisions=19, label="{value}", disabled=True)
        self.sl_song = ft.Slider(min=5, max=100, value=25, divisions=19, label="{value}", disabled=True)
        self.sl_gen = ft.Slider(min=5, max=50, value=10, divisions=9, label="{value}", disabled=True) 
        
        self.cb_album_art = ft.Checkbox(label="Show Album Art (Slow)", value=False, disabled=True)

        self.seg_unit = ft.SegmentedButton(
            selected={Theme.UNIT_HOURS},
            segments=[ft.Segment(value=v, label=ft.Text(l)) for v, l in [(Theme.UNIT_HOURS, "Hrs"), (Theme.UNIT_MINUTES, "Mins"), (Theme.UNIT_DAYS, "Days")]],
            disabled=True, allow_multiple_selection=False, on_change=self.on_unit_changed, width=Theme.TOGGLE_WIDTH
        )
        self.seg_sort = ft.SegmentedButton(
            selected={"time"},
            segments=[ft.Segment(value="time", label=ft.Text("Time")), ft.Segment(value="count", label=ft.Text("Plays"))],
            disabled=True, allow_multiple_selection=False, on_change=self.update_results_ui, width=Theme.TOGGLE_WIDTH
        )

        self.btn_run = ft.ElevatedButton("Generate Recap", icon="bar_chart", style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8), padding=20), expand=True, disabled=True, on_click=self.run_analysis)
        self.btn_cancel = ft.ElevatedButton("Cancel", icon="close", color="error", style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8), padding=20), expand=True, visible=False, on_click=self.cancel_analysis_handler)

        self.btn_reset = ft.IconButton(icon="refresh", tooltip="Reset View", disabled=True, on_click=self.reset_view)
        self.btn_theme = ft.IconButton(icon="light_mode", icon_size=18, tooltip="Toggle Theme", on_click=self.toggle_theme)
        self.btn_minimize = ft.IconButton(icon="remove", icon_size=14, on_click=self.minimize_app)
        self.btn_close = ft.IconButton(icon="close", icon_size=14, on_click=self.close_app)

        self.file_picker = ft.FilePicker(on_result=self.on_folder_picked)
        self.dir_picker = ft.FilePicker(on_result=self.on_save_wrapped_dir)
        self.page.overlay.extend([self.file_picker, self.dir_picker])

        self.tabs_row = ft.Row(spacing=0, scroll="auto", expand=True)
        self.btn_wrapped = ft.ElevatedButton(
            text="Generate Wrapped Cards", 
            icon="auto_awesome", 
            bgcolor="tertiary", 
            color="onTertiary", 
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)), 
            height=40, 
            visible=False, 
            on_click=self.start_wrapped_generation
        )
        self.spinner_wrapped = ft.ProgressRing(width=20, height=20, stroke_width=2, visible=False)

        self.list_results = ft.ListView(expand=True, spacing=10, padding=ft.padding.symmetric(horizontal=10, vertical=10))
        self.kpi_growth = ft.Text("0.0", size=32, weight="bold", color="primary")
        self.kpi_growth_u = ft.Text(f"{Theme.UNIT_HOURS} Growth", size=14, weight="bold", color=Theme.SUBTEXT)
        self.kpi_plays = ft.Text("0", size=32, weight="bold", color="primary")
        self.kpi_plays_u = ft.Text("New Plays", size=14, weight="bold", color=Theme.SUBTEXT)
        
        self.card_vals = [ft.Text("-", size=16, weight="bold", overflow="ellipsis", text_align="center", no_wrap=True) for _ in range(3)]
        self.card_subs = [ft.Text("-", size=11, color=Theme.SUBTEXT, text_align="center") for _ in range(3)]

        self.txt_app_title = ft.Text("TunesBack", weight="bold", size=14, color=Theme.SUBTEXT, opacity=0, animate_opacity=300)
        self.txt_loading_status = ft.Text("Crunching numbers...", size=16, weight="bold", color=Theme.SUBTEXT)

        # Modals
        self.modal_title = ft.Text("Error", weight="bold", size=20)
        self.modal_text = ft.Text("Msg")
        self.modal_container = ft.Container(
            content=ft.Container(
                content=ft.Column([
                    self.modal_title,
                    self.modal_text,
                    ft.Row([ft.TextButton("OK", on_click=lambda e: self.toggle_modal(False))], alignment="end")
                ], spacing=10, tight=True),
                padding=25, bgcolor="surface", border_radius=12, width=350, shadow=ft.BoxShadow(blur_radius=20, color=ft.Colors.with_opacity(0.5, "black"))
            ), bgcolor=ft.Colors.with_opacity(0.6, "black"), alignment=ft.alignment.center, visible=False, expand=True
        )
        
        self.wrapped_grid = ft.Row(scroll="auto", expand=True) 
        self.wrapped_modal = ft.Container(
             content=ft.Container(
                content=ft.Column([
                    ft.Text("Your Journey Recap", size=24, weight="bold"),
                    ft.Container(content=self.wrapped_grid, height=500, expand=True, border_radius=10, border=ft.border.all(1, "outline")),
                    ft.Row([
                        ft.TextButton("Close", on_click=lambda e: self.toggle_wrapped_modal(False)),
                        ft.ElevatedButton("Save All Images", icon="save_alt", on_click=lambda e: self.dir_picker.get_directory_path())
                    ], alignment="spaceBetween")
                ], spacing=20),
                padding=30, bgcolor="surface", border_radius=15, width=900, height=700, shadow=ft.BoxShadow(blur_radius=30, color="black")
            ), bgcolor=ft.Colors.with_opacity(0.8, "black"), alignment=ft.alignment.center, visible=False, expand=True
        )

    # --- UI HELPERS ---

    def _create_custom_tab_button(self, key, label, icon):
        is_selected = (self.current_tab == key)
        if is_selected:
            return ft.Container(
                content=ft.FilledButton(
                    text=label, icon=icon, 
                    style=ft.ButtonStyle(shape=ft.StadiumBorder()),
                    on_click=lambda e: self.on_custom_tab_clicked(key)
                ),
                padding=ft.padding.only(right=10)
            )
        else:
            return ft.Container(
                content=ft.OutlinedButton(
                    text=label, icon=icon, 
                    style=ft.ButtonStyle(shape=ft.StadiumBorder()),
                    on_click=lambda e: self.on_custom_tab_clicked(key)
                ),
                padding=ft.padding.only(right=10)
            )

    def _render_tabs(self):
        tabs = [("art", "Artists", "mic"), ("alb", "Albums", "album"), ("song", "Songs", "music_note"), 
                ("gen", "Genres", "category"), ("new", "New Finds", "new_releases"), ("skip", "Skipped", "fast_forward")]
        self.tabs_row.controls = [self._create_custom_tab_button(k, l, i) for k, l, i in tabs]

    def on_custom_tab_clicked(self, key):
        self.current_tab = key
        self._render_tabs()
        self.tabs_row.update()
        self.update_results_ui(None)

    def _build_layout(self):
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
            create_kpi_card(ft.Column([ft.Text("Top Artist", size=10, color=Theme.SUBTEXT), self.card_vals[0], self.card_subs[0]], horizontal_alignment="center", alignment="center", spacing=2)),
            create_kpi_card(ft.Column([ft.Text("Top Album", size=10, color=Theme.SUBTEXT), self.card_vals[1], self.card_subs[1]], horizontal_alignment="center", alignment="center", spacing=2)),
            create_kpi_card(ft.Column([ft.Text("Top Song", size=10, color=Theme.SUBTEXT), self.card_vals[2], self.card_subs[2]], horizontal_alignment="center", alignment="center", spacing=2)),
        ], spacing=15, expand=True)

        header_row = ft.Row([
            ft.Container(content=ft.Column([ft.Column([self.kpi_growth, self.kpi_growth_u], spacing=0), ft.Column([self.kpi_plays, self.kpi_plays_u], spacing=0)], alignment="spaceBetween", spacing=0), height=Theme.KPI_HEIGHT, alignment=ft.alignment.center_left),
            ft.Container(width=40), kpi_row
        ], alignment="start", vertical_alignment="center")

        results_box = ft.Container(content=self.list_results, bgcolor=ft.Colors.with_opacity(0.05, "black"), border_radius=10, border=ft.border.all(1, "outlineVariant"), expand=True, padding=0)
        
        self.view_dash = ft.Column([
            ft.Container(padding=ft.padding.only(left=Theme.PAD_LEFT, right=Theme.PAD_RIGHT), 
                         content=ft.Column([ft.Container(height=10), header_row, ft.Container(height=20), 
                                            ft.Row([self.tabs_row, ft.Container(width=10), ft.Row([self.btn_wrapped, self.spinner_wrapped], spacing=10)], alignment="spaceBetween", vertical_alignment="center"), 
                                            ft.Container(height=10)])),
            ft.Container(padding=ft.padding.only(left=Theme.PAD_LEFT, right=Theme.PAD_RIGHT, bottom=10), content=results_box, expand=True)
        ], expand=True, visible=False, spacing=0)

        exp_sliders = ft.Container(
            border=ft.border.all(1, Theme.SUBTEXT),
            border_radius=10,
            content=ft.ExpansionTile(
                title=ft.Container(
                    content=ft.Text("Number of Items To Show", size=12, weight="bold"),
                    padding=ft.padding.only(left=5)
                ),
                controls=[
                    ft.Container(
                        content=ft.Column([
                            create_slider_row("Artists", self.sl_art), 
                            create_slider_row("Albums", self.sl_alb), 
                            create_slider_row("Songs", self.sl_song), 
                            create_slider_row("Genres", self.sl_gen)
                        ], spacing=-5), 
                        padding=ft.padding.only(bottom=10, left=10, right=10)
                    )
                ],
                initially_expanded=False,
                tile_padding=ft.padding.symmetric(horizontal=5),
                shape=ft.RoundedRectangleBorder(radius=10),
                collapsed_shape=ft.RoundedRectangleBorder(radius=10),
                bgcolor=ft.Colors.TRANSPARENT,
            )
        )

        sidebar = ft.Container(width=Theme.SIDEBAR_WIDTH, bgcolor=Theme.SIDEBAR_BG, padding=0,
            content=ft.Column([ft.Container(padding=20, content=ft.Column([
                ft.Row([ft.Text("SETTINGS", size=12, weight="bold", color=Theme.SUBTEXT), self.btn_theme], alignment="spaceBetween"), ft.Divider(),
                ft.Text("Source", size=12, weight="bold"), self.btn_select, self.txt_path, self.txt_file_count, ft.Divider(),
                ft.Text("Period", size=12, weight="bold"), ft.Column([self.dd_start, ft.Row([self.dd_end, self.cb_compare], alignment="spaceBetween", vertical_alignment="center")], spacing=20), ft.Divider(),
                exp_sliders, 
                self.cb_album_art,
                ft.Divider(),
                ft.Text("Units & Ranking", size=12, weight="bold"), ft.Column([ft.Text("Time Unit", size=11, color=Theme.SUBTEXT), self.seg_unit, ft.Text("Rank By", size=11, color=Theme.SUBTEXT), self.seg_sort], spacing=5),
                ft.Container(height=20), ft.Stack([ft.Row([self.btn_run, self.btn_reset], spacing=10), self.btn_cancel])
            ], spacing=10))], scroll="auto"))

        window_header = ft.WindowDragArea(content=ft.Container(
            content=ft.Row([self.txt_app_title, ft.Row([self.btn_minimize, self.btn_close], spacing=0) if not self.is_macos else ft.Container()], alignment="spaceBetween"),
            padding=ft.padding.only(left=Theme.PAD_LEFT, right=20, top=30 if self.is_macos else 20, bottom=10), bgcolor=Theme.CONTENT_BG
        ))

        self.main_layout = ft.Container(content=ft.Stack([
            ft.Row([sidebar, ft.Container(content=ft.Column([window_header, ft.Container(expand=True, bgcolor=Theme.CONTENT_BG, padding=0, content=ft.Column([ft.Stack([self.view_welcome, self.view_dash, self.view_loading], expand=True)], spacing=0))], spacing=0), expand=True)], expand=True, spacing=0, vertical_alignment="stretch"),
            self.modal_container, self.wrapped_modal
        ]), expand=True)

    # --- EVENT HANDLERS ---

    def minimize_app(self, e): self.page.window.minimized = True; self.page.update()
    def close_app(self, e): self.page.window.close()
    
    def toggle_modal(self, show: bool, title: str = "", msg: str = ""):
        self.modal_container.visible = show; self.modal_title.value = title; self.modal_text.value = msg; self.page.update()
    def toggle_wrapped_modal(self, show: bool):
        self.wrapped_modal.visible = show; self.page.update()

    def open_file_picker(self, e): self.file_picker.get_directory_path()

    def on_folder_picked(self, e: ft.FilePickerResultEvent):
        if not e.path: return
        self.txt_path.value = e.path; self.txt_path.color = Theme.SUBTEXT; self.txt_path.visible = True; self.txt_file_count.visible = True
        self.files = get_files_in_folder(e.path)
        if self.files:
            self.full_labels = [f['label'] for f in self.files]
            opts = [ft.dropdown.Option(lbl) for lbl in self.full_labels]
            self.dd_start.options = opts; self.dd_end.options = [ft.dropdown.Option(lbl) for lbl in self.full_labels]
            self.dd_start.value = opts[0].key; self.dd_end.value = opts[-1].key if len(opts) > 1 else None
            
            is_single = len(self.files) == 1
            self.cb_compare.value = not is_single; self.cb_compare.disabled = is_single
            self.dd_end.disabled = is_single
            self.txt_file_count.value = "Found 1 snapshot." if is_single else f"Found {len(self.files)} snapshots"
            
            for c in [self.dd_start, self.btn_run, self.sl_art, self.sl_alb, self.sl_song, self.sl_gen, self.seg_unit, self.seg_sort, self.cb_album_art]: c.disabled = False
            self.on_start_changed(None)
        else:
            self.txt_path.value = "No dated XML files found."; self.txt_path.color = "error"
        self.page.update()

    def on_compare_changed(self, e):
        self.dd_end.disabled = not self.cb_compare.value
        if not self.cb_compare.value: self.dd_end.value = None
        else: self.dd_end.value = self.dd_end.options[-1].key if self.dd_end.options else None
        self.page.update()

    def on_start_changed(self, e):
        if not self.full_labels: return
        new_end_opts = [ft.dropdown.Option(lbl) for lbl in self.full_labels if lbl != self.dd_start.value]
        self.dd_end.options = new_end_opts
        if self.cb_compare.value and new_end_opts and (not self.dd_end.value or self.dd_end.value == self.dd_start.value):
            self.dd_end.value = new_end_opts[-1].key
        self.dd_end.update()

    def on_unit_changed(self, e):
        if not self.lib_start: return
        self._calculate_and_refresh()

    def _calculate_and_refresh(self):
        start_file = next((f for f in self.files if f['label'] == self.dd_start.value), None)
        start_date = start_file['date'] if start_file else None
        end_year = self.files[-1]['date'].year if self.files else 2025

        unit = list(self.seg_unit.selected)[0]
        
        stats = process_library_stats(
            new_lib=self.lib_start if not self.is_compare_mode else self.lib_end,
            old_lib=self.lib_start if self.is_compare_mode else None,
            start_date=start_date,
            unit=unit,
            current_year=end_year
        )
        
        (val_main, val_plays, df_art, df_alb, df_song, df_gen, df_new, df_skip, top_genres, age) = stats
        
        self.wrapped_data = {"genres": top_genres, "age": age}
        self.data_frames = {"art": df_art, "alb": df_alb, "song": df_song, "gen": df_gen, "new": df_new, "skip": df_skip}
        self.cached_sorted.clear()
        
        prefix = f"{unit} Growth" if self.is_compare_mode else f"Total {unit}"
        self.kpi_growth.value = f"{val_main:,.1f}"; self.kpi_growth_u.value = prefix
        self.kpi_plays.value = f"{int(val_plays):,}"; self.kpi_plays_u.value = "New Plays" if self.is_compare_mode else "Total Plays"
        
        self._update_top_cards(unit)
        self.update_results_ui(None)
        self.page.update()

    def cancel_analysis_handler(self, e):
        self.cancel_analysis = True
        self.txt_loading_status.value = "Cancelling..."
        self.page.update()

    def run_analysis(self, e):
        if not self.dd_start.value: return
        
        # CHANGED: Explicit date check logic before thread starts
        try:
            start_file = next(f for f in self.files if f['label'] == self.dd_start.value)
            if self.cb_compare.value:
                if not self.dd_end.value:
                    return
                end_file = next(f for f in self.files if f['label'] == self.dd_end.value)
                
                # STRICT COMPARISON
                if start_file['date'] > end_file['date']:
                    self.toggle_modal(True, "Invalid Range", "Start Date cannot be after End Date.")
                    return
        except StopIteration:
            self.toggle_modal(True, "Error", "Selected file not found.")
            return

        self.cancel_analysis = False
        self.analysis_thread = threading.Thread(target=self._run_analysis_thread, daemon=True)
        self.analysis_thread.start()

    def _run_analysis_thread(self):
        try:
            start_file = next(f for f in self.files if f['label'] == self.dd_start.value)
            
            self._set_loading_state(True)
            self.txt_loading_status.value = "Parsing first library..."
            self.page.update()
            
            self.lib_start = parse_xml_library(start_file['path'])
            if self.lib_start.error: raise Exception(self.lib_start.error)
            if self.cancel_analysis: return self._set_loading_state(False)

            self.is_compare_mode = self.cb_compare.value
            self.lib_end = None

            if self.is_compare_mode:
                if not self.dd_end.value: return
                end_file = next(f for f in self.files if f['label'] == self.dd_end.value)
                
                self.txt_loading_status.value = "Parsing second library..."
                self.page.update()
                
                self.lib_end = parse_xml_library(end_file['path'])
                if self.lib_end.error: raise Exception(self.lib_end.error)
                if self.cancel_analysis: return self._set_loading_state(False)
                
                self.txt_loading_status.value = "Calculating differences..."
                self.page.update()
            else:
                self.txt_loading_status.value = "Calculating stats..."
                self.page.update()

            self._calculate_and_refresh()
            self._set_loading_state(False)

        except Exception as ex:
            print(traceback.format_exc())
            self.toggle_modal(True, "Error", str(ex))
            self._set_loading_state(False)

    def _set_loading_state(self, is_loading: bool):
        self.view_loading.visible = is_loading; self.view_welcome.visible = False
        self.view_dash.visible = not is_loading and bool(self.data_frames["art"].size)
        if not is_loading and not self.data_frames["art"].size: self.view_welcome.visible = True
        
        self.btn_run.visible = not is_loading; self.btn_cancel.visible = is_loading; self.btn_reset.disabled = is_loading
        self.txt_app_title.opacity = 0 if is_loading else 1
        self.btn_wrapped.visible = not is_loading and self.is_compare_mode; self.spinner_wrapped.visible = False 
        if not is_loading: self.txt_loading_status.value = "Crunching numbers..."
        self.page.update()

    def _update_top_cards(self, unit: str):
        dfs = [self.data_frames["art"], self.data_frames["alb"], self.data_frames["song"]]
        keys = ["Artist", "Album", "Song"]
        for i, df in enumerate(dfs):
            if df.empty: self.card_vals[i].value = "-"; self.card_subs[i].value = "-"
            else:
                top = df.sort_values('Value', ascending=False).iloc[0]
                self.card_vals[i].value = top[keys[i]]
                self.card_subs[i].value = f"{top['Value']:.1f} {unit} • {int(top['Count'])} plays"

    def update_results_ui(self, e):
        unit = list(self.seg_unit.selected)[0]
        sort_mode = list(self.seg_sort.selected)[0]
        
        configs = {
            "art": (self.data_frames["art"], int(self.sl_art.value), "cyan", "Artist", None, False),
            "alb": (self.data_frames["alb"], int(self.sl_alb.value), "purple", "Album", "Artist", False),
            "song": (self.data_frames["song"], int(self.sl_song.value), "pink", "Song", "Artist", False),
            "gen": (self.data_frames["gen"], int(self.sl_gen.value), "teal", "Genre", None, False),
            "new": (self.data_frames["new"], int(self.sl_song.value), "orange", "Song", "Artist", False),
            "skip": (self.data_frames["skip"], int(self.sl_song.value), "red", "Song", "Artist", True),
        }
        
        df, limit, color, main_col, sub_col, is_skip = configs.get(self.current_tab, configs["art"])
        self.list_results.controls.clear()
        
        if df.empty:
            self.list_results.controls.append(ft.Text("No data to display.", italic=True))
        else:
            cache_key = (self.current_tab, sort_mode)
            if cache_key not in self.cached_sorted:
                sort_col = 'Value' if sort_mode == 'time' else 'Count'
                self.cached_sorted[cache_key] = df.sort_values(sort_col, ascending=False)
            
            df_sorted = self.cached_sorted[cache_key].head(limit)
            
            for i, row in enumerate(df_sorted.itertuples(), 1):
                lbl = getattr(row, main_col)
                sub = getattr(row, sub_col) if sub_col else ""
                self.list_results.controls.append(draw_list_item(i, lbl, sub, getattr(row, "Value"), getattr(row, "Count"), unit, color, is_skip))
        self.list_results.update()

    def reset_view(self, e):
        self.view_welcome.visible = True; self.view_dash.visible = False; self.btn_reset.disabled = True; self.txt_app_title.opacity = 0
        self.data_frames = {k: pd.DataFrame() for k in ["art", "alb", "song", "gen", "new", "skip"]}
        self.cached_sorted.clear(); self.lib_start = None; self.lib_end = None
        self.page.update()

    def toggle_theme(self, e):
        self.page.theme_mode = 'light' if self.page.theme_mode == 'dark' else 'dark'
        self.btn_theme.icon = 'dark_mode' if self.page.theme_mode == 'light' else 'light_mode'
        self.page.update()
        
    def start_wrapped_generation(self, e):
        if not self.is_compare_mode: return
        self.btn_wrapped.visible = False; self.spinner_wrapped.visible = True; self.page.update()
        threading.Thread(target=self._generate_wrapped_thread, daemon=True).start()

    def _generate_wrapped_thread(self):
        sort_mode = list(self.seg_sort.selected)[0]
        sort_col = 'Value' if sort_mode == 'time' else 'Count'
        
        top_songs = self.data_frames['song'].sort_values(sort_col, ascending=False).head(5).to_dict('records')
        top_albums = self.data_frames['alb'].sort_values(sort_col, ascending=False).head(5).to_dict('records')
        top_artists = self.data_frames['art'].sort_values(sort_col, ascending=False).head(1).to_dict('records')
        
        songs_data = []; albums_data = []
        
        for s in top_songs: songs_data.append({'name': s['Song'], 'sub': s['Artist'], 'image': extract_art_from_file(s.get('Location'))})
        for a in top_albums: albums_data.append({'name': a['Album'], 'sub': a['Artist'], 'image': extract_art_from_file(a.get('Location'))})
            
        top_artist_data = None
        if top_artists:
            ta = top_artists[0]
            top_artist_data = {'name': ta['Artist'], 'minutes': int(ta['Value'] * 60), 'image': extract_art_from_file(ta.get('Location'))}

        self.generated_images = []
        self.generated_images.append(generate_wrapped.draw_top_songs(songs_data, "#1DB954"))
        self.generated_images.append(generate_wrapped.draw_top_albums(albums_data, "#2196F3"))
        
        if albums_data:
            top_alb = albums_data[0]
            self.generated_images.append(generate_wrapped.draw_single_top_album(top_alb['name'], top_alb['sub'], int(top_albums[0]['Value'] * 60) if top_albums else 0, top_alb['image']))

        self.generated_images.append(generate_wrapped.draw_top_genres(self.wrapped_data.get('genres', [])))
        self.generated_images.append(generate_wrapped.draw_listening_age(self.wrapped_data.get('age', 0), f"Based on your listening habits in {self.dd_end.value.split()[0][:4]}"))
        
        if top_artist_data:
            self.generated_images.append(generate_wrapped.draw_top_artist_spotlight(top_artist_data['name'], top_artist_data['minutes'], top_artist_data['image']))
            
        self._show_wrapped_ui()

    def _show_wrapped_ui(self):
        import base64
        controls = []
        for i, img in enumerate(self.generated_images):
            buffered = BytesIO()
            img.convert("RGB").save(buffered, format="JPEG", quality=85)
            b64_str = base64.b64encode(buffered.getvalue()).decode()
            controls.append(ft.Container(content=ft.Image(src_base64=b64_str, fit=ft.ImageFit.CONTAIN, border_radius=10), height=450, margin=ft.margin.only(right=20)))
        
        self.wrapped_grid.controls = controls
        self.spinner_wrapped.visible = False; self.btn_wrapped.visible = True
        self.toggle_wrapped_modal(True)

    def on_save_wrapped_dir(self, e: ft.FilePickerResultEvent):
        if not e.path or not self.generated_images: return
        try:
            for i, img in enumerate(self.generated_images):
                img.convert("RGB").save(os.path.join(e.path, f"tunesback_journey_{i+1}.jpg"), "JPEG", quality=95)
            self.page.snack_bar = ft.SnackBar(ft.Text(f"Saved {len(self.generated_images)} images successfully!")); self.page.snack_bar.open = True; self.page.update()
        except Exception as ex: print(f"Save failed: {ex}")

def main(page: ft.Page):
    page.title = "TunesBack"
    page.theme_mode = "system"
    page.padding = 0
    page.window.min_width = 900
    page.window.min_height = 600
    
    is_linux = page.platform == "linux"
    page.window.frameless = False; page.window.title_bar_hidden = True; page.window.title_bar_buttons_hidden = is_linux
    page.window.bgcolor = ft.Colors.TRANSPARENT; page.bgcolor = ft.Colors.TRANSPARENT
    
    app = TunesBackApp(page)
    page.add(app.main_layout)

if __name__ == "__main__":
    ft.app(target=main)