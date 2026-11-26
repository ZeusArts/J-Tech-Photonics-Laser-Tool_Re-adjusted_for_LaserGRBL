# J-Tech Photonics Laser Tool - 変更内容と理由 / Changes & Rationale

[日本語](#日本語) | [English](#english)

---

## 日本語

### 概要
Inkscape 1.4.2 と LaserGRBL 環境において、SVG ドキュメントの `viewBox` スケールと出力単位（`mm` / `in`）の不一致によって発生していた **トンボ枠のサイズズレ** および **G-code の加工サイズ・開始点ズレ** を修正しました。

### 発生していた問題と原因
- **現象**:
  1. ドキュメントサイズを `300mm × 300mm`、ベッドサイズを `300 × 300 (mm)` に設定して実行すると、画面左上に約 `80mm × 80mm`（実際は `79.375mm`）の小さなトンボ枠が描画される。
  2. 出力された G-code の加工サイズや開始点が不自然な位置にズレ、Y 座標がマイナス領域に飛び出す。
- **原因**:
  Inkscape 1.4.2 でページサイズを `300mm × 300mm` に設定しても、ドキュメントの `viewBox` スケールが 96 dpi 基準（`1 user unit = 1 px ≒ 0.2646 mm`、`1 mm ≒ 3.7795 user units`）のままになっている場合、`laser.py` が単位変換を行わずに数値をそのまま扱っていたためです。
  - トンボ描画では `300` が `300 px`（約 `79.4 mm`）として描画されていました。
  - G-code 生成では SVG 内の px 座標が約 `3.78` 倍のまま出力され、さらに `bed_height`（`300`）から Y 反転の引き算が行われることで座標が大きくズレていました。

### 変更内容と理由 (`laser.py`)

`inkex` の `self.svg.unittouu()` を利用し、ドキュメントのユーザー単位（user units）とエクステンション側の設定単位（`mm` / `in`）を相互変換するようにしました。

1. **G-code 座標変換のスケーリング (`GcodeExtension.effect`)**
   - `uu_per_unit = self.svg.unittouu(f"1{self.options.unit}")` とその逆数 `unit_per_uu = 1.0 / uu_per_unit` を算出。
   - `transformation.add_scale(unit_per_uu)` を追加し、SVG パスのユーザー単位座標を正しく設定単位（`mm` / `in`）へ変換してからオフセット・原点変換・Y 軸反転を行うように変更しました。
2. **デバッグトレース描画のスケーリング (`GcodeExtension.draw_debug_traces`)**
   - G-code 座標系から SVG ユーザー単位へ戻す `change_origin.add_scale(uu_per_unit)` を追加。
   - 線幅も `self.svg.unittouu(f"{self.options.debug_line_width}px")` でスケーリングし、`viewBox` の設定に関わらず図形と正確に重なるようにしました。
3. **トンボ描画のスケーリング (`GcodeExtension.draw_unit_reference`)**
   - `bed_width`・`bed_height` に `uu_per_unit` を掛けて四隅の基準点座標を算出し、設定通りのベッドサイズ（例：`300mm × 300mm`）の位置に描画されるようにしました。
   - 十字マークの大きさ・線幅・ラベル文字サイズにも `px_to_uu = self.svg.unittouu("1px")` を適用し、ドキュメントの `viewBox` 単位（`px` 基準 / `mm` 基準）を問わず視認性を保つようにしました。

### 検証結果
- 検証用サンプル `test_samples/test_300x300.svg`（`width="300mm" height="300mm" viewBox="0 0 1133.8583 1133.8583"`、左上に `100mm × 100mm` の正方形パスを配置）を Inkscape 1.4.2 で実行し、以下を確認しました。
  - トンボ枠が `300mm × 300mm` ページの四隅に正しく描画されること。
  - 生成された G-code の正方形座標が `X20.000013 Y279.999987` ～ `X119.999998 Y180.000002`（`100mm × 100mm`）として実寸通り出力されること。

---

## English

### Overview
Fixed an issue in Inkscape 1.4.2 with LaserGRBL where a mismatch between the SVG document's `viewBox` scale and the extension's output unit (`mm` / `in`) caused **incorrect reference frame sizing** and **shifted/scaled G-code coordinates**.

### Issue & Root Cause
- **Symptoms**:
  1. Even with a `300mm × 300mm` document and `300 × 300 (mm)` bed settings, the generated debug reference frame appeared at roughly `80mm × 80mm` (actually `79.375mm`) in the top-left corner.
  2. The generated G-code toolpath had incorrect scale and starting positions, extending into negative Y coordinates.
- **Root Cause**:
  When an Inkscape 1.4.2 document has `width="300mm" height="300mm"` while keeping a 96 dpi pixel-based `viewBox` (`1 user unit = 1 px ≈ 0.2646 mm`, `1 mm ≈ 3.7795 user units`), `laser.py` treated raw user-unit numbers as target units without conversion:
  - `draw_unit_reference()` placed markers at `300 px` (`≈ 79.4 mm`) instead of `300 mm`.
  - G-code compilation used raw pixel values (`≈ 3.78×` too large) and subtracted them from `bed_height` (`300`), causing severe origin and scale mismatches.

### Changes & Rationale (`laser.py`)

Used `inkex`'s `self.svg.unittouu()` to convert accurately between SVG user units and the selected output unit (`mm` or `in`):

1. **G-code Coordinate Scaling (`GcodeExtension.effect`)**
   - Computed `uu_per_unit = self.svg.unittouu(f"1{self.options.unit}")` and `unit_per_uu = 1.0 / uu_per_unit`.
   - Added `transformation.add_scale(unit_per_uu)` so parsed SVG coordinates are converted into target units (`mm` / `in`) before applying offsets, origin shifts, and Y-axis inversion.
2. **Debug Trace Scaling (`GcodeExtension.draw_debug_traces`)**
   - Added `change_origin.add_scale(uu_per_unit)` to map G-code coordinates back into SVG user units.
   - Scaled `stroke_width` via `self.svg.unittouu(f"{self.options.debug_line_width}px")` so debug traces align with the original paths regardless of `viewBox` settings.
3. **Reference Point Scaling (`GcodeExtension.draw_unit_reference`)**
   - Multiplied `bed_width` and `bed_height` by `uu_per_unit` so corner markers are placed at the actual physical bed dimensions (e.g., `300mm × 300mm`).
   - Scaled marker size, stroke width, and label font size using `px_to_uu = self.svg.unittouu("1px")` to keep them visually consistent across both `px`-based and `mm`-based `viewBox` documents.

### Verification
- Verified with `test_samples/test_300x300.svg` (`width="300mm" height="300mm" viewBox="0 0 1133.8583 1133.8583"`, containing a `100mm × 100mm` square at `(20mm, 20mm)`) in Inkscape 1.4.2:
  - Confirmed the debug reference markers align with the four corners of the `300mm × 300mm` page.
  - Confirmed the output G-code coordinates for the square are `X20.000013 Y279.999987` to `X119.999998 Y180.000002` (`100mm × 100mm`).

