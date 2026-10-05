# Third-party notices

## ai5/OEXEngine

Android OEX packaging in this project was designed with reference to the public `ai5/OEXEngine` project.

- Project: `ai5/OEXEngine`
- Purpose: Shogi engine OEX packaging template for Android
- License: MIT License
- Reference areas: Android manifest structure, OEX engine declaration (`enginelist.xml`), and ContentProvider-based engine exposure

The code in this repository is adapted/reimplemented for the `shogi-ai` project rather than copied as a full template.


## YaneuraOu / Stockfish-derived rules

- Source: https://github.com/yaneurao/YaneuraOu
- Pinned revision: c1b80eaa09fe13d5f12b1599d1ae4d53c224de30
- License: GNU General Public License version 3 (see `third_party/yaneuraou/LICENSE`)
- Used implementation files: position.cpp, movegen.cpp, bitboard.cpp, types.cpp and required headers
- Modifications: conditional rules-only build guards in `rules-only.patch`; move text formatting adapted from usi.cpp in `engine/rules/upstream_support.cpp`
- Original file contents are fetched at the pinned revision and verified against `manifest.json`; copyright and license notices in upstream sources are preserved.
- The resulting native engine incorporates GPL-covered code. Corresponding buildable source consists of this repository, the pinned upstream source and the recorded patch/build instructions. Preserve these when distributing the binary; this notice does not remove upstream license terms.

### Test-only dependency

Independent differential tests use `python-shogi==1.1.1` (https://github.com/gunyarakun/python-shogi, GPL-3.0). It is not packaged in the Android app.
