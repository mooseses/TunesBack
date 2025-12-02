import flet as ft
import os
import traceback
import pandas as pd
from collections import defaultdict
from dateutil import parser
from libpytunes import Library


# =============================================================================
# 1. CONFIGURATION & THEME
# =============================================================================

class Theme:
    SIDEBAR_BG = "surfaceVariant"
    CONTENT_BG = "background"
    CARD_BG = "secondaryContainer"
    SUBTEXT = "outline"
    PAD_LEFT = 50
    PAD_RIGHT = 30
    KPI_HEIGHT = 140


# Conversion Constants
MS_TO_HOURS = 3.6e6
MS_TO_MINS = 60000


# =============================================================================
# 2. BACKEND LOGIC
# =============================================================================

def get_files_in_folder(folder_path):
    """Scans folder for XML files, parses dates, and handles duplicates."""
    valid_files = []
    if os.path.isdir(folder_path):
        for f in os.listdir(folder_path):
            if f.endswith('.xml'):
                clean_name = os.path.splitext(f)[0]
                try:
                    dt = parser.parse(clean_name, fuzzy=True)
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

    return valid_files


def parse_xml_library(xml_path):
    """Parses iTunes XML using libpytunes and aggregates data."""
    try:
        lib = Library(xml_path)
    except Exception as e:
        return None, None, 0, str(e)

    artist_data = defaultdict(lambda: defaultdict(lambda: {'count': 0, 'time': 0.0}))
    song_data = defaultdict(lambda: {'count': 0, 'time': 0.0})
    total_time_ms = 0.0

    for song in lib.songs.values():
        if not song.play_count or not song.length: continue
        if song.podcast or song.movie or song.has_video: continue

        artist = song.album_artist if song.album_artist else song.artist
        specific_artist = song.artist if song.artist else "Unknown"
        album = song.album if song.album else "Unknown"

        play_ms = song.play_count * song.length
        total_time_ms += play_ms

        artist_data[artist][album]['count'] += song.play_count
        artist_data[artist][album]['time'] += play_ms

        key = (song.name, specific_artist)
        song_data[key]['count'] += song.play_count
        song_data[key]['time'] += play_ms

    return artist_data, song_data, total_time_ms, None


def calculate_stats(old_res, new_res, unit="Hours"):
    """Calculates growth stats between two snapshots."""
    divisor = MS_TO_MINS if unit == "Minutes" else MS_TO_HOURS
    old_artists, old_songs, old_total, _ = old_res
    new_artists, new_songs, new_total, _ = new_res

    diff_total = (new_total - old_total) / divisor
    new_plays = sum(item['count'] for item in new_songs.values())
    old_plays = sum(item['count'] for item in old_songs.values())
    diff_plays = new_plays - old_plays

    artist_list, album_list, song_list = [], [], []

    for artist, albums in new_artists.items():
        for album, stats in albums.items():
            new_time = stats['time']
            new_count = stats['count']
            old_stats = old_artists.get(artist, {}).get(album, {'time': 0.0, 'count': 0})

            diff_time = new_time - old_stats['time']
            diff_count = new_count - old_stats['count']

            if diff_time > 0:
                found = next((i for i in artist_list if i['Artist'] == artist), None)
                if found:
                    found['Value'] += diff_time / divisor
                    found['Count'] += diff_count
                else:
                    artist_list.append({'Artist': artist, 'Value': diff_time / divisor, 'Count': diff_count})

                album_list.append({'Album': album, 'Artist': artist, 'Value': diff_time / divisor, 'Count': diff_count})

    for key, stats in new_songs.items():
        name, artist = key
        old_stats = old_songs.get(key, {'time': 0.0, 'count': 0})
        diff_time = stats['time'] - old_stats['time']
        diff_count = stats['count'] - old_stats['count']

        if diff_time > 0:
            song_list.append({'Song': name, 'Artist': artist, 'Value': diff_time / divisor, 'Count': diff_count})

    return diff_total, diff_plays, pd.DataFrame(artist_list), pd.DataFrame(album_list), pd.DataFrame(song_list)


def calculate_single_stats(res, unit="Hours"):
    """Calculates stats for a single snapshot."""
    divisor = MS_TO_MINS if unit == "Minutes" else MS_TO_HOURS
    artists, songs, total_time_ms, _ = res

    total_val = total_time_ms / divisor
    total_plays = sum(item['count'] for item in songs.values())

    artist_list, album_list, song_list = [], [], []

    for artist, albums in artists.items():
        for album, stats in albums.items():
            val = stats['time'] / divisor
            count = stats['count']

            found = next((i for i in artist_list if i['Artist'] == artist), None)
            if found:
                found['Value'] += val
                found['Count'] += count
            else:
                artist_list.append({'Artist': artist, 'Value': val, 'Count': count})

            album_list.append({'Album': album, 'Artist': artist, 'Value': val, 'Count': count})

    for key, stats in songs.items():
        name, artist = key
        song_list.append({
            'Song': name, 'Artist': artist,
            'Value': stats['time'] / divisor,
            'Count': stats['count']
        })

    return total_val, total_plays, pd.DataFrame(artist_list), pd.DataFrame(album_list), pd.DataFrame(song_list)


# =============================================================================
# 3. UI COMPONENTS
# =============================================================================

def create_slider_row(label, slider):
    return ft.Row([
        ft.Text(label, size=12, weight="bold", width=50),
        ft.Container(content=slider, expand=True)
    ], alignment="center", spacing=5)


def create_kpi_card(content):
    return ft.Container(
        content=content, bgcolor=Theme.CARD_BG, padding=15, border_radius=12,
        expand=1, alignment=ft.alignment.center, height=Theme.KPI_HEIGHT
    )


def draw_list_item(rank, label, sub_label, value, count, unit, color):
    stats = f"{value:,.1f} {unit} • {int(count)} plays"
    return ft.Container(
        content=ft.Row([
            ft.Row([
                ft.Text(f"{rank}.", weight="bold", color="primary", width=30, size=16),
                ft.Column([
                    ft.Text(label, weight="bold", size=15, overflow="ellipsis", no_wrap=True),
                    ft.Text(sub_label, size=12, color=Theme.SUBTEXT, overflow="ellipsis",
                            no_wrap=True) if sub_label else ft.Container()
                ], spacing=2, expand=True),
            ], expand=True),
            ft.Container(
                content=ft.Text(stats, weight="bold", size=13, color=None),
                bgcolor="secondaryContainer", padding=ft.padding.symmetric(horizontal=10, vertical=5), border_radius=10
            )
        ], alignment="spaceBetween"),
        padding=15, bgcolor="surface", border_radius=10, border=ft.border.all(1, "outlineVariant")
    )


# =============================================================================
# 4. MAIN APPLICATION
# =============================================================================

class TunesBackApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self.files = []
        self.full_labels = []
        self.data_frames = {"art": pd.DataFrame(), "alb": pd.DataFrame(), "song": pd.DataFrame()}

        self._init_controls()
        self._build_layout()

    def _init_controls(self):
        # --- Sidebar Controls ---

        # Source Selection (Hidden initially)
        self.txt_path = ft.Text("", size=11, color="error", overflow="ellipsis", max_lines=2, visible=False)
        self.txt_file_count = ft.Text("", size=11, color="primary", weight="bold", visible=False)
        self.btn_select = ft.ElevatedButton("Select Folder", icon="folder", width=float("inf"), height=50,
                                            on_click=self.open_file_picker)

        # Date Dropdowns
        self.dd_start = ft.Dropdown(
            label="Start Date / Single Library",
            text_size=14,
            label_style=ft.TextStyle(size=14),
            dense=True, border="outline", disabled=True, width=260,
            on_change=self.on_start_changed
        )
        self.dd_end = ft.Dropdown(
            label="End Date",
            text_size=14,
            label_style=ft.TextStyle(size=14),
            dense=True, border="outline", disabled=True, expand=True
        )
        self.cb_compare = ft.Checkbox(label="Compare", value=True, disabled=True, on_change=self.on_compare_changed)

        # Sliders
        self.sl_art = ft.Slider(min=5, max=100, value=15, divisions=19, label="{value}", disabled=True)
        self.sl_alb = ft.Slider(min=5, max=100, value=15, divisions=19, label="{value}", disabled=True)
        self.sl_song = ft.Slider(min=5, max=100, value=25, divisions=19, label="{value}", disabled=True)

        # Toggle Buttons (Fixed width)
        self.seg_unit = ft.SegmentedButton(
            selected={"Hours"}, segments=[ft.Segment(value="Hours", label=ft.Text("Hours")),
                                          ft.Segment(value="Minutes", label=ft.Text("Minutes"))],
            disabled=True, allow_multiple_selection=False, on_change=self.update_results_ui, width=260
        )
        self.seg_sort = ft.SegmentedButton(
            selected={"time"}, segments=[ft.Segment(value="time", label=ft.Text("Time")),
                                         ft.Segment(value="count", label=ft.Text("Plays"))],
            disabled=True, allow_multiple_selection=False, on_change=self.update_results_ui, width=260
        )

        # Action Buttons
        self.btn_run = ft.ElevatedButton("Generate Recap", icon="bar_chart",
                                         style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8), padding=20),
                                         expand=True, disabled=True, on_click=self.run_analysis)
        self.btn_reset = ft.IconButton(icon="refresh", tooltip="Reset View", disabled=True, on_click=self.reset_view)
        self.btn_theme = ft.IconButton(icon="light_mode", icon_size=18, tooltip="Toggle Theme",
                                       on_click=self.toggle_theme)

        # File Picker
        self.file_picker = ft.FilePicker(on_result=self.on_folder_picked)
        self.page.overlay.append(self.file_picker)

        # --- Dashboard Controls ---
        self.tabs_main = ft.Tabs(
            selected_index=0, animation_duration=300, indicator_color="primary", label_color="primary",
            tabs=[ft.Tab(text="Top Artists", icon="mic"), ft.Tab(text="Top Albums", icon="album"),
                  ft.Tab(text="Top Songs", icon="music_note")],
            on_change=self.update_results_ui
        )
        self.list_results = ft.ListView(expand=True, spacing=10, padding=20)

        # KPI & Title
        self.kpi_growth = ft.Text("0.0", size=32, weight="bold", color="primary")
        self.kpi_growth_u = ft.Text("Hours Growth", size=14, weight="bold", color=Theme.SUBTEXT)
        self.kpi_plays = ft.Text("0", size=32, weight="bold", color="primary")
        self.kpi_plays_u = ft.Text("New Plays", size=14, weight="bold", color=Theme.SUBTEXT)

        self.card_vals = [ft.Text("-", size=16, weight="bold", overflow="ellipsis", text_align="center", no_wrap=True)
                          for _ in range(3)]
        self.card_subs = [ft.Text("-", size=11, color=Theme.SUBTEXT, text_align="center") for _ in range(3)]

        self.txt_app_title = ft.Text("TunesBack", weight="bold", size=14, color=Theme.SUBTEXT, opacity=0,
                                     animate_opacity=300)

        # --- Modal ---
        self.modal_title = ft.Text("Error", weight="bold", size=20)
        self.modal_text = ft.Text("Something went wrong.")
        self.modal_container = ft.Container(
            content=ft.Container(
                content=ft.Column([
                    self.modal_title, self.modal_text,
                    ft.Row([ft.TextButton("OK", on_click=lambda e: self.toggle_modal(False))], alignment="end")
                ], spacing=10, tight=True),
                padding=25, bgcolor="surface", border_radius=12, width=350,
                shadow=ft.BoxShadow(blur_radius=20, color=ft.Colors.with_opacity(0.5, "black"))
            ),
            bgcolor=ft.Colors.with_opacity(0.6, "black"), alignment=ft.alignment.center, visible=False, expand=True
        )

    def _build_layout(self):
        # View: Welcome
        self.view_welcome = ft.Container(
            content=ft.Column([
                ft.Text("👋", size=60), ft.Text("Welcome to TunesBack", size=24, weight="bold"),
                ft.Text("Select a folder containing your library snapshots to begin.", size=14, color=Theme.SUBTEXT),
            ], horizontal_alignment="center", alignment="center", spacing=10),
            alignment=ft.alignment.center, expand=True, visible=True, padding=ft.padding.only(bottom=60)
        )

        # View: Loading
        self.view_loading = ft.Container(
            content=ft.Column([
                ft.ProgressRing(width=50, height=50, stroke_width=4),
                ft.Text("Crunching numbers...", size=16, weight="bold", color=Theme.SUBTEXT)
            ], horizontal_alignment="center", alignment="center", spacing=20),
            alignment=ft.alignment.center, expand=True, visible=False, padding=ft.padding.only(bottom=60)
        )

        # View: Dashboard
        kpi_cards = ft.Row([
            create_kpi_card(
                ft.Column([ft.Text("Top Artist", size=10, color=Theme.SUBTEXT), self.card_vals[0], self.card_subs[0]],
                          horizontal_alignment="center", alignment="center", spacing=2)),
            create_kpi_card(
                ft.Column([ft.Text("Top Album", size=10, color=Theme.SUBTEXT), self.card_vals[1], self.card_subs[1]],
                          horizontal_alignment="center", alignment="center", spacing=2)),
            create_kpi_card(
                ft.Column([ft.Text("Top Song", size=10, color=Theme.SUBTEXT), self.card_vals[2], self.card_subs[2]],
                          horizontal_alignment="center", alignment="center", spacing=2)),
        ], spacing=15, expand=True)

        header_row = ft.Row([
            ft.Container(content=ft.Column([
                ft.Column([self.kpi_growth, self.kpi_growth_u], spacing=0),
                ft.Column([self.kpi_plays, self.kpi_plays_u], spacing=0)
            ], alignment="spaceBetween", spacing=0), height=Theme.KPI_HEIGHT, alignment=ft.alignment.center_left),
            ft.Container(width=40),
            kpi_cards
        ], alignment="start", vertical_alignment="center")

        results_box = ft.Container(content=self.list_results, bgcolor=ft.Colors.with_opacity(0.05, "black"),
                                   border_radius=10, border=ft.border.all(1, "outlineVariant"), expand=True)

        self.view_dash = ft.Column([
            ft.Container(padding=ft.padding.only(left=Theme.PAD_LEFT, right=Theme.PAD_RIGHT), content=ft.Column([
                ft.Container(height=10), header_row, ft.Container(height=20), self.tabs_main, ft.Container(height=10)
            ])),
            ft.Container(padding=ft.padding.only(left=Theme.PAD_LEFT, right=20, bottom=20), content=results_box,
                         expand=True)
        ], expand=True, visible=False, spacing=0)

        # Sidebar Area
        sidebar_inner = ft.Container(padding=20, content=ft.Column([
            ft.Row([ft.Text("SETTINGS", size=12, weight="bold", color=Theme.SUBTEXT), self.btn_theme],
                   alignment="spaceBetween"),
            ft.Divider(), ft.Text("Source", size=12, weight="bold"), self.btn_select, self.txt_path,
            self.txt_file_count,
            ft.Divider(), ft.Text("Period", size=12, weight="bold"),
            ft.Column([self.dd_start,
                       ft.Row([self.dd_end, self.cb_compare], alignment="spaceBetween", vertical_alignment="center")],
                      spacing=20),
            ft.Divider(), ft.Text("Number of Items To Show", size=12, weight="bold"),
            ft.Column([create_slider_row("Artists", self.sl_art), create_slider_row("Albums", self.sl_alb),
                       create_slider_row("Songs", self.sl_song)], spacing=2),
            ft.Divider(), ft.Text("Units & Ranking", size=12, weight="bold"),
            ft.Column([ft.Text("Time Unit", size=11, color=Theme.SUBTEXT), self.seg_unit,
                       ft.Text("Rank By", size=11, color=Theme.SUBTEXT), self.seg_sort], spacing=5),
            ft.Container(height=20), ft.Row([self.btn_run, self.btn_reset], spacing=10)
        ], spacing=10))

        sidebar = ft.Container(width=300, bgcolor=Theme.SIDEBAR_BG, padding=0,
                               content=ft.Column([sidebar_inner], scroll="auto"))

        # Window Header
        window_header = ft.WindowDragArea(content=ft.Container(
            content=ft.Row([self.txt_app_title, ft.Row([
                ft.IconButton(icon="remove", icon_size=14, on_click=self.minimize_app),
                ft.IconButton(icon="close", icon_size=14, on_click=self.close_app)
            ], spacing=0)], alignment="spaceBetween"),
            padding=ft.padding.only(left=Theme.PAD_LEFT, right=20, top=20, bottom=10), bgcolor=Theme.CONTENT_BG
        ))

        content_area = ft.Container(expand=True, bgcolor=Theme.CONTENT_BG, padding=0, content=ft.Column([ft.Stack([
            self.view_welcome, self.view_dash, self.view_loading
        ], expand=True)]))

        self.main_layout = ft.Container(
            content=ft.Stack([
                ft.Row(
                    [sidebar, ft.Container(content=ft.Column([window_header, content_area], spacing=0), expand=True)],
                    expand=True, spacing=0, vertical_alignment="stretch"),
                self.modal_container
            ]),
            expand=True
        )

    # --- HANDLERS ---

    def minimize_app(self, e):
        self.page.window.minimized = True
        self.page.update()

    def close_app(self, e):
        self.page.window.close()

    def toggle_modal(self, show, title="", msg=""):
        self.modal_container.visible = show
        if show:
            self.modal_title.value = title
            self.modal_text.value = msg
        self.page.update()

    def open_file_picker(self, e):
        self.file_picker.get_directory_path()

    def on_folder_picked(self, e: ft.FilePickerResultEvent):
        if not e.path: return
        self.txt_path.value = e.path
        self.txt_path.color = Theme.SUBTEXT
        self.txt_path.visible = True
        self.txt_file_count.visible = True

        self.files = get_files_in_folder(e.path)

        if self.files:
            self.full_labels = [f['label'] for f in self.files]
            opts = [ft.dropdown.Option(lbl) for lbl in self.full_labels]
            self.dd_start.options = opts
            self.dd_end.options = [ft.dropdown.Option(lbl) for lbl in self.full_labels]
            self.dd_start.value = opts[0].key
            self.dd_end.value = opts[-1].key
            self.txt_file_count.value = f"Found {len(self.files)} snapshot(s)"

            for c in [self.dd_start, self.btn_run, self.sl_art, self.sl_alb, self.sl_song, self.seg_unit, self.seg_sort,
                      self.cb_compare]: c.disabled = False
            self.dd_end.disabled = False
            self.on_start_changed(None)
        else:
            self.txt_path.value, self.txt_path.color = "No dated XML files found.", "error"
            self.txt_file_count.value = ""
        self.page.update()

    def on_compare_changed(self, e):
        self.dd_end.disabled = not self.cb_compare.value
        if not self.cb_compare.value:
            self.dd_end.value = None
        self.page.update()

    def on_start_changed(self, e):
        if not self.full_labels: return
        new_end_opts = [ft.dropdown.Option(lbl) for lbl in self.full_labels if lbl != self.dd_start.value]
        self.dd_end.options = new_end_opts
        if self.dd_end.value == self.dd_start.value: self.dd_end.value = None
        self.dd_end.update()

    def run_analysis(self, e):
        if not self.dd_start.value: return
        if self.cb_compare.value and not self.dd_end.value: return

        try:
            start_file = next(f for f in self.files if f['label'] == self.dd_start.value)

            if self.cb_compare.value:
                end_file = next(f for f in self.files if f['label'] == self.dd_end.value)
                if start_file['date'] > end_file['date']:
                    self.toggle_modal(True, "Invalid Range", "Start Date cannot be after End Date.")
                    return

            self._set_loading_state(True)

            res_start = parse_xml_library(start_file['path'])
            if res_start[3]: raise Exception(f"Read error: {res_start[3]}")

            unit = list(self.seg_unit.selected)[0]

            if self.cb_compare.value:
                res_end = parse_xml_library(end_file['path'])
                val_main, val_plays, df_art, df_alb, df_song = calculate_stats(res_start, res_end, unit)
                self.kpi_growth_u.value, self.kpi_plays_u.value = f"{unit} Growth", "New Plays"
            else:
                val_main, val_plays, df_art, df_alb, df_song = calculate_single_stats(res_start, unit)
                self.kpi_growth_u.value, self.kpi_plays_u.value = f"Total {unit}", "Total Plays"

            self.data_frames = {"art": df_art, "alb": df_alb, "song": df_song}
            self.kpi_growth.value = f"{val_main:,.1f}"
            self.kpi_plays.value = f"{int(val_plays):,}"

            self._update_top_cards(unit)
            self.update_results_ui(None)
            self._set_loading_state(False)

        except Exception as ex:
            self.toggle_modal(True, "Error", str(ex))
            print(traceback.format_exc())
            self._set_loading_state(False)

    def _set_loading_state(self, is_loading):
        self.view_loading.visible = is_loading
        self.view_welcome.visible = False
        self.view_dash.visible = not is_loading and not self.view_welcome.visible
        if not is_loading and not self.kpi_growth.value: self.view_welcome.visible = True

        self.btn_run.disabled = is_loading
        self.btn_reset.disabled = is_loading
        self.txt_app_title.opacity = 0 if is_loading else 1
        self.page.update()

    def _update_top_cards(self, unit):
        dfs = [self.data_frames["art"], self.data_frames["alb"], self.data_frames["song"]]
        keys = ["Artist", "Album", "Song"]

        for i, df in enumerate(dfs):
            top = df.sort_values('Value', ascending=False).iloc[0] if not df.empty else None
            self.card_vals[i].value = top[keys[i]] if top is not None else "-"
            self.card_subs[
                i].value = f"{top['Value']:.1f} {unit} • {int(top['Count'])} plays" if top is not None else "-"

    def update_results_ui(self, e):
        idx = self.tabs_main.selected_index
        unit = list(self.seg_unit.selected)[0]
        sort_mode = list(self.seg_sort.selected)[0]

        configs = [
            (self.data_frames["art"], int(self.sl_art.value), "cyan", "Artist", None),
            (self.data_frames["alb"], int(self.sl_alb.value), "purple", "Album", "Artist"),
            (self.data_frames["song"], int(self.sl_song.value), "pink", "Song", "Artist")
        ]

        df, limit, color, main_col, sub_col = configs[idx]
        self.list_results.controls.clear()

        if df.empty:
            self.list_results.controls.append(ft.Text("No data to display.", italic=True))
        else:
            sort_col = 'Value' if sort_mode == 'time' else 'Count'
            df_sorted = df.sort_values(sort_col, ascending=False).head(limit)
            for i, row in enumerate(df_sorted.itertuples(), 1):
                lbl = getattr(row, main_col)
                sub = getattr(row, sub_col) if sub_col else ""
                self.list_results.controls.append(
                    draw_list_item(i, lbl, sub, getattr(row, "Value"), getattr(row, "Count"), unit, color)
                )
        self.list_results.update()

    def reset_view(self, e):
        self.view_welcome.visible = True
        self.view_dash.visible = False
        self.btn_reset.disabled = True
        self.txt_app_title.opacity = 0
        self.page.update()

    def toggle_theme(self, e):
        self.page.theme_mode = 'light' if self.page.theme_mode == 'dark' else 'dark'
        self.btn_theme.icon = 'dark_mode' if self.page.theme_mode == 'light' else 'light_mode'
        self.page.update()


# =============================================================================
# 5. ENTRY POINT
# =============================================================================

def main(page: ft.Page):
    # Page Settings
    page.title = "TunesBack"
    page.theme_mode = "system"
    page.padding = 0
    page.window.min_width = 900
    page.window.min_height = 600

    # Frame Configuration
    page.window.frameless = False
    page.window.title_bar_hidden = True
    page.window.title_bar_buttons_hidden = True
    page.window.bgcolor = ft.Colors.TRANSPARENT
    page.bgcolor = ft.Colors.TRANSPARENT
    page.window.shadow = True

    # Run App
    app = TunesBackApp(page)
    page.add(app.main_layout)


if __name__ == "__main__":
    ft.app(target=main)