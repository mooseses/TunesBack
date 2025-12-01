<div align="center">
  <img src="./assets/icon_256.ico" alt="TunesBack Logo" width="128" height="128">
  
# 🎵 TunesBack

**Your music story, beautifully analyzed.**

*The "Apple Music Replay" experience for iTunes and iPod users.*

  [![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

</div>

## Why TunesBack?

Spotify has Wrapped. Apple Music has Replay. But what about iTunes and iPod users?

**TunesBack fills that gap.** If you own your music library instead of streaming, you've been left out of the year-end analytics revolution. TunesBack brings that experience to your local library—track listening habits, discover top artists and songs, and see how your taste evolves over time.

Works with both iTunes and Apple Music libraries. Cross-platform support for Windows, macOS, and Linux. (WIP)

Powered by [libpytunes](https://github.com/liamks/libpytunes) for robust iTunes XML parsing.

## ✨ Features

- **Compare periods**  (Must be dated. See guide below.) or analyze single snapshots
- **Top Artists, Albums & Songs** with customizable rankings (5-100 items)
- **Flexible display**: Hours/minutes, sort by time/plays
- **Beautiful dashboard** with dark/light mode
- **100% private**: All processing happens locally on your machine

## 🚀 Quick Start

### 1. Install

**Pre-built app** (recommended): Download from [Releases](https://github.com/mooseses/TunesBack/releases)

**From source**:
```bash
git clone https://github.com/mooseses/TunesBack.git
cd TunesBack

pip install -r requirements.txt

python tunesback.py
```

Alternatively, install dependencies manually:
```bash
pip install flet libpytunes pandas python-dateutil
python tunesback.py
```

### 2. Export Your Library

1. Open iTunes/Music → **File** → **Library** → **Export Library**
2. Save as `.xml` with a date in filename (e.g., `2025-12-01.xml`)
3. Export again later to compare!

### 3. Analyze

1. Click **Select Folder** and choose your XML files location
2. Pick date range or single snapshot
3. Click **Generate Recap**

## 📁 File Naming Guide

**How TunesBack Parses Dates**

TunesBack uses **fuzzy date parsing** to automatically extract dates from your XML filenames. The parser looks for date-like patterns anywhere in the filename and standardizes them to `YYYY-MM-DD` format in the app.

**✅ Recommended Formats (Unambiguous):**
- `2025-12-01.xml` or `2025-12-01 iTunes Library.xml`
- `2025_12_01.xml`
- `December 01 2025.xml` or `Dec 01 2025.xml`
- `01 December 2025.xml`
- `2025-December-01.xml`

**⚠️ Date Format Ambiguity Warning**

Be careful with numeric-only dates! The parser may interpret them differently based on your system:

- `01-12-2025.xml` could be:
  - **January 12, 2025** (MM-DD-YYYY format)
  - **December 1, 2025** (DD-MM-YYYY format)

- `12-01-2025.xml` could be:
  - **December 1, 2025** (MM-DD-YYYY format)
  - **January 12, 2025** (DD-MM-YYYY format)

**Best Practice:** Use ISO format `YYYY-MM-DD.xml` or include month names like `December-01-2025.xml` to avoid confusion.

**Examples that work:**
- ✅ `2025-12-01.xml`
- ✅ `iTunes Export December 2025.xml`
- ✅ `Library_2025_12_01_backup.xml`

**Examples that might fail:**
- ❌ `library.xml` (no date)
- ❌ `v2.1.3-export.xml` (version numbers confused with dates)


## 💡 Tips

- 📅 Export monthly for meaningful trends
- 🎧 Sort by "Plays" for guilty pleasures; "Time" for what really stuck
- 📈 Use top 50-100 for comprehensive year-end recaps
- 🔄 Compare consecutive months to see immediate vs. long-term shifts

## ❓ Troubleshooting

**"No dated XML files found"**
- Filenames need recognizable dates (see File Naming Guide above)
- When in doubt, use `YYYY-MM-DD.xml` format—it's universally recognized

**No data showing?**
- Podcasts, movies, and videos are filtered out—only songs count
- Verify your library has play count history

**Slow loading?**
- Large libraries (10,000+ songs) take 5-15 seconds—this is normal

## 🛠️ Built With

- [Flet](https://flet.dev/) - Python UI framework
- [libpytunes](https://github.com/liamks/libpytunes) - iTunes XML parser
- [pandas](https://pandas.pydata.org/) - Data analysis
- [python-dateutil](https://dateutil.readthedocs.io/) - Date parsing

## 📜 License

Distributed under the GPL-3.0 License. See `LICENSE` for details.
