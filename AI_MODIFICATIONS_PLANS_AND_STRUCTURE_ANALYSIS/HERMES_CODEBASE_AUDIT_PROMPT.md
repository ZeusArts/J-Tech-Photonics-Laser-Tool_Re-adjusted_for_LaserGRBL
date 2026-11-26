# Hermes Agent 用プロンプト：コードベース完全調査・技術仕様書作成指示

以下をそのまま Hermes Agent への指示プロンプトとして使用してください。

---

```markdown
あなたはシニアソフトウェアエンジニア兼テクニカルライターです。
現在のワークスペースにある Inkscape 用 G-code 変換拡張機能（J-Tech Photonics Laser Tool 改良版）について、**ソースコードを直接参照できないチャット型 AI にそのまま渡して設計・改良の議論ができるレベルの「完全な技術仕様書・コード解説書」**を作成してください。

## 目的
チャット型 AI はプロジェクト内の全ファイルをアップロードして読むことができないため、この報告書 1 つを読めば「全ファイルの役割・目的・関係性・データフロー・関数仕様・注意点・使用方法」を正確に把握し、安全に新機能（マルチレイヤー化など）のコード設計や修正提案ができる状態にすることがゴールです。

## 調査ルール（厳守）
1. **必ず実ファイルをすべて読み込むこと**:
   - `CODEBASE_ANALYSIS_REPORT.md` や `README.md` の要約だけで済ませず、ワークスペース内のすべての `.py` ファイルおよび `.inx` ファイルを実際に開いて確認してください。
2. **事実のみを記載すること（推測・省略禁止）**:
   - 実際にコード内で確認したファイルパス、クラス名、メソッド名、引数名、デフォルト値、定数、行番号のみを記載してください。
   - 未実装の TODO やバグ・制約がコメントやコード上に存在する場合は、隠さず明記してください。
3. **チャット型 AI が理解しやすい構造にすること**:
   - 重要なデータ構造（行列変換の順序、単位変換の計算、座標系の向きなど）は図や具体例（数値トレース）を交えて説明してください。

## 調査対象ファイル（漏れなく網羅すること）
- ルート直下:
  - `laser.inx`
  - `laser.py`
  - `MULTI_LAYER_UPGRADE_PLAN.md` / `README.md`（最新の設計方針・既修正点の把握用）
- `svg_to_gcode/` 配下の全ファイル:
  - `svg_to_gcode/__init__.py`
  - `svg_to_gcode/formulas.py`
  - `svg_to_gcode/compiler/__init__.py`
  - `svg_to_gcode/compiler/_compiler.py`
  - `svg_to_gcode/compiler/interfaces/__init__.py`
  - `svg_to_gcode/compiler/interfaces/_abstract_interface.py`
  - `svg_to_gcode/compiler/interfaces/_gcode.py`
  - `svg_to_gcode/compiler/interfaces/_fan_controlled_gcode.py`
  - `svg_to_gcode/geometry/__init__.py`
  - `svg_to_gcode/geometry/_vector.py`
  - `svg_to_gcode/geometry/_matrix.py`
  - `svg_to_gcode/geometry/_abstract_curve.py`
  - `svg_to_gcode/geometry/_line.py`
  - `svg_to_gcode/geometry/_circular_arc.py`
  - `svg_to_gcode/geometry/_elliptical_arc.py`
  - `svg_to_gcode/geometry/_quadratic_bazier.py`
  - `svg_to_gcode/geometry/_cubic_bazier.py`
  - `svg_to_gcode/geometry/_abstract_chain.py`
  - `svg_to_gcode/geometry/_line_segment_chain.py`
  - `svg_to_gcode/geometry/_smooth_arc_chain.py`
  - `svg_to_gcode/svg_parser/__init__.py`
  - `svg_to_gcode/svg_parser/_parser_methods.py`
  - `svg_to_gcode/svg_parser/_path.py`
  - `svg_to_gcode/svg_parser/_transformation.py`
  - `svg_to_gcode/svg_parser/debug_methods.py`
- （その他、上記以外に存在する `.py` ファイルがあればすべて追加で調査）

## 報告書に必ず含めるべき構成

### 1. プロジェクト概要と End-to-End 実行フロー
- Inkscape 1.4.2 から `laser.inx` → `laser.py` が呼び出され、G-code ファイルおよびデバッグ SVG レイヤーが出力されるまでの一連の処理フロー。
- 使用ライブラリ（`inkex`, `lxml.etree`, `xml.etree.ElementTree`, Python 標準ライブラリ）とその使い分け。

### 2. モジュール間の依存関係マップ
- 各ファイル・パッケージが何を `import` し、どこから呼び出されているかの関係図（Mermaid またはテキストツリー）。

### 3. `laser.inx` UI パラメータと `laser.py` での対応一覧
- すべての `<param>` について、`name` / `type` / `gui-text` / デフォルト値 / `laser.py` 内の `self.options.<name>` での使用箇所を表形式でまとめること。
- `read_arguments()` がどのように `.inx` を動的にパースしているかの仕組みも説明すること。

### 4. 全ファイル・全クラス・全関数リファレンス
ファイルごとに以下のフォーマットで詳細に解説してください：
- **ファイルパスと役割（1〜2行）**
- **公開クラス・関数・定数一覧**（シグネチャ、引数の型と意味、戻り値、例外・警告）
- **内部ロジックの要点**（処理アルゴリズム、状態管理、副作用）
- **呼び出し元・呼び出し先（関係性）**

### 5. 座標系・単位変換・変換行列の詳細（重要）
- SVG 座標系（左上原点・Y下向き・`viewBox` / user units）から G-code 座標系（`bottom-left` / `center` / `top-left`、`invert_y_axis`、`mm` / `in`）への変換数式と行列乗算の順序。
- `laser.py` における `self.svg.unittouu()` を用いた単位変換の仕組み（`effect()`, `draw_debug_traces()`, `draw_unit_reference()` それぞれでの計算）。
- `Transformation` クラスの行列適用順序（`add_translation`, `add_scale`, `extend` 等が右掛けか左掛けか）。

### 6. 既知の制約・注意点・バグ候補（改良時の落とし穴）
- SVG 要素の対応範囲（`<path>` のみ、`<rect>` や `<text>` の扱い）。
- `Path._parse_commands` や `Transformation.add_rotation`、楕円弧の変換など、コード上の注意点や TODO。
- デバッグレイヤー（`debug_traces`, `debug_references`, `content layer`）の ID 管理と削除タイミング。

### 7. 使用方法・インストール・テスト検証手順
- Inkscape 1.4.2（Windows）の拡張機能ディレクトリへの配置方法。
- `test_samples/test_300x300.svg` を使った動作確認手順と期待結果。

## 出力先とフォーマット
- 調査結果はワークスペース直下に **`DETAILED_CODEBASE_SPECIFICATION.md`** として Markdown 形式で保存してください。
- 日本語で記述し、ファイルパス・クラス名・メソッド名・引数名・G-code コマンド等の技術識別子は正確な英語表記のままバッククォートで囲んでください。
```

