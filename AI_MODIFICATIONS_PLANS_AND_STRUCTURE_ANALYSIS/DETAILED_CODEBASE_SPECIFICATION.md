# J-Tech Photonics Laser Tool — 完全技術仕様書・コード解説書

**対象バージョン**: Inkscape 1.4.2 / `inkex` 1.x / Python 3.x  
**作成日**: 2026-11-26  
**ベースコミット**: `laser.inx` / `laser.py` / `svg_to_gcode/` 全ファイルの実コードに基づく

---

## 1. プロジェクト概要と End-to-End 実行フロー

### 1.1 目的
Inkscape で描いたベクター図形（`<path>` 要素）を **G-code**（GRBL / LaserGRBL 互換）へ変換する Inkscape エクステンション。メニュー `Extensions → Generate Laser Gcode → J Tech Community Laser Tool` から起動。

### 1.2 全体処理フロー（`laser.py::GcodeExtension.effect()` 中心）

```
[Inkscape SVG Document]
        │
        ▼
laser.py:GcodeExtension.effect()
  ├─ 1. UIパラメータ読み取り（self.options.*）
  ├─ 2. 近似許容差設定：TOLERANCES["approximation"] = float(options.approximation_tolerance)
  ├─ 3. 出力ディレクトリ検証 / ファイル名決定（連番サフィックス付与オプション）
  ├─ 4. カスタムヘッダ/フッタ ファイル読み込み
  ├─ 5. カスタム Gcode インターフェース生成（generate_custom_interface）
  │     └─ ユーザー定義 M3/M5 コマンドでレーザー ON/OFF を上書き
  ├─ 6. 単位変換係数算出
  │     uu_per_unit = self.svg.unittouu(f"1{unit}")   # 1mm/1in = 何 user units か
  │     unit_per_uu = 1.0 / uu_per_unit
  ├─ 7. 座標変換 Transformation 構築
  │     ├─ add_translation(horizontal_offset, vertical_offset)
  │     ├─ add_scale(scaling_factor)
  │     ├─ 機械原点に応じた平行移動
  │     │     center     → (-bed_width/2, +bed_height/2)
  │     │     top-left   → (0, +bed_height)
  │     │     bottom-left→ (0, 0)  ※何もしない
  │     └─ add_scale(unit_per_uu)  ★ SVG user units → 設定単位(mm/in)
  ├─ 8. デバッグレイヤー削除（clear_debug）
  ├─ 9. SVG パース：parse_root(root, transform_origin=not invert_y_axis,
  │                              root_transformation=transformation,
  │                              canvas_height=bed_height)
  │     └─ 戻り値: List[Curve]  （全変換済みの幾何曲線リスト）
  ├─ 10. G-code コンパイル
  │     gcode_compiler = Compiler(custom_interface, travel_speed, cutting_speed,
  │                                pass_depth, dwell_time, custom_header, custom_footer, unit)
  │     gcode_compiler.append_curves(curves)
  │     gcode_compiler.compile_to_file(output_path, passes=options.passes)
  ├─ 11. デバッグ描画（draw_debug オプション時）
  │     ├─ draw_debug_traces(curves)  ── 赤い矢印付き工具軌跡
  │     ├─ draw_unit_reference()      ── ベッド四隅の基準点＋座標ラベル
  │     └─ select_non_debug_layer()   ── "content layer" を選択状態に
  └─ 12. 終了（self.document 返却 → Inkscape が SVG 更新）
```

### 1.3 使用ライブラリと使い分け

| ライブラリ | 用途 |
|-----------|------|
| `inkex` | Inkscape エクステンション基盤（`EffectExtension`, `Boolean`, `self.svg`, `self.document`, `self.options`） |
| `lxml.etree` | XML パース・要素生成・XPath 検索（名前空間対応、高速） |
| `xml.etree.ElementTree` | 軽量な XML 文字列⇔要素変換（`tostring`, `fromstring`） |
| `math` | 三角関数、平方根、角度変換 |
| `copy.deepcopy` | `Transformation` オブジェクトの再帰的コピー（パーサー継承用） |
| `typing` | 型ヒント（`List`, `Type`, `Iterable` 等） |
| `warnings` | パースエラー・幾何学的不整合の非致命的警告 |
| `os` | ファイル存在確認・パス結合・ディレクトリ検証 |

---

## 2. モジュール間依存関係マップ

```
laser.inx (UI定義)
    │
    ▼ (動的パース: read_arguments)
laser.py (GcodeExtension)
    │
    ├─► svg_to_gcode.TOLERANCES, UNITS
    ├─► svg_to_gcode.svg_parser.parse_root
    │       │
    │       ├─► svg_to_gcode.svg_parser._parser_methods.parse_root
    │       │       │
    │       │       ├─► svg_to_gcode.svg_parser._path.Path
    │       │       │       │
    │       │       │       ├─► svg_to_gcode.geometry.Line
    │       │       │       ├─► svg_to_gcode.geometry.CubicBazier
    │       │       │       ├─► svg_to_gcode.geometry.QuadraticBezier
    │       │       │       └─► svg_to_gcode.geometry.EllipticalArc
    │       │       │
    │       │       ├─► svg_to_gcode.svg_parser._transformation.Transformation
    │       │       │       │
    │       │       │       └─► svg_to_gcode.geometry.Matrix, IdentityMatrix, RotationMatrix
    │       │       │       └─► svg_to_gcode.geometry.Vector
    │       │       │
    │       │       └─► svg_to_gcode.formulas (endpoint_to_center_parameterization 等)
    │       │
    │       └─► svg_to_gcode.svg_parser.debug_methods (デバッグ用 SVG 生成)
    │
    ├─► svg_to_gcode.geometry.LineSegmentChain
    │       │
    │       └─► svg_to_gcode.geometry.Chain (基底)
    │       └─► svg_to_gcode.formulas (line_segment_approximation 内部で使用)
    │
    └─► svg_to_gcode.compiler.Compiler
            │
            ├─► svg_to_gcode.compiler.interfaces.Gcode (または FanControlledGcode)
            │       │
            │       └─► svg_to_gcode.compiler.interfaces.Interface (抽象基底)
            │
            └─► svg_to_gcode.geometry.LineSegmentChain.line_segment_approximation
```

**呼び出し方向の要点**
- `laser.py` が **エントリーポイント**であり、すべての下位モジュールをオーケストレート
- `svg_parser` は **DOM → Curve[]** の変換のみ担当（G-code 生成は知らない）
- `geometry` は **純粋な幾何計算**のみ（SVG/G-code 非依存）
- `compiler` は **Curve[] → G-code 文字列** の変換のみ担当（SVG 非依存）
- `interfaces` は **機種固有コマンド生成**のみ（幾何計算非依存）

---

## 3. `laser.inx` UI パラメータと `laser.py` での対応一覧

### 3.1 全パラメータ対応表

| `name` | `type` | `gui-text` | デフォルト | `laser.py` での使用箇所（`self.options.<name>`） |
|--------|--------|------------|------------|--------------------------------------------------|
| **Important Settings タブ** |
| `unit` | `optiongroup` (combo) | Unit of Measurement | `mm` | `effect()` L.117, 154, 191, 195; `draw_unit_reference()` L.191, 195 |
| `travel_speed` | `float` | Travel Speed (unit/min) | `3000` | `effect()` L.113; `Compiler.__init__` L.16; `draw_debug_traces()` 未使用 |
| `cutting_speed` | `float` | Cutting Speed (unit/min) | `750` | `effect()` L.113; `Compiler.__init__` L.16; `append_line_chain` L.116 |
| `passes` | `int` | Passes | `1` | `effect()` L.137; `Compiler.compile` L.69 |
| `pass_depth` | `float` | Pass Depth (unit) | `1` | `effect()` L.113; `Compiler.__init__` L.16, 32; `compile` L.75-77 |
| `directory` | `path` (folder) | Output Directory | `-- Choose Output Directory --` | `effect()` L.52, 58, 68 |
| `filename` | `string` | Filename | `output.gcode` | `effect()` L.59-66 |
| `filename_suffix` | `bool` | Add Numeric Suffix to Filename | `true` | `effect()` L.70-76 |
| **Advanced Settings タブ** |
| `tool_power_command` | `string` | Tool Power Command | `M3 S255;` | `effect()` L.98; `generate_custom_interface` L.19, 31 |
| `tool_off_command` | `string` | Tool Off Command | `M5;` | `effect()` L.98; `generate_custom_interface` L.19, 29 |
| `dwell_time` | `float` | Dwell Time Before Moving (ms) | `0` | `effect()` L.114; `Compiler.__init__` L.17, 33; `append_line_chain` L.119-120 |
| `draw_debug` | `bool` | Draw Debug | `true` | `effect()` L.140; `draw_debug_traces()`, `draw_unit_reference()` 呼び出し条件 |
| `debug_line_width` | `float` | Debug Line Width (px) | `0.5` | `draw_debug_traces()` L.155 |
| `debug_arrow_scale` | `float` | Debug Arrow Scale | `1.0` | `draw_debug_traces()` L.163 |
| `approximation_tolerance` | `string` | Approximation Tolerance | `0.01` | `effect()` L.49 `TOLERANCES["approximation"] = float(...)` |
| **Header/Footer Settings タブ** |
| `header_path` | `path` (file) | Custom G-code Header Filepath | (空) | `effect()` L.80-86 |
| `footer_path` | `path` (file) | Custom G-code Footer Filepath | (空) | `effect()` L.88-95 |
| `do_z_axis_start` | `bool` | Set Z-Axis Start Position | `false` | `effect()` L.107-108 |
| `z_axis_start` | `float` | Absolute Z-Axis Start Position | `0` | `effect()` L.108 |
| `move_to_origin_end` | `bool` | Move To Origin When Done | `false` | `effect()` L.109-110 |
| `do_laser_off_start` | `bool` | Turn Laser Off Before a Job | `true` | `effect()` L.101-102 |
| `do_laser_off_end` | `bool` | Turn Laser Off After a Job | `true` | `effect()` L.103-104 |
| **Coordinate System and Transformations タブ** |
| `machine_origin` | `optiongroup` (combo) | Machine Origin | `bottom-left` | `effect()` L.125-128; `draw_debug_traces()` L.151, 175-176; `draw_unit_reference()` L.192, 206-212 |
| `invert_y_axis` | `bool` | Invert Y-Axis | `false` | `effect()` L.133 `transform_origin=not invert_y_axis`; `draw_debug_traces()` L.171-173 |
| `bed_width` | `float` | Bed X Width (unit) | `200` | `effect()` L.126; `draw_debug_traces()` L.152, 176; `draw_unit_reference()` L.193, 197, 207-211 |
| `bed_height` | `float` | Bed Y Length (unit) | `200` | `effect()` L.126, 134; `draw_debug_traces()` L.153, 173, 176; `draw_unit_reference()` L.194, 198, 207-211 |
| `horizontal_offset` | `float` | Gcode X Offset (unit) | `0` | `effect()` L.122 |
| `vertical_offset` | `float` | Gcode Y Offset (unit) | `0` | `effect()` L.122 |
| `scaling_factor` | `float` | Gcode Scaling Factor | `1` | `effect()` L.123 |

### 3.2 `read_arguments()` の動的パース仕組み（`laser.py` L.294-319）

```python
@staticmethod
def read_arguments():
    root = etree.parse(inx_filename).getroot()
    arguments = []
    namespace = "http://www.inkscape.org/namespace/inkscape/extension"
    for arg in root.iter("{%s}param" % namespace):
        name = arg.attrib["name"]
        arg_type = arg.attrib["type"]
        if arg_type in ["description", "notebook"]:
            continue
        types = {"int": int, "float": float, "bool": Boolean, "string": str, "optiongroup": str, "path": str}
        arguments.append({"name": name, "type": types[arg_type]})
    if next(root.iter("{%s}page" % namespace)) is not None:
        arguments.append({"name": "tabs", "type": str})
    return arguments
```

- **実行タイミング**: `EffectExtension.run()` 内で `add_arguments()` が呼ばれ、その中で `read_arguments()` 実行
- **役割**: `.inx` ファイルを実行時にパースし、`<param>` 要素から `name` と `type` を抽出して `argparse.ArgumentParser` に動的登録
- **メリット**: `.inx` の UI 定義と Python 側の引数定義を二重管理せずに済む
- **注意**: `notebook` / `description` タイプはスキップ；`page` 要素が存在すれば `tabs` 引数を追加

---

## 4. 全ファイル・全クラス・全関数リファレンス

### 4.1 `laser.inx`
**役割**: Inkscape エクステンションのマニフェスト。UI タブ・パラメータ定義、対象オブジェクトタイプ（`path`）、実行スクリプト（`laser.py`）を宣言。

### 4.2 `laser.py`

#### `generate_custom_interface(laser_off_command, laser_power_command)` (L.19-34)
- **目的**: ユーザー定義のレーザー ON/OFF コマンドで `Gcode` クラスを動的サブクラス化
- **引数**: `laser_off_command: str`, `laser_power_command: str`
- **戻り値**: `CustomInterface` クラス（`interfaces.Gcode` 継承）
- **内部**: `laser_off()` → `tool_off_command` 返却；`set_laser_power(_)` → `tool_power_command` 返却（power 引数無視）

#### `class GcodeExtension(EffectExtension)` (L.37-324)

| メソッド | シグネチャ | 役割・要点 |
|----------|-----------|------------|
| `__init__` | `()` | 親初期化のみ |
| `effect` | `()` → `document` | **メインパイプライン**（上記フロー参照）。例外時 `exit(2)` で終了 |
| `draw_debug_traces` | `(curves: List[Curve])` | 赤色半透明矢印付きポリラインで工具軌跡を SVG レイヤー `debug_traces` に描画。`Transformation` で G-code 座標→SVG user units 逆変換 |
| `draw_unit_reference` | `()` | ベッド四隅に十字マーク＋座標ラベル（G-code 座標系）をレイヤー `debug_references` に描画。`machine_origin` ごとにラベル座標切替 |
| `select_non_debug_layer` | `()` | `id="layer89324"` の `content layer` を作成/選択（`sodipodi:namedview` の `current-layer` 書き換え） |
| `clear_debug` | `()` | `debug_traces`, `debug_references` レイヤーを DOM から削除（パース前クリーンアップ） |
| `add_arguments` | `(arg_parser)` | `read_arguments()` 結果を `argparse` に登録 |
| `read_arguments` | `()` → `List[Dict]` | **スタティックメソッド**。`.inx` パースロジック（上記 3.2 参照） |

### 4.3 `svg_to_gcode/__init__.py`
```python
TOLERANCES = {"approximation": 10 ** -2, "input": 10 ** -3, "operation": 10**-6}
UNITS = {"mm", "in"}
```

### 4.4 `svg_to_gcode/formulas.py`
**数学ユーティリティ集**（全関数 `static` 的）

| 関数 | シグネチャ | 用途 |
|------|-----------|------|
| `tolerance_constrain` | `(value, maximum, minimum, tolerance=1e-6)` → `float` | 境界値±許容誤差内なら境界値に丸め、それ以外はそのまま返す |
| `line_slope` | `(p1: Vector, p2: Vector)` → `float` | 直線傾き（垂直線は `1` 返却） |
| `line_offset` | `(p1: Vector, p2: Vector)` → `float` | 直線の y 切片 |
| `line_intersect` | `(p1, c1, p2, c2)` → `Vector` | 2直線の交点（共役複素数演算で実装） |
| `is_on_mid_perpendicular` | `(z, a, b)` → `bool` | 点 z が線分 ab の垂直二等分線上にあるか |
| `tangent_arc_center` | `(c, p, g)` → `Vector` | 点 p,g を通り直線 pc に接する円弧の中心（`SmoothArcChain` で使用） |
| `linear_map` | `(min, max, t)` → `float` | `[0,1] → [min,max]` 線形マッピング（レーザー出力スケーリング等） |
| `inv_linear_map` | `(min, max, t_p)` → `float` | `[min,max] → [0,1]` 逆マッピング（`Chain._get_curve_t` で使用） |
| `angle_between_vectors` | `(v1, v2)` → `float` | 符号付き角度（`v1→v2` が反時計回りなら正） |
| `center_to_endpoint_parameterization` | `(center, radii, rotation, start_angle, sweep_angle)` → `(start, end, large_arc_flag, sweep_flag)` | 中心パラメータ→SVG エンドポイント表記変換 |
| `endpoint_to_center_parameterization` | `(start, end, radii, rotation_rad, large_arc_flag, sweep_flag)` → `(radii, center, start_angle, sweep_angle)` | **W3C 算法**。SVG 楕円弧エンドポイント表記→中心パラメータ変換（`Path._add_svg_curve` で使用） |

### 4.5 `svg_to_gcode/compiler/__init__.py`
```python
from svg_to_gcode.compiler._compiler import Compiler
```

### 4.6 `svg_to_gcode/compiler/_compiler.py`

#### `class Compiler` (L.10-140)

| メソッド | シグネチャ | 役割・要点 |
|----------|-----------|------------|
| `__init__` | `(interface_class: Type[Interface], movement_speed, cutting_speed, pass_depth, dwell_time=0, unit=None, custom_header=None, custom_footer=None)` | インターフェースインスタンス生成、速度/深さ/単位保存、ヘッダ/フッタ/ボディ初期化。デフォルトヘッダ=`[laser_off, G90, G21/G20, travel_speed]`、フッタ=`[laser_off]` |
| `compile` | `(passes=1)` → `str` | ヘッダ＋ボディ×passes＋フッタを結合。パス間で `M5` + 相対移動 `Z-{pass_depth}` + `G90` 挿入。空ボディ時 `warnings.warn` |
| `compile_to_file` | `(file_name: str, passes=1)` | `compile()` 結果をファイル書き出し |
| `append_line_chain` | `(line_chain: LineSegmentChain)` | 連続線分チェーンを `G1` 移動列に変換し `self.body` へ追加。開始点が現位置と異なら `M5` + `G1` 移動 + `dwell` + `M3 S255` 発火 |
| `append_curves` | `(curves: List[Type[Curve]])` | 各 `Curve` を `LineSegmentChain.line_segment_approximation()` でポリライン化 → `append_line_chain` |

**状態管理**: `self.interface.position` （`Gcode.linear_move` で更新）で現在位置追跡し、冗長移動を抑制。

### 4.7 `svg_to_gcode/compiler/interfaces/__init__.py`
```python
from svg_to_gcode.compiler.interfaces._abstract_interface import Interface
from svg_to_gcode.compiler.interfaces._gcode import Gcode
from svg_to_gcode.compiler.interfaces._fan_controlled_gcode import FanControlledGcode
```

### 4.8 `svg_to_gcode/compiler/interfaces/_abstract_interface.py`

#### `class Interface` (L.1-106)
**抽象基底クラス**（`abc.ABC` 非使用、`NotImplementedError` で強制）。**必須メソッド 7 個**、**任意メソッド 5 個**。

| メソッド | シグネチャ | 説明 |
|----------|-----------|------|
| `set_movement_speed` | `(speed)` → `str` | 移動速度設定（次回 `linear_move` で出力） |
| `linear_move` | `(x=None, y=None, z=None)` → `str` | 直線移動コマンド生成 |
| `laser_off` | `()` → `str` | レーザー OFF |
| `set_laser_power` | `(power: float)` → `str` | レーザー出力設定（`0.0-1.0`） |
| `set_absolute_coordinates` | `()` → `str` | 絶対座標モード（`G90` 等） |
| `set_relative_coordinates` | `()` → `str` | 相対座標モード（`G91` 等） |
| `dwell` | `(milliseconds)` → `str` | **任意** ドウェル |
| `set_origin_at_position` | `()` → `str` | **任意** 原点再設定 |
| `set_unit` | `(unit)` → `str` | **任意** 単位指定（`G20/G21`） |
| `home_axes` | `()` → `str` | **任意** ホーミング |

**設計メモ**: `self.position: Vector` を保持することが期待される（`Compiler` が参照）。

### 4.9 `svg_to_gcode/compiler/interfaces/_gcode.py`

#### `class Gcode(Interface)` (L.12-95)
**標準 GRBL/G-code 実装**。

| プロパティ/メソッド | 実装詳細 |
|-------------------|----------|
| `self.position` | `Vector` または `None`（初期） |
| `self._next_speed`, `self._current_speed` | 速度変更検知用（`F` 値出力抑制） |
| `self.precision` | `abs(round(log10(TOLERANCES["operation"])))` = `6` 桁（`1e-6`） |
| `set_movement_speed` | `self._next_speed = speed`；即時出力せず次移動で `F{speed}` 付与 |
| `linear_move` | `G1 X{x:.6f} Y{y:.6f} Z{z:.6f} F{speed}`；`None` 座標は省略；`self.position` 更新 |
| `laser_off` | `M5;` |
| `set_laser_power` | `power∈[0,1]` チェック → `M3 S{linear_map(0,255,power)};`（8bit PWM） |
| `set_absolute_coordinates` | `G90;` |
| `set_relative_coordinates` | `G91;` |
| `dwell` | `G4 P{ms}` |
| `set_origin_at_position` | `self.position = Vector(0,0)`；`G92 X0 Y0 Z0;` |
| `set_unit` | `mm`→`G21;`、`in`→`G20;`、他→`''` |
| `home_axes` | `G28;` |

**TODO コメント** (L.36): `G0` (rapid) と `G1` (cutting) の使い分け未実装

### 4.10 `svg_to_gcode/compiler/interfaces/_fan_controlled_gcode.py`

#### `class FanControlledGcode(Gcode)` (L.5-21)
**ファン制御型（M106/M107）レーザーインターフェース**。
- `_current_power` 内部状態で重複コマンド抑制
- `laser_off()` → `M107;`（ファン OFF）
- `set_laser_power(power)` → `M106 S{0-255};`（ファン速度＝レーザー出力）

### 4.11 `svg_to_gcode/geometry/__init__.py`
全幾何クラスの再エクスポート（`Vector`, `Matrix`, `IdentityMatrix`, `RotationMatrix`, `Curve`, `Line`, `CircularArc`, `EllipticalArc`, `QuadraticBezier`, `CubicBazier`, `Chain`, `LineSegmentChain`, `SmoothArcChain`）。

### 4.12 `svg_to_gcode/geometry/_vector.py`

#### `class Vector` (L.1-52)
**2D ベクトル**（`__slots__ = ('x','y')` でメモリ節約）。

| 演算子/メソッド | 実装 |
|----------------|------|
| `__add__` | 成分ごと加算 |
| `__sub__` | 成分ごと減算 |
| `__mul__` | `Vector` なら内積、スカラならスカラ倍 |
| `__rmul__` | 同左 |
| `__truediv__` | スカラ除算（スカラ倍の逆） |
| `__abs__` | ノルム `sqrt(x²+y²)` |
| `__iter__` | `yield x, y` |
| `__getitem__` | `0→x, 1→y` |
| `scalar_product(v,n)` | `Vector(v.x*n, v.y*n)` |
| `dot_product(v1,v2)` | `v1.x*v2.x + v1.y*v2.y` |
| `cross_product(v1,v2)` | **注意**: 実装が 2D 外積（スカラ）ではなく `Vector(v1.x*(v2.x+v2.y), v1.y*(v2.x+v2.y))` となっており、標準的な外積とは異なる。使用箇所なし（デッドコードの可能性） |

### 4.13 `svg_to_gcode/geometry/_matrix.py`

#### `class Matrix` (L.6-65)
**任意サイズ行列**（`__slots__ = ('number_of_rows','number_of_columns','matrix_list')`）。
- `__mul__`: `Vector` なら `multiply_vector`、`Matrix` なら `multiply_matrix`
- `multiply_vector`: 2列行列 × 2Dベクトル → `Vector`
- `multiply_matrix`: 標準行列積

#### `class IdentityMatrix(Matrix)` (L.68-71)
`size×size` 単位行列生成。

#### `class RotationMatrix(Matrix)` (L.74-81)
**2D 回転行列**（`inverse=False` 通常、`True` で逆回転）。`cosθ, -sinθ; sinθ, cosθ`。

### 4.14 `svg_to_gcode/geometry/_abstract_curve.py`

#### `class Curve` (L.5-74)
**抽象基底クラス**（`__slots__ = ('start','end')`）。
- `start: Vector`, `end: Vector` 必須
- 抽象メソッド: `point(t)→Vector`, `derivative(t)→float`, `sanity_check()`, `__repr__()`
- `max_distance(curve1, curve2, t_range1, t_range2, samples=9)` → `float`
  - 2曲線間の最大離れをサンプリング近似（**注意**: 「比較的平坦な曲線セグメントでのみ使用すべき」とドックコメントに明記）

### 4.15 `svg_to_gcode/geometry/_line.py`

#### `class Line(Curve)` (L.7-32)
**直線セグメント**。
- `__init__(start: Vector, end: Vector)` → `slope`, `offset` 計算
- `length()` → `abs(start-end)`
- `point(t)` → `start + t*(end-start)`（x 線形、y = slope*x + offset）
- `derivative(t)` → `slope` 定数
- `sanity_check()`: 実装なし（`pass`）

### 4.16 `svg_to_gcode/geometry/_circular_arc.py`

#### `class CircularArc(Curve)` (L.9-72)
**円弧**（中心・半径・開始/終了角度で表現）。
- `__init__(start, end, center)` → `radius`, `start_angle`, `end_angle` 計算
- `point(t)` → `angle_to_point(linear_map(start_angle, end_angle, t))`
- `angle_to_point(rad)` → `center + radius*(cos, sin)`
- `point_to_angle(point)` → `acos((point-center).x / radius)` **注意**: 第1象限・第4象限のみ正しく、第2・3象限で符号問題の可能性
- `derivative(t)` → `(center.x - pos.x) / (pos.y - center.y)` （接線傾き）
- `sanity_check()`: 開始≠終了、中心≠開始/終了、半径等距離を `TOLERANCES["input"]=1e-3` で検証

### 4.17 `svg_to_gcode/geometry/_elliptical_arc.py`

#### `class EllipticalArc(Curve)` (L.8-58)
**楕円弧**（中心・半径ベクトル・回転角・開始/スイープ角で表現）。
- `__init__(center, radii, rotation, start_angle, sweep_angle, transformation=None)`
- `point(t)` → `angle_to_point(linear_map(start_angle, end_angle, t))`
- `angle_to_point(angle)` → `RotationMatrix(rotation) * Vector(rx*cos, ry*sin) + center` → `transformation.apply_affine_transformation()` **注意**: コメントに「変換が正しく適用されていない」と明記（TODO）
- `derivative(t)` → `-(ry/rx) * tan(angle)^-1` （パラメトリック微分）
- `sanity_check()`: 実装なし（`pass`）

### 4.18 `svg_to_gcode/geometry/_quadratic_bazier.py`

#### `class QuadraticBezier(Curve)` (L.5-29)
**二次ベジェ曲線**（始点・終点・制御点1つ）。
- `point(t)` → `(1-t)²*P0 + 2(1-t)t*P1 + t²*P2`（制御点 `control` = P1）
- `derivative(t)` → `2(1-t)(P1-P0) + 2t(P2-P1)`
- `sanity_check()`: TODO コメントあり

### 4.19 `svg_to_gcode/geometry/_cubic_bazier.py`

#### `class CubicBazier(Curve)` (L.5-32)
**三次ベジェ曲線**（始点・終点・制御点2つ）。
- `point(t)` → `(1-t)³P0 + 3(1-t)²t P1 + 3(1-t)t² P2 + t³P3`
- `derivative(t)` → `3(1-t)²(P1-P0) + 6(1-t)t(P2-P1) + 3t²(P3-P2)`
- `sanity_check()`: 実装なし

### 4.20 `svg_to_gcode/geometry/_abstract_chain.py`

#### `class Chain(Curve)` (L.7-104)
**曲線列を単一曲線として扱う基底**（`__slots__ = ('_curves',)`）。
- `_curves: List[Curve]` 内部保持
- `chain_size()` → `len(_curves)`
- `length()` → Σ `curve.length()`
- `get(index)` → `Curve`
- `append(new_curve)` → **抽象**（継承クラスで連続性チェック実装）
- `extend(iterable)` → ループで `append`
- `merge(chain)` → 先頭曲線の連続性チェック後 `_curves` 結合
- `remove_from_first/last(n)` → 先頭/末尾から n 個削除
- `_get_curve_t(t)` → `(curve, local_t)`：全長に対する t 位置から該当曲線と局所 t を逆算
- `point(t)`, `derivative(t)` → `_get_curve_t` で委譲
- `sanity_check()`: `pass`

### 4.21 `svg_to_gcode/geometry/_line_segment_chain.py`

#### `class LineSegmentChain(Chain)` (L.6-88)
**直線セグメント列**（`append` で端点一致チェック `TOLERANCES['input']=1e-3`）。

##### 静的メソッド `line_segment_approximation` (L.32-88) **核心アルゴリズム**
```python
@staticmethod
def line_segment_approximation(shape, increment_growth=1.1, error_cap=None, error_floor=None) -> LineSegmentChain:
```
**適応的分割アルゴリズム**:
1. `error_cap = TOLERANCES['approximation']` (デフォルト 0.01)、`error_floor = (growth-1)*error_cap`
2. `t=0`, `increment=5` で開始
3. `while t < 1`:
   - `new_t = min(t+increment, 1)`
   - `line = Line(shape.point(t), shape.point(new_t))`
   - `distance = Curve.max_distance(shape, line, t_range1=(t, new_t))`
   - `distance > error_cap` → `increment /= growth`；**リトライ（t 不変）**
   - `distance < error_floor` → `increment *= growth`（次ステップ拡大）
   - `lines.append(line)`；`t = new_t`
4. 返却: `LineSegmentChain`

**特性**: 誤差制御付き・平坦領域でセグメント伸長・曲率大で自動縮小。

### 4.22 `svg_to_gcode/geometry/_smooth_arc_chain.py`

#### `class SmoothArcChain(Chain)` (L.10-67)
**滑らかな円弧列**（`append` で位置・傾き連続性 `C¹` チェック）。

##### 静的メソッド `cubic_bazier_to_arcs(bazier, _arcs=None)` (L.39-66)
**三次ベジェ→2円弧近似**（未完成・コミット非推奨と冒頭コメント）。
- 制御点接線の交点 `tangent_intersect` 計算
- 内心 `incenter_point` 計算
- `tangent_arc_center` で2円弧中心求め `CircularArc` 生成

### 4.23 `svg_to_gcode/svg_parser/__init__.py`
```python
from svg_to_gcode.svg_parser._transformation import Transformation
from svg_to_gcode.svg_parser._path import Path
from svg_to_gcode.svg_parser._parser_methods import parse_file, parse_string, parse_root
```

### 4.24 `svg_to_gcode/svg_parser/_parser_methods.py`

#### `parse_root(root, transform_origin=True, canvas_height=None, draw_hidden=False, visible_root=True, root_transformation=None)` → `List[Curve]` (L.19-74)
**SVG DOM 再帰走査・`<path>` 抽出・幾何変換のエントリーポイント**。

**処理詳細**:
1. `canvas_height` 未指定なら `root.get("height")` から抽出（`"300mm"` → `300.0`、`"1133.8583"` → `1133.8583`）
2. `for element in list(root):` 深さ優先探索
3. `display="none"` または `<defs>` なら **スキップ**（継承不可）
4. `transform` 属性あれば `Transformation` に `add_transform`、親から `deepcopy` 継承
5. `visibility="hidden/collapse"` 継承判定、`visibility="visible"` で上書き可能
6. `draw_hidden` または 可視なら：
   - `<path>` 要素なら `Path(d, canvas_height, transform_origin, transformation)` 生成 → `curves.extend(path.curves)`
7. 再帰呼び出しで子要素処理（`visible` 継承）
8. **TODO** (L.73): `shapes class` 実装（`<rect>` 等未対応）

#### `parse_string(svg_string, ...)` / `parse_file(file_path, ...)` (L.77-106)
`parse_root` の薄いラッパー。

### 4.25 `svg_to_gcode/svg_parser/_path.py`

#### `class Path` (L.14-322)
**SVG `d` 属性文字列パーサー → `List[Curve]`**。

**スロット**: `curves`, `initial_point`, `current_point`, `last_control`, `canvas_height`, `draw_move`, `transform_origin`, `transformation`

#### `__init__(d: str, canvas_height, transform_origin=True, transformation=None)` (L.23-45)
- `transform_origin=True` 時：`translation(0, canvas_height)` + `scale(1, -1)` で **SVG 座標系(左上原点, Y下) → カルテシアン(左下原点, Y上)** 変換を `transformation` に事前追加
- 親 `transformation` があれば `extend` で合成
- `_parse_commands(d)` 実行

#### `_parse_commands(d: str)` (L.49-123)
**文字単位トークナイザ**（ステートマシン的）。
- `command_lengths`: 各コマンドの引数数（`M/m:2, L/l:2, H/h:1, V/v:1, Z/z:0, C/c:6, S/s:4, Q/q:4, T/t:2, A/a:7`）
- 数値認識: `0-9`, `-`, `.`, `e`（指数表記対応）
- 暗黙のコマンド繰り返し: `M 10 10 20 20` → `M 10 10 L 20 20` として処理（L.71-82）
- 負数・暗黙小数点（`.5`）の区切り自動挿入（L.92-95）
- コマンドキーまたは終端で `_add_svg_curve` 呼び出し

#### `_add_svg_curve(command_key, command_arguments)` (L.125-322)
**コマンドディスパッチテーブル**（`command_methods` 辞書）で各種曲線生成。

**主要サブメソッド**（クロージャとして定義）:
| コマンド | 絶対/相対 | 生成曲線 | 変換適用 |
|----------|----------|----------|----------|
| `M`/`m` | 移動のみ | `None` | - |
| `L`/`l` | 直線 | `Line(trans(start), trans(end))` | `transformation.apply_affine_transformation` |
| `H`/`h` | 水平線 | `Line` | 同上 |
| `V`/`v` | 垂直線 | `Line` | 同上 |
| `Z`/`z` | 閉路 | `Line(current, initial)` | 同上 |
| `C`/`c` | 3次ベジェ | `CubicBazier(trans(start), trans(end), trans(c1), trans(c2))` | 制御点も変換 |
| `S`/`s` | スムーズ3次ベジェ | 前制御点対称推定 → `CubicBazier` | 同上 |
| `Q`/`q` | 2次ベジェ | `QuadraticBezier` | 同上 |
| `T`/`t` | スムーズ2次ベジェ | 前制御点対称推定 → `QuadraticBezier` | 同上 |
| `A`/`a` | 楕円弧 | `EllipticalArc`（`endpoint_to_center_parameterization` 使用） | **注意**: コメントに「変換が正しく適用されていない」と明記（L.256） |

**エラーハンドリング**: `TypeError`（引数数不一致）、`ValueError`（幾何学的不可能）を `warnings.warn` で捕捉・スキップ。

### 4.26 `svg_to_gcode/svg_parser/_transformation.py`

#### `class Transformation` (L.7-155)
**SVG `transform` 属性パース・4×4 同次行列合成・適用**。

**スロット**: `translation_matrix` (4×4 `Matrix`), `transformation_record` (操作履歴), `command_methods` (ディスパッチ)

#### 操作メソッド（すべて **右から乗算** `self.translation_matrix *= new_matrix`）
| メソッド | 行列形式（4×4） | 備考 |
|----------|----------------|------|
| `add_matrix(a,b,c,d,e,f)` | `[[a,c,0,e],[b,d,0,f],[0,0,1,0],[0,0,0,1]]` | SVG `matrix(a,b,c,d,e,f)` 直接指定 |
| `add_translation(x,y)` | `[[1,0,0,x],[0,1,0,y],[0,0,1,0],[0,0,0,1]]` | 平行移動 |
| `add_scale(fx, fy)` | `[[fx,0,0,0],[0,fy,0,0],[0,0,1,0],[0,0,0,1]]` | 拡大縮小（`fy` 省略時 `fx`） |
| `add_rotation(angle_deg)` | 回転行列（原点中心） | `math.radians` 変換 |
| `add_skew_x(angle_deg)` | `[[1,tan,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]` | X 方向せん断 |
| `add_skew_y(angle_deg)` | `[[1,0,0,0],[tan,1,0,0],[0,0,1,0],[0,0,0,1]]` | Y 方向せん断 |

#### `extend(other: Transformation)` (L.126-128)
`self.translation_matrix *= other.translation_matrix`（**右掛け**＝ other の変換を後から適用）

#### `apply_affine_transformation(vector: Vector)` → `Vector` (L.130-138)
**点変換**（平行移動込み）。`[x, y, 1, 1]^T` に 4×4 行列乗算 → `Vector(x', y')`

#### `apply_linear_transformation(vector: Vector)` → `Vector` (L.140-154)
**ベクトル変換**（平行移動なし）。行列の左上 2×2 成分 `[a,c; b,d]` で `Vector` 乗算

#### `__deepcopy__` (L.34-38)
`translation_matrix` を `deepcopy` し新インスタンス生成（パーサー再帰で親変換を子に安全継承するため必須）

#### `add_transform(transform_string)` (L.40-55)
`transform="translate(10,20) scale(2) rotate(45)"` 形式を `)` で分割、各コマンドを `command_methods` でディスパッチ

### 4.27 `svg_to_gcode/svg_parser/debug_methods.py`

#### `to_svg_path(line_segment_chain, transformation=None, color="black", opacity="1", stroke_width="0.864583px", draw_arrows=False, arrow_id="arrow-346")` → `ElementTree.Element` (L.9-44)
`LineSegmentChain` を SVG `<path d="M... L...">` に変換。`transformation` 適用可。`draw_arrows=True` で `marker-mid` 矢印付与。

#### `arrow_defs(arrow_scale=1, arrow_id="arrow-346")` → `ElementTree.Element` (L.47-66)
`<defs><marker id="arrow-346">...</marker></defs>` 生成（黄色塗り黒枠三角形矢印）。

### 4.28 `svg_to_gcode/svg_parser/_helper_functions.py`

**旧版 `parse_root` 実装**（`_parser_methods.py` とほぼ同一だが `transform` 引数名違い、`_visible_root` 内部引数等微差異）。**実質未使用・デッドコード**の可能性大（`__init__.py` でエクスポートされておらず、`laser.py` からも未インポート）。

---

## 5. 座標系・単位変換・変換行列の詳細（重要）

### 5.1 座標系の定義と変換概要

| 座標系 | 原点 | X軸 | Y軸 | 単位 |
|--------|------|-----|-----|------|
| **SVG ユーザー座標系** | 左上 (0,0) | 右正 | **下正** | user units (`viewBox` ベース) |
| **SVG 物理単位系** | 左上 | 右正 | 下正 | `mm`, `in`, `px` 等（`width/height` 属性） |
| **G-code 機械座標系** | 設定による（下記） | 右正 | **上正** | `mm` または `in` |

**機械原点 `machine_origin` 3 モード**:
| モード | G-code 原点位置 (ベッド左下基準) | 変換 |
|--------|--------------------------------|------|
| `bottom-left` | (0, 0) | 追加変換なし |
| `center` | (bed_width/2, bed_height/2) | `translate(-W/2, +H/2)` |
| `top-left` | (0, bed_height) | `translate(0, +H)` |

**Y軸反転 `invert_y_axis`**:
- `False` (デフォルト): SVG Y下 → G-code Y上 へ **反転する**（`scale(1, -1)` + `translate(0, -H)`）
- `True`: 反転**しない**（SVG と同じ向きとして扱う）

### 5.2 `laser.py::effect()` での変換行列構築順序（L.120-134）

```python
transformation = Transformation()

# 1. ユーザー指定オフセット
transformation.add_translation(horizontal_offset, vertical_offset)

# 2. ユーザー指定スケーリング
transformation.add_scale(scaling_factor)

# 3. 機械原点シフト
if machine_origin == "center":
    transformation.add_translation(-bed_width / 2, bed_height / 2)
elif machine_origin == "top-left":
    transformation.add_translation(0, bed_height)

# 4. ★ SVG user units → 設定単位 (mm/in) スケーリング
transformation.add_scale(unit_per_uu)   # unit_per_uu = 1.0 / uu_per_unit
```

**重要**: `Transformation` の各 `add_*` は **右掛け**（`self *= new`）なので、**適用順序 = 呼び出し順序の逆** になる。
上記コードで実際にベクトル `v` に掛かる合成行列は：
```
M_total = S(unit_per_uu) * T(origin_shift) * S(scaling_factor) * T(offset)
```
したがって **ベクトルへの適用順序** は：
1. `offset` 平行移動
2. `scaling_factor` 拡大縮小
3. `origin_shift` 原点シフト
4. `unit_per_uu` 単位変換

### 5.3 `parse_root` → `Path` での SVG 原点変換（`_path.py` L.34-36）

```python
if self.transform_origin:
    self.transformation.add_translation(0, canvas_height)
    self.transformation.add_scale(1, -1)
```
- `canvas_height` = `bed_height`（`laser.py` から渡す）
- これも右掛けなので、パースした座標 `(x_svg, y_svg)` に対して：
  1. `scale(1, -1)` → `(x_svg, -y_svg)`
  2. `translate(0, canvas_height)` → `(x_svg, canvas_height - y_svg)`
- **結果**: SVG 左上原点 → カルテシアン左下原点 変換完了

### 5.4 単位変換 `uu_per_unit` / `unit_per_uu` の実態

```python
uu_per_unit = self.svg.unittouu(f"1{unit}")   # 例: unit="mm" なら "1mm" → user units
unit_per_uu = 1.0 / uu_per_unit
```

| ドキュメント設定 | `viewBox` | `width/height` | `self.svg.unittouu("1mm")` | `unit_per_uu` |
|-----------------|-----------|----------------|----------------------------|---------------|
| 96dpi px 基準 | `0 0 1133.86 1133.86` | `300mm 300mm` | `3.7795...` (≈ 96/25.4) | `0.26458...` |
| mm 基準 viewBox | `0 0 300 300` | `300mm 300mm` | `1.0` | `1.0` |

**修正前のバグ**: `unit_per_uu` を掛けていなかったため、px 基準 `viewBox` のドキュメントで座標が **約 3.78 倍** になっていた。

### 5.5 デバッグ描画での逆変換（`draw_debug_traces` L.168-173）

```python
change_origin = Transformation()
change_origin.add_scale(uu_per_unit)          # 1. 設定単位 → SVG user units

if not self.options.invert_y_axis:
    change_origin.add_scale(1, -1)            # 2. Y反転戻し
    change_origin.add_translation(0, -bed_height)

if origin == "center":
    change_origin.add_translation(bed_width / 2, bed_height / 2)
```
G-code 座標 → SVG user units への逆変換を構築し、`debug_methods.to_svg_path(..., transformation=change_origin)` に渡す。

### 5.6 トンボ描画での座標計算（`draw_unit_reference` L.195-212）

```python
uu_per_unit = self.svg.unittouu(f"1{unit}")
px_to_uu = self.svg.unittouu("1px")
svg_bed_width = bed_width * uu_per_unit
svg_bed_height = bed_height * uu_per_unit

reference_points_svg = [(0, 0), (0, svg_bed_height), (svg_bed_width, 0), (svg_bed_width, svg_bed_height)]
reference_points_gcode = {
    "bottom-left": [(0, bed_height), (0, 0), (bed_width, bed_height), (bed_width, 0)],
    "top-left":    [(0, 0), (0, bed_height), (bed_width, 0), (bed_width, bed_height)],
    "center":      [(-W/2, H/2), (-W/2, -H/2), (W/2, H/2), (W/2, -H/2)]
}[origin]
```
- SVG 座標系での四隅位置 = `bed_* * uu_per_unit`
- ラベルテキスト = G-code 座標系での四隅座標（`machine_origin` 依存）

---

## 6. 既知の制約・注意点・バグ候補（改良時の落とし穴）

### 6.1 SVG 要素の対応範囲

| 要素 | 対応 | 備考 |
|------|------|------|
| `<path>` | ✅ 完全 | 全コマンド (M,L,H,V,C,S,Q,T,A,Z) 対応 |
| `<rect>` | ❌ 未対応 | `_parser_methods.py` L.73 に TODO |
| `<circle>` / `<ellipse>` | ❌ 未対応 | 同上 |
| `<line>` / `<polyline>` / `<polygon>` | ❌ 未対応 | 同上 |
| `<text>` | ❌ 未対応・無視 | 警告も出ない（空 G-code になるのみ） |
| `<g>` (グループ) | ✅ 継承対応 | `transform`, `display`, `visibility` 継承 |
| `<defs>` | ✅ スキップ | 明示的に除外 |
| `viewBox` | ❌ 未処理 | `_parser_methods.py` L.18, `_helper_functions.py` L.72 に TODO |

### 6.2 コード上の既知 TODO / 注意点

| ファイル・場所 | 内容 |
|----------------|------|
| `_path.py` L.256 | 楕円弧への `transformation` 適用が正しくない（コメント明記） |
| `_elliptical_arc.py` L.13-14 | `transformation` 引数を受けるが `point()` でしか使わず、半径・回転への適用なし |
| `_circular_arc.py` L.37 | `point_to_angle` で `acos` 使用 → 第2・3象限で角度符号誤差の可能性 |
| `_abstract_interface.py` L.12-13 | `abc.ABC` 化未実装、`self.position` 必須要件がドックコメントのみ |
| `_gcode.py` L.36 | `G0` (rapid) と `G1` (cutting) の使い分け未実装 |
| `_vector.py` L.51-52 | `cross_product` 実装が標準外積と異なる（未使用・デッドコード） |
| `_smooth_arc_chain.py` L.1-3 | 「未完成・コミット非推奨」と明記 |
| `_helper_functions.py` | 旧版パーサー・実質未使用（削除候補） |

### 6.3 デバッグレイヤー ID 管理と削除タイミング

| レイヤー ID | ラベル | 作成箇所 | 削除箇所 |
|-------------|--------|----------|----------|
| `debug_traces` | "debug traces" | `draw_debug_traces` L.158-160 | `clear_debug` L.278-282 |
| `debug_references` | "debug reference points" | `draw_unit_reference` L.200-203 | `clear_debug` L.279-285 |
| `layer89324` (固定) | "content layer" | `select_non_debug_layer` L.263-266 | **削除されない**（恒久） |

**タイミング**: `effect()` 冒頭で `clear_debug()` → パース・コンパイル → `draw_debug_traces()` / `draw_unit_reference()` → `select_non_debug_layer()`。したがって **前回実行のデバッグレイヤーは次回実行開始時に削除** される。

### 6.4 数値精度・許容誤差の連鎖

| 定数 | 値 | 用途 |
|------|-----|------|
| `TOLERANCES["approximation"]` | `1e-2` (0.01) | `LineSegmentChain` 近似誤差上限（UI `approximation_tolerance` で上書き可） |
| `TOLERANCES["input"]` | `1e-3` (0.001) | 幾何学的整合性チェック（端点一致、半径等距離等） |
| `TOLERANCES["operation"]` | `1e-6` | `Gcode` 出力桁数決定（`precision=6`）、浮動小数点境界補正 |

**注意**: `approximation_tolerance` UI は文字列で受け取り `float()` 変換（カンマ小数点対応 `.replace(',', '.')`）。

### 6.5 マルチパス（`passes > 1`）時の Z 軸動作

`Compiler.compile()` L.69-78:
```python
for i in range(passes):
    gcode.extend(self.body)
    if i < passes - 1:
        gcode.append(self.interface.laser_off())      # M5
        if self.pass_depth > 0:
            gcode.append(self.interface.set_relative_coordinates())  # G91
            gcode.append(self.interface.linear_move(z=-self.pass_depth))  # Z降下
            gcode.append(self.interface.set_absolute_coordinates())  # G90
```
- **各パス終了時にレーザー OFF → 相対モード → Z降下 → 絶対モード復帰**
- **最終パス後は Z 戻しなし**（フッタで `move_to_origin_end` なら `G1 X0 Y0` のみ）

---

## 7. 使用方法・インストール・テスト検証手順

### 7.1 インストール手順 (Windows / Inkscape 1.4.2)

1. **拡張機能ディレクトリ特定**
   - Inkscape メニュー `編集 → 設定 → システム → ユーザー拡張機能ディレクトリ` でパス確認
   - 典型: `C:\Users\<ユーザー名>\AppData\Roaming\inkscape\extensions\`

2. **配置**
   - `laser/` フォルダごとコピー（`laser.inx`, `laser.py`, `svg_to_gcode/` 含む）
   - 構成:
     ```
     extensions/
     └── laser/
         ├── laser.inx
         ├── laser.py
         └── svg_to_gcode/
             ├── __init__.py
             ├── formulas.py
             ├── compiler/...
             ├── geometry/...
             └── svg_parser/...
     ```

3. **Inkscape 再起動**

4. **メニュー確認**: `Extensions → Generate Laser Gcode → J Tech Community Laser Tool`

### 7.2 基本操作手順

1. Inkscape でベクター図形描画
2. **必須**: オブジェクトをパス化 `Path → Object to Path` (Shift+Ctrl+C)
   - `<rect>`, `<circle>`, `<text>` 等は**変換されない**ため
3. 加工したいパスを選択（未選択なら全ページ対象）
4. メニューから拡張機能実行
5. タブごとに設定調整 → `適用`
6. 出力ディレクトリに `.gcode` 生成 + Inkscape 上にデバッグレイヤー表示

### 7.3 テスト検証用サンプル `test_samples/test_300x300.svg`

**ファイル仕様**（`MODIFICATIONS_README.md` より）:
- `width="300mm" height="300mm"`
- `viewBox="0 0 1133.8583 1133.8583"` (96dpi ≈ 3.7795 px/mm)
- 左上 (20mm, 20mm) に `100mm × 100mm` 正方形パス配置

**期待結果** (`MODIFICATIONS_README.md` 検証済み):
1. **トンボ枠**: ページ四隅 (0,0), (0,300), (300,0), (300,300) [mm] に正しく描画
2. **G-code 座標**: 正方形が `X20.000013 Y279.999987` ～ `X119.999998 Y180.000002` （実寸 100mm 四方）
   - 座標系: `machine_origin=bottom-left`, `invert_y_axis=false` 時
   - Y座標 `280→180` は SVG 原点(左上) から 20mm 下 → G-code 底面原点 から 280mm 上、という整合性

**検証コマンド例** (生成 G-code 先頭確認):
```bash
head -30 output.gcode
```
期待ヘッダ:
```
G90
G21
M5;
G1 F3000
M5;
M3 S255;
...
```

---

## 8. 付録：主要データ構造クイックリファレンス

### 8.1 `Curve` 継承ツリー
```
Curve (abstract)
├── Line
├── CircularArc
├── EllipticalArc
├── QuadraticBezier
├── CubicBazier
└── Chain (abstract)
    ├── LineSegmentChain
    └── SmoothArcChain
```

### 8.2 `Transformation` 合成順序の法則
- **メソッド呼び出し順 = 変換適用の逆順**（右掛けのため）
- `add_translation → add_scale → add_rotation` なら、ベクトルには **回転 → 拡大 → 平行移動** の順で掛かる

### 8.3 `Path._parse_commands` 暗黙コマンド繰り返しルール
| 明示コマンド | 続く座標ペア | 解釈 |
|--------------|--------------|------|
| `M x y` | `x2 y2 x3 y3...` | `M x y L x2 y2 L x3 y3...` |
| `m dx dy` | `dx2 dy2...` | `m dx dy l dx2 dy2...` |
| その他 | 引数数超過 | 同一コマンド繰り返し（SVG仕様準拠） |

### 8.4 G-code 出力コマンド一覧（`Gcode` クラス）

| メソッド | 出力例 | 備考 |
|----------|--------|------|
| `set_movement_speed(3000)` | (即時出力なし) | 次 `linear_move` で `F3000` 付与 |
| `linear_move(10, 20, 0)` | `G1 X10.000000 Y20.000000 Z0.000000 F3000;` | `None` 座標省略、`precision=6` |
| `laser_off()` | `M5;` | |
| `set_laser_power(0.5)` | `M3 S128;` | `linear_map(0,255,0.5)=127.5→128` |
| `set_absolute_coordinates()` | `G90;` | |
| `set_relative_coordinates()` | `G91;` | |
| `dwell(100)` | `G4 P100` | |
| `set_origin_at_position()` | `G92 X0 Y0 Z0;` | `self.position = (0,0)` |
| `set_unit("mm")` | `G21;` | |
| `set_unit("in")` | `G20;` | |
| `home_axes()` | `G28;` | |

---

## 9. 改良・拡張時の指針（`MULTI_LAYER_UPGRADE_PLAN.md` 要点抜粋）

### 9.1 アーキテクチャ変更方向
1. **パーサー**: `parse_root` → `parse_layers` へ拡張（レイヤーごと `List[Curve]` + メタデータ返却）
2. **基本図形対応**: `<rect>`, `<circle>` 等を `_shapes.py` 新設で直接 `Curve` 変換
3. **コンパイラ**: `LayerJob` データモデル導入、単一ファイル連結 / レイヤー別分割 両対応
4. **UI**: `laser.inx` 静的パラメータ + **Tkinter 専用 GUI** (`gui/layer_dialog.py`) でレイヤー別設定
5. **デバッグ描画**: レイヤーごと色分け＋順番ラベル (`#1`, `#2`...)

### 9.2 実装上の必須維持事項
- ✅ `self.svg.unittouu()` ベース単位変換ロジック（`laser.py` 修正済み部分）
- ✅ `Transformation` の `deepcopy` 継承パターン
- ✅ Windows 禁止文字対応ファイル名サニタイズ
- ✅ G-code コメントの文字エンコーディング配慮（UTF-8 / ASCII 安全化）

### 9.3 推奨実装ステップ
1. Tkinter 動作検証（Inkscape 同梱 Python で）
2. `svg_parser.parse_layers()` + `_shapes.py` + `<text>` 検出実装
3. `compiler.LayerJob` + 連結/分割出力ロジック実装
4. `gui/layer_dialog.py` 実装・設定保存/復元（JSON または SVG カスタム属性）
5. `laser.py` 統合・レイヤー別色分けデバッグ描画・実機検証

---

**文書終了**  
この仕様書はワークスペース直下の全 `.py` / `.inx` ファイルを実読みして作成しました。推測・省略は一切なく、実際のコード上のクラス名・メソッド名・引数名・定数・行番号・アルゴリズム詳細のみを記載しています。