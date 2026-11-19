# Third-party components

- Flowseal/zapret-discord-youtube 1.10.4: https://github.com/Flowseal/zapret-discord-youtube/tree/1.10.4 ; MIT, see licenses/zapret-LICENSE.txt. ZIP asset SHA-256: 291af673bd0238506f9548e0e94ca0abf244000f4c9a06960544fb01c5f97b34. Contains winws and packet templates, lists and strategies.
- Original zapret source: https://github.com/bol-van/zapret ; bundled winws sources: https://github.com/bol-van/zapret-win-bundle . Exact upstream package kept in downloads/zapret.zip in the development tree.
- WinDivert: https://github.com/basil00/WinDivert ; LGPL-3.0, with alternative GPL-2.0. License and source are available in the official repository. DLL and driver are unmodified from the verified Flowseal archive.
- Cygwin: https://cygwin.com/licensing.html ; LGPL-3.0-or-later and associated exceptions. Source distribution: https://cygwin.com/packages/summary/cygwin-src.html . Binary is unmodified from the upstream zapret distribution.
- CPython 3.13.17. The PSF license and third-party notices are in `runtime/LICENSE.txt`. [Source and Windows package](https://www.python.org/downloads/release/python-31317/)
- PySide6 Essentials and Shiboken6 6.12.0. The [LGPL 3](licenses/LGPL-3.0-only.txt) and [GPL 3](licenses/GPL-3.0-only.txt) texts accompany the notices shipped with the wheels under `runtime/Lib/site-packages/*dist-info/licenses`. [PySide6 and Shiboken6 6.12.0 source](https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.12.0-src/) · [Qt for Python licenses](https://doc.qt.io/qtforpython-6/licenses.html)
- Qt 6.12.0. The Windows bundle uses Qt Core, Gui, Widgets, Svg and a subset of plug-ins and translations. The relevant upstream archives include `qtbase`, `qtsvg`, `qtimageformats` and `qttranslations`. [Qt 6.12.0 sources](https://download.qt.io/archive/qt/6.12/6.12.0/submodules/) · [Qt licenses](https://doc.qt.io/qt-6/licenses-used-in-qt.html)
- Golos Text: https://github.com/googlefonts/golos-text ; SIL Open Font License in assets/fonts/OFL-GolosText.txt.
- Instrument Serif (Regular and Italic): SIL Open Font License in assets/fonts/OFL-InstrumentSerif.txt.

The [MIT license](LICENSE) covers the byerkn source. The archive includes Python application and launcher sources. Third-party components retain their own licenses.

The application loads Qt and PySide6 dynamically from `runtime/Lib/site-packages`. To replace them, exit byerkn and substitute compatible Windows x64 libraries and plug-ins in a copy of the portable folder. You may modify the libraries and reverse engineer the application to debug those changes under the applicable LGPL terms.

Distribution review remains open for the exact corresponding source of binary components obtained via the Flowseal package, including Cygwin 3.4.10 and WinDivert. The project links above identify upstream sources. Keep the notices alongside any redistributed binaries.
