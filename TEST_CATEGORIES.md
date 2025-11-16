# テストカテゴリの整理と実行戦略

## 現状の問題点

### 1. カテゴリ分けが曖昧
- **統合テスト**: 明示的なマーカー（`@pytest.mark.integration`）で管理
- **Seleniumテスト**: キーワードフィルタ（`-k "not (Firefox or Chrome or Selenium)"`）で除外
- 両者の違いが不明確

### 2. 本質的な共通点
統合テストとSeleniumテストは、実は本質的に同じカテゴリです：

| 特徴 | 統合テスト | Seleniumテスト | 共通点 |
|------|-----------|---------------|-------|
| 外部依存 | HTTP, FFmpeg | ブラウザ, Selenium | ✅ あり |
| 実行速度 | 遅い（数秒〜数分） | 非常に遅い（数分） | ✅ 遅い |
| 環境要件 | ネットワーク, FFmpeg | ブラウザ, ドライバー | ✅ 特殊環境 |
| CI/CD | デフォルトではスキップ | デフォルトではスキップ | ✅ スキップ |
| 実行タイミング | mainマージ時、週次 | リリース前のみ | ✅ 選択的実行 |

**結論: 両者とも「実環境依存テスト」であり、デフォルトでは実行しない**

---

## 📋 推奨：明確なテストカテゴリ分類

### レベル1: ユニット/モックテスト（デフォルト）

**特徴:**
- ✅ 外部依存なし（完全モック化）
- ✅ 高速（< 2秒）
- ✅ オフライン実行可能
- ✅ 再現性100%

**マーカー:** なし（デフォルト）

**実行:**
```bash
pytest tests/
```

**対象:**
- WebFile（モック）
- HLSFile（モック）
- Utils
- WebPage (Requests, Curl)

**実行タイミング:** すべてのコミット、Pull Request

---

### レベル2: 統合テスト（HTTP/FFmpeg）

**特徴:**
- ⚠️ 外部HTTP依存（httpbin.org, GitHub）
- ⚠️ FFmpeg依存（HLS処理）
- ⚠️ 中速（数秒〜数分）
- ⚠️ ネットワーク接続必須

**マーカー:** `@pytest.mark.integration`

**実行:**
```bash
# マーカー指定
pytest tests/integration/ -m integration -v

# 環境変数
INTEGRATION_TEST=1 pytest tests/ -v
```

**対象:**
- WebFile（実HTTP）
- HLSFile（実FFmpeg）
- 外部API互換性

**実行タイミング:** mainマージ時、週次定期実行

---

### レベル3: E2Eテスト（ブラウザ）

**特徴:**
- ⚠️ ブラウザ依存（Firefox, Chrome）
- ⚠️ Selenium/WebDriver必須
- ⚠️ 非常に遅い（数分〜数十分）
- ⚠️ GUI環境必須

**マーカー:** `@pytest.mark.browser` （提案）

**実行:**
```bash
# 現状（提案前）
pytest tests/ -k "Firefox or Chrome or Selenium" -v

# 提案後
pytest tests/ -m browser -v
```

**対象:**
- WebPageFirefox
- WebPageChrome
- ブラウザ自動化

**実行タイミング:** リリース前のみ、手動実行

---

## 🎯 改善提案：明示的なマーカー戦略

### 現状の問題
```python
# 現在：Seleniumテストに明示的なマーカーがない
class TestWebPageFirefox:
    def test_something(self):  # マーカーなし
        ...

# 除外方法：キーワードフィルタに依存
pytest tests/ -k "not (Firefox or Chrome or Selenium)"
```

### 改善案：明示的なマーカー
```python
# 提案：@pytest.mark.browser を追加
@pytest.mark.browser
class TestWebPageFirefox:
    @pytest.mark.browser
    def test_something(self):
        ...

# 除外方法：マーカーで明示的に制御
pytest tests/ -m "not browser"
```

---

## 📊 推奨：実行戦略マトリックス

| 環境/タイミング | ユニット/モック | 統合（HTTP/FFmpeg） | E2E（ブラウザ） |
|---------------|---------------|-------------------|---------------|
| **ローカル開発** | ✅ 常時実行 | ⚠️ 必要時のみ | ❌ 実行しない |
| **コミット前** | ✅ 必須 | ❌ スキップ | ❌ スキップ |
| **Pull Request** | ✅ 必須 | ❌ スキップ | ❌ スキップ |
| **mainマージ** | ✅ 実行 | ✅ 実行 | ❌ スキップ |
| **週次定期実行** | ✅ 実行 | ✅ 実行 | ⚠️ 実行（推奨） |
| **リリース前** | ✅ 必須 | ✅ 必須 | ✅ 必須 |

---

## 🔧 実装方針

### ステップ1: マーカー定義の追加

**pyproject.toml に追加:**
```toml
[tool.pytest.ini_options]
markers = [
    "integration: Integration tests using real HTTP/FFmpeg dependencies",
    "browser: Browser automation tests using Selenium (Firefox/Chrome)",
    "slow: Tests that take a long time to run",
    "no_mock: Skip all automatic mocking for this test",
    "no_mock_http: Skip HTTP mocking only",
    "no_mock_ffmpeg: Skip FFmpeg mocking only",
]

# デフォルトではブラウザテストを除外
addopts = "-m 'not browser'"
```

### ステップ2: Seleniumテストにマーカー追加

**tests/test_webpage.py を修正:**
```python
import pytest

@pytest.mark.browser
@pytest.mark.slow
class TestWebPageFirefox(MixinTestWebPage, ...):
    """Firefox browser automation tests."""

    @pytest.mark.browser
    def test_something(self):
        ...

@pytest.mark.browser
@pytest.mark.slow
class TestWebPageChrome(MixinTestWebPage, ...):
    """Chrome browser automation tests."""

    @pytest.mark.browser
    def test_something(self):
        ...
```

### ステップ3: 統合テストディレクトリの再編成

```
tests/
├── unit/                       # モックテスト（または tests/ 直下）
│   ├── test_webfile.py
│   ├── test_hlsfile.py
│   └── test_utils.py
│
├── integration/                # 統合テスト（HTTP/FFmpeg）
│   ├── test_webfile_integration.py
│   └── test_hlsfile_integration.py   # 将来追加
│
└── browser/                    # E2Eテスト（ブラウザ）
    └── test_webpage_browser.py        # 既存のSeleniumテスト
```

**または、既存構造を維持してマーカーのみ追加:**
```
tests/
├── test_webfile.py            # @pytest.mark なし（デフォルト：モック）
├── test_hlsfile.py            # @pytest.mark なし（デフォルト：モック）
├── test_webpage.py            # 一部 @pytest.mark.browser 付き
│
└── integration/
    └── test_webfile_integration.py  # @pytest.mark.integration 付き
```

---

## 💻 実行コマンド例

### 開発時（モックのみ）
```bash
# デフォルト：モックテストのみ実行、ブラウザテストは除外
pytest tests/

# 明示的に指定
pytest tests/ -m "not (browser or integration)"
```

### 統合テスト含む
```bash
# 統合テストのみ
pytest tests/ -m integration -v

# モック + 統合（ブラウザ除外）
pytest tests/ -m "not browser" -v
```

### すべて実行
```bash
# すべてのテスト（モック + 統合 + ブラウザ）
pytest tests/ -m "" -v

# または
pytest tests/ --override-ini="addopts=" -v
```

### ブラウザテストのみ
```bash
# ブラウザテストのみ実行
pytest tests/ -m browser -v

# 特定のブラウザ
pytest tests/ -k Firefox -v
pytest tests/ -k Chrome -v
```

---

## 📝 pyproject.toml 設定例

### オプション1: ブラウザテストをデフォルトで除外（推奨）
```toml
[tool.pytest.ini_options]
markers = [
    "integration: Integration tests using real HTTP/FFmpeg dependencies",
    "browser: Browser automation tests using Selenium",
    "slow: Tests that take a long time to run",
]

# デフォルトではブラウザテストを除外
addopts = "-m 'not browser'"
```

### オプション2: 統合テストとブラウザテストの両方を除外
```toml
[tool.pytest.ini_options]
markers = [
    "integration: Integration tests using real HTTP/FFmpeg dependencies",
    "browser: Browser automation tests using Selenium",
    "slow: Tests that take a long time to run",
]

# デフォルトではモックテストのみ実行
addopts = "-m 'not (browser or integration)'"
```

### オプション3: カスタムマーカーで柔軟に制御
```toml
[tool.pytest.ini_options]
markers = [
    "unit: Unit tests with mocks (default)",
    "integration: Integration tests using real HTTP/FFmpeg",
    "browser: Browser automation tests using Selenium",
    "slow: Tests that take a long time",
    "requires_network: Tests requiring internet connection",
    "requires_ffmpeg: Tests requiring FFmpeg",
    "requires_browser: Tests requiring browser installation",
]

# デフォルトではユニットテストのみ
addopts = "-m 'not (browser or integration)'"
```

---

## 🎯 まとめ

### 現状の本質
**統合テストとSeleniumテストは本質的に同じカテゴリ:**
- どちらも「実環境依存テスト」
- デフォルトCIでは実行したくない
- 選択的に実行する必要がある

### 違いは「依存の種類」のみ
- **統合テスト**: HTTP/FFmpeg依存、サーバー側の検証
- **Seleniumテスト**: ブラウザ依存、クライアント側のE2E検証

### 推奨アプローチ
1. **明示的なマーカー戦略**
   - `@pytest.mark.integration` - HTTP/FFmpeg依存
   - `@pytest.mark.browser` - ブラウザ依存
   - キーワードフィルタではなくマーカーで制御

2. **デフォルト動作の明確化**
   - `pytest tests/` = モックテストのみ
   - `pytest tests/ -m integration` = 統合テストのみ
   - `pytest tests/ -m browser` = ブラウザテストのみ
   - `pytest tests/ -m ""` = すべて

3. **段階的な実行戦略**
   - レベル1（常時）: モックテスト
   - レベル2（定期）: モック + 統合
   - レベル3（リリース前）: すべて（モック + 統合 + ブラウザ）

この整理により、テスト実行が明確で予測可能になります。
