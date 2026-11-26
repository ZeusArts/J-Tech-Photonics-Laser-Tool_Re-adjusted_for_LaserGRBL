# J-Tech Photonics Laser Tool — マルチレイヤー化・機能拡張 改良計画書（改訂版）

**対象環境**: Inkscape 1.4.2 (`inkex` 1.x / Python 3.x) / LaserGRBL (GRBL 1.1+) / Windows  
**ライセンス**: MIT License  
**改訂日**: 2026-11-26  

本計画書は、全ソースコードの詳細調査結果（完全技術仕様書）を踏まえて、設計上の落とし穴（Z軸リセット、楕円弧の変換バグ、GUIと `.inx` の関係、コンパイラ状態引き継ぎ等）を解消しつつ、段階的にマルチレイヤー化を遂行するための改訂版設計書です。

---

## 1. 調査レポートから判明した重要な設計前提・制約

1. **既修正ロジックの維持 (`laser.py`)**:
   - `self.svg.unittouu(f"1{unit}")` による単位変換（`unit_per_uu` / `uu_per_unit`）と `Transformation` の**右掛け合成規則**（適用順＝呼び出し順の逆）をすべての新規レイヤー処理・デバッグ描画で維持すること。
2. **コンパイラの Z 軸設定 (`_compiler.py` L.69-78)**:
   - 現行 `Compiler.compile()` は `pass_depth > 0` かつ `passes > 1` の場合のみ各パス間で `G91` → `G1 Z-{pass_depth}` → `G90` を出力する（`pass_depth == 0` なら Z 指令は一切出力されない）。
   - 2軸（X/Y）ダイオードレーザー機では Z 軸を使用しないため、`pass_depth` はデフォルト `0`（Z 指令なし）として扱い、将来 Z 軸を追加する場合にのみ利用するオプションに留める。
3. **コンパイラの位置追跡とコマンド抑制 (`_compiler.py` L.113, `_gcode.py` L.28-35)**:
   - `Compiler` は `self.interface.position` で現在位置を追跡し、開始点が同一ならレーザー設定や移動をスキップする。また `Gcode` は `_current_speed` で `F` 値出力を抑制する。
   - マルチレイヤー連結時は、レイヤーごとに加工速度 `F` やレーザーコマンド（`M3`/`M4`, `S`値）が変わるため、**レイヤー境界で必ずレーザー OFF (`M5`)・速度再設定・新レーザー出力コマンドの発行**を強制する設計が必要。
4. **楕円弧の変換バグ回避 (`_path.py` L.256, `_elliptical_arc.py`)**:
   - `EllipticalArc` は非等方スケールや回転等の `Transformation` が正しく適用されない既知の TODO を持つ。
   - 新規で `<circle>` / `<ellipse>` / 角丸 `<rect>` をサポートする際は、`EllipticalArc` ではなく **3次ベジェ曲線（`C` コマンド相当の 4 分割近似）で `d` 文字列に変換し `Path` へ渡す** ことで、既存の `CubicBazier`（`Transformation` 完全対応）を安全に利用できる。
5. **`laser.inx` の `<object-type>` 制約**:
   - 現行は `<object-type>path</object-type>` になっているが、基本図形（`<rect>` 等）や未変換 `<text>` 警告に対応するため `<object-type>all</object-type>` への変更を検討する。
6. **空の `"content layer"` (`id="layer89324"`) 対策**:
   - `select_non_debug_layer()` が恒久レイヤー `layer89324` を作成するため、要素が空のレイヤーは GUI 上で分かりやすく区別（例：`(空)` 表示・初期状態 OFF）する。

---

## 2. 決定事項と全体仕様

| 項目 | 決定仕様 |
|---|---|
| **UI 方式** | **専用 GUI ウィンドウ（Tkinter）** を起動し、SVG 内のレイヤー一覧を動的に読み込んで操作する |
| **G-code 出力形式** | **1 つの `.gcode` に順番に連結するモード** と **レイヤーごとに別ファイル出力するモード** を切り替え可能にする |
| **加工順番の基準** | Inkscape の **レイヤーパネルの並び順（上から順 / 下から順を切り替え可能）** ＋ GUI 上での個別並べ替え |
| **パーサー拡張** | 基本図形（`<rect>`, `<circle>`, `<ellipse>`, `<line>`, `<polyline>`, `<polygon>`）を自動変換対応し、`<text>` 未変換時は警告を表示する |

---

## 3. 目標アーキテクチャ

```text
Inkscape SVG
   │
   ▼
laser.py (GcodeExtension.effect)
   │  1. clear_debug() で debug_traces / debug_references 除去
   │  2. uu_per_unit = self.svg.unittouu(f"1{unit}"), unit_per_uu = 1.0 / uu_per_unit
   │  3. 共通変換 root_transformation（offset, scaling_factor, machine_origin, unit_per_uu）構築
   │  4. parse_layers(root, ...) でレイヤー単位に抽出
   ▼
[List[LayerData]]  （layer_id, label, visible, curves, unconverted_text_count）
   │
   ▼
gui/layer_dialog.py (Tkinter 専用 GUI)
   │  - SVG 内カスタム属性または JSON から前回設定を復元
   │  - レイヤー一覧編集（有効/無効、順番↑↓、プリセット、M3/M4、S値、F値、Passes、Pass Depth）
   │  - 出力モード切替（単一ファイル連結 / レイヤー別分割）
   │  - 加工順基準切替（レイヤーパネルの上から順 / 下から順）
   │  - 未変換 <text> があるレイヤーへの警告表示
   ▼
[List[LayerJob]]  （確定した加工ジョブ列）
   │
   ▼
svg_to_gcode/compiler/ (MultiLayerCompiler または Compiler 拡張)
   │  - ジョブごとに custom_interface(M3/M4, S値) と速度・パス数を適用
   │  - 連結時はレイヤー間で M5 + Z復帰 + 速度/出力再設定を実施
   │  - 分割時は {base}_{index:02d}_{safe_label}.gcode で個別出力
   ▼
出力 .gcode ファイル & レイヤー別色分けデバッグトレース描画
```

---

## 4. フェーズ別詳細設計

### Phase 1: Tkinter 環境確認（前提検証）
- Inkscape 1.4.2（Windows）同梱 Python 環境で `import tkinter` が正常に動作し、`EffectExtension.effect()` 内からモーダルウィンドウを開閉して Inkscape に制御が戻ることを確認する。
- 万一 Tkinter が利用不可の環境だった場合のフォールバック（`laser.inx` の従来モード維持）を確認する。

### Phase 2: パーサーのレイヤー抽出・基本図形変換・`<text>` 検出

#### 2.1 `svg_to_gcode/svg_parser/_shapes.py`（新設）
以下の要素を SVG パス `d` 文字列へ変換する関数群を実装し、既存の `Path(d, canvas_height, transform_origin, transformation)` に渡す（これにより `Transformation` と Y 反転が既存パスと完全に同一経路で処理される）：
- `<rect>`: `x`, `y`, `width`, `height`, `rx`, `ry`（角丸時は 4隅を3次ベジェ曲線で生成、`rx`/`ry` の SVG 仕様クランプ処理含む）
- `<circle>`: `cx`, `cy`, `r`（$\kappa = \frac{4(\sqrt{2}-1)}{3} \approx 0.5522847498$ を用いた 4 分割 3 次ベジェ閉曲線）
- `<ellipse>`: `cx`, `cy`, `rx`, `ry`（同上の 4 分割 3 次ベジェ閉曲線）
- `<line>`: `x1`, `y1`, `x2`, `y2` → `M x1,y1 L x2,y2`
- `<polyline>` / `<polygon>`: `points` 属性の数値ペア解析 → `M ... L ...`（`polygon` は末尾に `Z`）

#### 2.2 `svg_to_gcode/svg_parser/_parser_methods.py`（拡張）
- 既存 `parse_root()` は後方互換のため維持しつつ、`LayerData` データクラスと `parse_layers()` を追加する。
- **レイヤー識別**: `element.tag == "{http://www.w3.org/2000/svg}g"` かつ `element.get("{http://www.inkscape.org/namespaces/inkscape}groupmode") == "layer"`。
- **除外対象**: `id` が `"debug_traces"` または `"debug_references"`。
- **ルート直下の非レイヤー要素**: いずれのレイヤーにも属さない図形が存在する場合、仮想レイヤー（例：`id="__root__"`, `label="(Root)"`）にまとめる。
- **加工順番と DOM 順の対応**:
  - SVG DOM の先頭＝レイヤーパネルの**最背面（一番下）**、末尾＝**最前面（一番上）**。
  - したがって「**上から順**」＝ `list(reversed(layers))`、「**下から順**」＝ `layers` そのまま。
- **未変換 `<text>` 検出**:
  - `<svg:text>` を検出したら、親レイヤー（または仮想レイヤー）の `unconverted_text_count` を加算する（`display="none"` の非表示テキストは除外）。

### Phase 3: マルチジョブ対応コンパイラ (`svg_to_gcode/compiler/`)

1. **`LayerJob` モデル**:
   - `layer_id: str`, `label: str`, `enabled: bool`
   - `laser_mode: str`（`"M3"` / `"M4"`）
   - `laser_power: int`（例：0〜1000 または 0〜255）
   - `laser_off_command: str`（デフォルト `"M5;"`）
   - `travel_speed: float`, `cutting_speed: float`
   - `passes: int`, `pass_depth: float`, `dwell_time: float`
   - `curves: List[Curve]`
2. **カスタムインターフェースの改善 (`laser.py` / `interfaces`)**:
   - レイヤーごとに `laser_power_command = f"{job.laser_mode} S{job.laser_power};"` を生成（`\n` エスケープ展開 `.replace(r'\n', '\n')` もサポート）。
3. **連結モード (`compile_combined`)**:
   - 共通ヘッダ出力 → 各有効 `LayerJob` を順に処理：
     - ジョブ区切りコメント（`; Layer: ...` ※ASCII 安全化または UTF-8）を挿入。
     - ジョブ開始時に `M5;` を出力し、内部速度状態（`_current_speed`）および開始点チェックをリセットして新ジョブの速度・出力コマンドを確実に出力させる。
     - `pass_depth` はデフォルト `0`（Z 軸コマンド出力なし）とし、`pass_depth > 0` が指定された場合のみ従来通りの Z 降下を適用する（将来 Z 軸機を使う場合は必要に応じて Z 復帰オプションを検討）。
   - 全ジョブ完了後に共通フッタ出力。
4. **分割モード (`compile_separate`)**:
   - `{base_name}_{index:02d}_{sanitized_label}.gcode` を各有効レイヤーごとに生成（Windows 禁止文字 `\ / : * ? " < > |` を `_` に置換）。
   - 各ファイルに独立したヘッダ・フッタを付与。

### Phase 4: Tkinter 専用 GUI (`gui/layer_dialog.py`)

1. **上部グローバル設定エリア**:
   - 出力フォルダ・ベースファイル名・連番付加チェック
   - 出力形式ラジオ：`[1つのファイルに連結]` / `[レイヤーごとに分割出力]`
   - レイヤー順デフォルト切替：`[レイヤーパネルの上から順]` / `[下から順]`（押下時に一覧を即座に並び替え）
2. **中央レイヤー一覧テーブル**:
   - 列：`有効` / `順(↑↓)` / `レイヤー名（図形数・⚠未変換テキスト警告）` / `プリセット(彫刻/カット/カスタム)` / `モード(M3/M4)` / `出力(S)` / `加工速度(F)` / `回数(Passes)`（`Pass Depth` は 2軸機向けにデフォルト `0` で折りたたみ／詳細設定扱いも可）
   - 非表示レイヤー（`visible=False`）および空レイヤー（`curves==0`）はデフォルトで `有効=False` に設定。
3. **設定の永続化**:
   - プリセット／レイヤー設定を SVG ルート要素のカスタム属性（例：`inkscape:laser-config` または `data-laser-jobs` JSON）に保存し、同じ SVG を次回開いた際に前回のレイヤー設定を自動復元できるようにする。
   - あわせて JSON ファイルへのエクスポート／インポート機能も用意する。

### Phase 5: `laser.py` / `laser.inx` 統合 & マルチレイヤーデバッグ描画

1. **`laser.inx`**:
   - `<object-type>all</object-type>` へ変更。
   - 「マルチレイヤー GUI を使用する（`use_layer_gui` = `true`）」オプションを追加し、OFF にすれば従来の単一設定モード（無人バッチ実行等）も利用可能にする。
2. **デバッグ描画 (`draw_debug_traces`)**:
   - 有効化された各レイヤーごとに色分け（パレット配列、または彫刻系=青・カット系=赤）してトレースを描画。
   - 各レイヤーの最初のパス開始点付近に加工順番ラベル（`#1`, `#2`...）を描画。
   - 既存の `top-left` 原点時における `draw_debug_traces` の逆変換漏れもあわせて修正する。

---

## 5. 実装ステップと検証計画

1. **Step 1**: Inkscape 1.4.2 環境での Tkinter 最小起動テスト。
2. **Step 2**: `_shapes.py`（基本図形 → パス `d` 変換）および `parse_layers()`（レイヤー抽出 + `<text>` 検出）の実装と単体検証。
3. **Step 3**: マルチレイヤー用コンパイラ（連結時の速度/出力再設定、分割時のファイル名サニタイズ）の実装と単体検証。
4. **Step 4**: `gui/layer_dialog.py` の実装および設定保存/復元機能の実装。
5. **Step 5**: `laser.py` / `laser.inx` 統合、レイヤー別色分けデバッグ描画の実装、マルチレイヤーサンプル SVG（彫刻レイヤー＋カットレイヤー＋基本図形＋未変換テキスト）による Inkscape 1.4.2 + LaserGRBL 総合検証。
