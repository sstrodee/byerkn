# Third-party components

- Flowseal/zapret-discord-youtube 1.10.4 contains the starting profiles, lists, templates and Windows engine binaries. The ZIP asset SHA-256 is `291af673bd0238506f9548e0e94ca0abf244000f4c9a06960544fb01c5f97b34`. [Flowseal 1.10.4](https://github.com/Flowseal/zapret-discord-youtube/tree/1.10.4) · [Bundled license and notices](licenses/zapret-LICENSE.txt)
- The bundled winws reports zapret v72.9, commit `c849e55ef0f1c244206f5a05ff7b1ab41a3824ee`. [Source at that commit](https://github.com/bol-van/zapret/tree/c849e55ef0f1c244206f5a05ff7b1ab41a3824ee) · [Windows bundle project](https://github.com/bol-van/zapret-win-bundle)
- WinDivert 2.2.2 is dual licensed under LGPL 3 or GPL 2. The bundled `WinDivert.dll` and `WinDivert64.sys` exactly match the x64 files in the upstream 2.2.2-A archive. [Release and source archives](https://github.com/basil00/WinDivert/releases/tag/v2.2.2) · [LGPL 3 text](licenses/LGPL-3.0-only.txt)
- The bundled `cygwin1.dll` exactly matches the DLL in the Cygwin x86_64 3.4.10-1 package. Cygwin is licensed under LGPL 3 or later with additional terms. [Exact 3.4.10-1 source package](https://ftp.cvut.cz/mirrors/cygwin.com/x86_64/release/cygwin/cygwin-3.4.10-1-src.tar.xz) · [Cygwin licensing terms](https://cygwin.com/licensing.html)
- CPython 3.13.17. The PSF license and third-party notices are in `runtime/LICENSE.txt`. [Source and Windows package](https://www.python.org/downloads/release/python-31317/)
- PySide6 Essentials and Shiboken6 6.12.0. The [LGPL 3](licenses/LGPL-3.0-only.txt) and [GPL 3](licenses/GPL-3.0-only.txt) texts accompany the notices shipped with the wheels under `runtime/Lib/site-packages/*dist-info/licenses`. [PySide6 and Shiboken6 6.12.0 source](https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.12.0-src/) · [Qt for Python licenses](https://doc.qt.io/qtforpython-6/licenses.html)
- Qt 6.12.0. The Windows bundle uses Qt Core, Gui, Widgets, Svg and a subset of plug-ins and translations. The relevant upstream archives include `qtbase`, `qtsvg`, `qtimageformats` and `qttranslations`. [Qt 6.12.0 sources](https://download.qt.io/archive/qt/6.12/6.12.0/submodules/) · [Qt licenses](https://doc.qt.io/qt-6/licenses-used-in-qt.html)
- Golos Text: https://github.com/googlefonts/golos-text ; SIL Open Font License in assets/fonts/OFL-GolosText.txt.
- Instrument Serif (Regular and Italic): SIL Open Font License in assets/fonts/OFL-InstrumentSerif.txt.

The [MIT license](LICENSE) covers the byerkn source. The archive includes Python application and launcher sources. Third-party components retain their own licenses.

The application loads Qt and PySide6 dynamically from `runtime/Lib/site-packages`. To replace them, exit byerkn and substitute compatible Windows x64 libraries and plug-ins in a copy of the portable folder. You may modify the libraries and reverse engineer the application to debug those changes under the applicable LGPL terms.
