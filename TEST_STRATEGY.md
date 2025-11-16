# テスト戦略: モックテスト vs 統合テスト

## 概要

このプロジェクトでは、2つのテスト実行モードを提供します：

1. **モックテスト（デフォルト）**: 外部依存をモック化し、高速でオフライン実行可能
2. **統合テスト**: 実際のHTTPエンドポイントとFFmpegを使用し、本番環境に近い検証を実施

## テストモードの比較

| 観点 | モックテスト | 統合テスト |
|------|-------------|-----------|
| **実行速度** | 非常に高速（< 2秒） | 遅い（数分） |
| **外部依存** | なし（完全オフライン可） | あり（httpbin.org, GitHub, FFmpeg必須） |
| **信頼性** | 高い（ネットワーク障害の影響なし） | 中程度（外部サービスに依存） |
| **用途** | CI/CD、ローカル開発、TDD | リリース前検証、本番環境互換性確認 |
| **検証範囲** | ロジック、エラーハンドリング | 実際のHTTPレスポンス、FFmpeg互換性 |

## 実装方針

### 1. pytest マーカーによる分類

#### モックテスト（デフォルト）
```python
@pytest.fixture(autouse=True)
def mock_external_http(request, mocker, ...):
    """外部HTTPをモック化（デフォルト有効）"""
    # integration テストマーカーがある場合はモックをスキップ
    if 'integration' in request.keywords:
        yield
        return

    # 通常はモック適用
    # ... モック実装 ...
```

#### 統合テスト
```python
@pytest.mark.integration
def test_real_download():
    """実際のHTTPリクエストでダウンロードテスト"""
    # モックなしで実行
    ...
```

### 2. 環境変数による制御

```bash
# モックテスト（デフォルト）
pytest tests/

# 統合テストのみ実行
INTEGRATION_TEST=1 pytest tests/ -m integration

# 統合テストを除外
pytest tests/ -m "not integration"

# すべて実行（モック + 統合）
pytest tests/ --run-integration
```

### 3. テストファイル構成

```
tests/
├── conftest.py                    # モック定義（autouse）
├── test_webfile.py                # 主にモックで実行
├── test_hlsfile.py                # 主にモックで実行
├── test_integration/              # 統合テスト専用ディレクトリ
│   ├── conftest.py                # 統合テスト用の設定
│   ├── test_webfile_integration.py
│   └── test_hlsfile_integration.py
└── pytest.ini or pyproject.toml   # マーカー定義
```

## 実装ステップ

### ステップ1: マーカー定義

**pyproject.toml** に追加：
```toml
[tool.pytest.ini_options]
markers = [
    "integration: Integration tests that use real external dependencies",
    "no_mock: Skip all automatic mocking for this test",
]
```

### ステップ2: モックフィクスチャの条件分岐

**tests/conftest.py** を修正：
```python
@pytest.fixture(autouse=True)
def mock_external_http(request, mocker, ...):
    """外部HTTPをモック化（統合テストでは無効化）"""
    # 統合テストマーカーまたは環境変数でスキップ
    if ('integration' in request.keywords or
        'no_mock' in request.keywords or
        os.getenv('INTEGRATION_TEST') == '1'):
        yield
        return

    # モック実装...
```

同様に：
- `mock_ffmpeg` フィクスチャ
- `mock_useragent` フィクスチャ

### ステップ3: 統合テスト用のテストコピー作成

既存のテストケースを統合テスト用にコピー：

**tests/test_integration/test_webfile_integration.py**:
```python
import pytest
from pyscraper.webfile import WebFile

@pytest.mark.integration
class TestWebFileIntegration:
    """実際のHTTPエンドポイントを使用した統合テスト"""

    @pytest.mark.integration
    def test_download_real_http(self):
        """実際のhttpbin.orgからダウンロード"""
        url = "https://httpbin.org/bytes/1024"
        wf = WebFile(url)
        with wf as f:
            content = f.read()
            assert len(content) == 1024

    @pytest.mark.integration
    def test_range_request_real(self):
        """実際のRangeリクエスト"""
        url = "https://httpbin.org/range/1024"
        wf = WebFile(url)
        wf.download()
        # ...
```

### ステップ4: CI/CD での使い分け

**GitHub Actions ワークフロー例**:
```yaml
name: Tests

on: [push, pull_request]

jobs:
  # 高速モックテスト（すべてのコミットで実行）
  mock-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: pip install -e ".[dev]"
      - name: Run mock tests
        run: pytest tests/ -m "not integration" -v

  # 統合テスト（mainブランチのみ、または週次）
  integration-tests:
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main' || github.event_name == 'schedule'
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          pip install -e ".[dev]"
          sudo apt-get install ffmpeg
      - name: Run integration tests
        run: INTEGRATION_TEST=1 pytest tests/ -m integration -v
        env:
          # タイムアウトを長めに設定
          PYTEST_TIMEOUT: 600
```

## 推奨運用フロー

### ローカル開発時
```bash
# 通常の開発: モックテスト（高速）
pytest tests/

# リファクタリング時: モックテスト + カバレッジ
pytest tests/ --cov=pyscraper --cov-report=html

# リリース前: 統合テストも実行
pytest tests/ --run-integration
```

### CI/CD
- **Pull Request**: モックテストのみ（高速フィードバック）
- **main ブランチマージ**: モック + 統合テスト
- **リリースタグ**: 完全な統合テスト

### トラブルシューティング
- **モックテストが失敗**: ロジックの問題（すぐ修正）
- **統合テストのみ失敗**: 外部API変更、ネットワーク問題（調査が必要）

## モック vs 実装のテストカバレッジ

### モックで十分なケース
- ✅ エラーハンドリング（HTTPステータスコード、タイムアウト）
- ✅ ビジネスロジック（ファイル名生成、パス処理）
- ✅ Rangeリクエストの処理
- ✅ リダイレクトハンドリング
- ✅ キャッシュロジック

### 統合テストが必要なケース
- ⚠️ 実際のHTTPレスポンスヘッダーの互換性
- ⚠️ FFmpegのバージョン互換性
- ⚠️ 大容量ファイルのダウンロード
- ⚠️ 外部サービスのAPI変更検出
- ⚠️ 実際のHLS動画ストリームの処理

## メンテナンス方針

1. **モックテストを優先**: 新機能は必ずモックテストで検証
2. **統合テストは選択的**: クリティカルなパスのみ統合テスト作成
3. **定期的な統合テスト実行**: 週次または月次で外部依存の互換性確認
4. **モックの更新**: 実際のAPIレスポンスが変わった場合、モックも更新

## まとめ

この2層テスト戦略により：
- ✅ **開発速度向上**: 高速なモックテストでTDDが可能
- ✅ **品質保証**: 統合テストで本番環境との互換性を確認
- ✅ **柔軟性**: 環境に応じてテストレベルを選択可能
- ✅ **CI/CDコスト削減**: 頻繁な実行はモックテスト、重要なタイミングのみ統合テスト

最初はモックテストを充実させ、リリースサイクルが安定してから統合テストを段階的に追加することを推奨します。
