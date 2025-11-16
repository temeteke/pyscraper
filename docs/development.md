# Development Guide

pyscraperプロジェクトの開発ガイドです。

## 🚀 セットアップ

### 開発環境の構築

```bash
# リポジトリのクローン
git clone https://github.com/temeteke/pyscraper.git
cd pyscraper

# 開発用依存関係のインストール
pip install -e ".[dev]"

# テスト実行
pytest tests/
```

### 推奨ツール

```bash
# コードフォーマッタ
pip install black isort

# リンター
pip install flake8 pylint

# 型チェック
pip install mypy
```

---

## 📁 プロジェクト構造

```
pyscraper/
├── pyscraper/          # ソースコード
│   ├── webpage.py      # Webページ処理（692行）
│   ├── webfile.py      # Webファイルダウンロード（423行）
│   ├── hlsfile.py      # HLSストリーム処理（249行）
│   ├── requests.py     # HTTPリクエストミックスイン
│   └── utils.py        # ユーティリティ
│
├── tests/              # テストコード
│   ├── conftest.py     # pytestフィクスチャ・モック
│   ├── test_webpage.py # WebPage関連テスト
│   ├── test_webfile.py # WebFile関連テスト（単体・結合）
│   ├── test_hlsfile.py # HLSFile関連テスト
│   └── test_utils.py   # ユーティリティテスト
│
├── docs/               # ドキュメント
│   ├── testing.md      # テストガイド
│   ├── development.md  # 開発ガイド（このファイル）
│   └── analysis/       # 詳細分析
│
└── pyproject.toml      # プロジェクト設定
```

**統計:**
- 総コード行数: 2,446行（7モジュール）
- 総メソッド数: 153
- テスト数: 218（単体114 + 結合104）

---

## 🧪 テスト駆動開発

### 開発フロー

```bash
# 1. 新機能用のテストを書く（tests/test_*.py）
# 2. テストが失敗することを確認
pytest tests/test_your_module.py::test_new_feature -v

# 3. 機能を実装
# 4. テストが成功することを確認
pytest tests/test_your_module.py::test_new_feature -v

# 5. すべての単体テストを実行
pytest tests/ -v

# 6. 必要に応じて結合テストを追加・実行
pytest tests/ -m integration -v
```

### テスト作成ガイドライン

#### 単体テスト（推奨）

```python
# tests/test_your_module.py

def test_download_file():
    """ファイルダウンロード機能のテスト"""
    # マーカー不要
    # 外部HTTP依存は自動的にモック化される

    wf = WebFile("https://example.com/file.txt")
    with wf as f:
        content = f.read()
        assert len(content) > 0
```

#### 結合テスト（必要な場合のみ）

```python
# tests/test_your_module.py

@pytest.mark.integration
def test_download_real_file():
    """実際のHTTP通信でファイルダウンロードをテスト"""
    # 実際のネットワークアクセスが発生

    wf = WebFile("https://httpbin.org/bytes/1024")
    with wf as f:
        content = f.read()
        assert len(content) == 1024
```

---

## 🔧 コーディング規約

### Pythonスタイル

```python
# PEP 8に従う
# インデント: スペース4つ
# 行の長さ: 最大100文字（推奨）

# クラス名: PascalCase
class WebPageRequests:
    pass

# 関数名・変数名: snake_case
def download_file(url, filename):
    file_path = Path(filename)
    ...

# 定数: UPPER_CASE
DEFAULT_TIMEOUT = 10
MAX_RETRIES = 3
```

### Docstring

```python
def download_file(url: str, directory: Path) -> Path:
    """指定URLからファイルをダウンロードする。

    Args:
        url: ダウンロード元URL
        directory: 保存先ディレクトリ

    Returns:
        ダウンロードしたファイルのパス

    Raises:
        WebFileError: ダウンロード失敗時
    """
    ...
```

---

## 📊 最近の改善履歴

### テストインフラの整備（2024年）

#### 1. pytestへの統一
**以前:** unittest と pytest が混在
**改善:** すべてのテストを pytest に統一

**効果:**
- ✅ フィクスチャの活用
- ✅ パラメータ化テストの簡素化
- ✅ プラグインエコシステムの活用

#### 2. HTTP通信のモック化
**以前:** 全テストで実際のHTTP通信を実行（遅い、不安定）
**改善:** 単体テストではHTTP通信を完全モック化

**実装:**
```python
# tests/conftest.py

@pytest.fixture(autouse=True)
def mock_external_http(request, mocker):
    """外部HTTPを自動的にモック化"""
    if 'integration' in request.keywords:
        yield  # 結合テストではモックをスキップ
        return

    # requests.Session.get をモック
    mocker.patch('requests.Session.get', side_effect=mock_get)
```

**効果:**
- ✅ テスト実行時間: 数分 → 1.2秒（99%削減）
- ✅ オフライン実行可能
- ✅ 再現性100%

#### 3. テストの分類体系化
**以前:** すべてのテストがデフォルト実行（遅い）
**改善:** 単体テストと結合テストを明確に分離

**実装:**
```python
# pyproject.toml

[tool.pytest.ini_options]
markers = [
    "integration: Integration tests (HTTP, Curl, Browser)",
]
addopts = "-m 'not integration'"
```

**効果:**
- ✅ デフォルト実行: 単体テストのみ（114テスト、1.2秒）
- ✅ 明示的実行: 結合テスト（104テスト、数分）
- ✅ CI/CDコスト削減

#### 4. FFmpegのモック化
**以前:** 実際の ffmpeg コマンドを実行（遅い、環境依存）
**改善:** subprocess.run をモック化

**実装:**
```python
# tests/conftest.py

class MockFFmpeg:
    """Mock FFmpeg that creates output files without running ffmpeg."""
    def run(self, *args, **kwargs):
        # 出力ファイルを作成（実際のffmpegは実行しない）
        if self.outputs:
            output_file = list(self.outputs.keys())[0]
            Path(output_file).write_bytes(b'mock ffmpeg output')
```

**効果:**
- ✅ HLSテスト: 数分 → 1秒未満
- ✅ ffmpeg インストール不要（単体テスト）

#### 5. WebPageCurlの結合テスト化
**以前:** subprocess.run(['curl', ...]) をモック（本質的な検証ができない）
**改善:** 結合テストに移行、実際のcurlコマンドを実行

**実装:**
```python
# tests/test_webpage.py

@pytest.mark.integration
class TestWebPageCurl(MixinTestWebPage):
    """Integration tests for WebPageCurl using actual curl command."""
```

**効果:**
- ✅ 実際のcurl動作を検証可能
- ✅ 単体テストから除外（高速化）
- ✅ 環境依存テストとして明確化

---

## 🏗️ アーキテクチャ

### 主要クラスの責務

#### WebPage系
```
WebPage (抽象基底クラス)
├── WebPageRequests   # requests ライブラリを使用
├── WebPageCurl       # curl コマンドを使用
└── WebPageSelenium   # Selenium を使用
    ├── WebPageFirefox
    └── WebPageChrome
```

**責務:**
- URLからHTMLを取得
- HTMLのパース（lxml）
- XPath/CSSセレクタによる要素取得

#### WebFile
```
WebFile
├── RequestsMixin     # HTTPセッション管理
└── HLSFile          # HLS専用拡張
```

**責務:**
- ファイルのダウンロード
- Range リクエスト対応
- プログレスコールバック
- HLSストリームの処理（HLSFile）

---

## 🔍 既知の技術的課題

### リファクタリング候補

#### 1. 状態検証の共通化 [優先度: 高]
**問題:** `if self.driver is None:` のような状態チェックが28箇所以上

**提案:**
```python
def _ensure_open(self):
    """Ensure driver is opened."""
    if self.driver is None:
        raise WebPageError("Driver is not opened yet")

# 使用例
@property
def html(self):
    self._ensure_open()
    return self.driver.page_source
```

**効果:** ~50行のボイラープレート削除

#### 2. Selenium ドライバークラスの統合 [優先度: 中]
**問題:** `WebPageFirefox` と `WebPageChrome` が95%同じコード

**提案:**
```python
class WebPageSelenium:
    def __init__(self, url, driver_type='firefox', ...):
        self.driver_type = driver_type

    def _create_driver(self):
        if self.driver_type == 'firefox':
            return self._create_firefox_driver()
        elif self.driver_type == 'chrome':
            return self._create_chrome_driver()
```

**効果:** ~40-50行の重複削除

#### 3. キャッシュ無効化の簡素化 [優先度: 高]
**問題:** `hlsfile.py` の `clear_cache()` で同じtry/exceptブロックが5回繰り返し

**現状:**
```python
try:
    del self.m3u8_obj
except AttributeError:
    pass
# ... 4回繰り返し
```

**提案:**
```python
for prop_name in ['m3u8_obj', 'm3u8_content', 'web_files', 'filestem', 'filesuffix']:
    try:
        delattr(self, prop_name)
    except AttributeError:
        pass
```

**効果:** ~10行の削除、保守性向上

---

## 🚀 コントリビューション

### プルリクエストの流れ

1. **Issueの作成または確認**
2. **ブランチの作成**
   ```bash
   git checkout -b feature/your-feature
   ```

3. **開発**
   - コードを書く
   - テストを書く
   - 単体テストを実行

4. **コミット**
   ```bash
   pytest tests/ -v
   git add -A
   git commit -m "Add your feature"
   ```

5. **プッシュ**
   ```bash
   git push origin feature/your-feature
   ```

6. **プルリクエスト作成**
   - GitHub上でPRを作成
   - CI/CDが単体テストを実行
   - レビュー待ち

7. **マージ後**
   - main ブランチで結合テストが実行される

---

## 📚 参考資料

### 外部ドキュメント
- [pytest](https://docs.pytest.org/)
- [requests](https://requests.readthedocs.io/)
- [lxml](https://lxml.de/)
- [Selenium](https://selenium-python.readthedocs.io/)
- [ffmpy](https://github.com/Ch00k/ffmpy)

### プロジェクト内ドキュメント
- [testing.md](./testing.md) - テストガイド
- [analysis/codebase.md](./analysis/codebase.md) - コードベース分析
- [analysis/modules.md](./analysis/modules.md) - モジュール構造
