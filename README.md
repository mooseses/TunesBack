<div align="center">
<img src="assets/icon_256.ico" width="120" />
<h1>TunesBack</h1>
<p>
<p> <a href="https://github.com/mooesy/TunesBack/actions"> <img src="https://www.google.com/search?q=https://img.shields.io/github/actions/workflow/status/{username}/{repo}/main.yml?style=flat-square" alt="Build Status" /> </a> </p>
</a>
</p>
</div>

**TunesBack** is a modern, cross-platform desktop application that visualizes your iTunes Library & Apple Music Library history. It analyzes your library XML "snapshots" to show you your top artists, albums, and songs, and calculates your listening growth over specific time periods.

<p>TunesBack is powered by <a href="https://github.com/liamks/libpytunes">libpytunes</a> for robust parsing of iTunes XML library files.</p>

![Screenshot](assets/screenshot.png)

## ✨ Features

* **📂 Snapshot Analysis:** Automatically parses dates from your iTunes Library XML filenames (e.g., `2023-12-01.xml`, `01.12.23.xml`).
* **📊 Single Snapshot Analysis:** View your total play time and top rankings for a single XML snapshot.
* **📈 Compare Mode:** Calculate the **growth** between two snapshots. See exactly how many hours you listened and which artists grew the most during that period.
* **🎨 Modern UI:** A frameless, clean interface built with **Flet** (Flutter for Python), featuring dark/light mode toggles and smooth animations.
* **🔒 Privacy First:** All processing happens locally on your machine. No data is ever uploaded.

## 🚀 How to Use

1.  **Select Folder:** Click the "Select Folder" button and choose the directory where you keep your iTunes `.xml` backups.
2.  **Select Mode:**
      * **Single Library:** Select a "Start Date" to see stats for that specific day.
      * **Compare:** Check the "Compare" box and select an "End Date" to see the difference between the two dates.
3.  **Customize:** Adjust the sliders to show Top 10, 20, or 50 items. Toggle between "Hours" or "Minutes".
4.  **Generate:** Click **Generate Recap** to view your statistics.

## 📦 Building Executables

To build a standalone executable (`.exe` for Windows, `.app` for macOS, or binary for Linux) that requires no Python installation to run:

1.  Ensure you have the dependencies installed.
2.  Run the packaging command:

**Windows:**

```bash
flet pack main.py --name TunesBack --icon assets/icon.ico
```

**macOS:**

```bash
flet pack main.py --name TunesBack --icon assets/icon.icns
```

The executable will appear in the `dist/` folder.

## 📝 License

Distributed under the GPL-3.0 license. See `LICENSE` for more information.