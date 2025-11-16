# テスト実行ガイド

このガイドでは、pyscraperプロジェクトのテストを実行する方法を説明します。

## クイックスタート

```bash
# デフォルト: モックテストのみ実行（推奨）
pytest tests/

# すべてのテスト（モック + 統合）を実行
pytest tests/ -m ""

# 統合テストのみ実行
pytest tests/integration/ -m integration

# 特定のテストファイルを実行
pytest tests/test_webfile.py -v
```

## テストモードの選択

### 1. モックテスト（デフォルト）

**特徴:**
- ✅ 高速実行（< 2秒）
- ✅ オフライン実行可能
- ✅ 外部依存なし
- ✅ 再現性が高い

**実行方法:**
```bash
# 方法1: デフォルトで実行
pytest tests/

# 方法2: 明示的に統合テストを除外
pytest tests/ -m "not integration"

# 方法3: 環境変数で制御
INTEGRATION_TEST=0 pytest tests/
```

**使用シーン:**
- 日常的な開発作業
- TDD（テスト駆動開発）
- CI/CDの高速フィードバック
- リファクタリング時の安全確認

### 2. 統合テスト

**特徴:**
- ⚠️ 実行に時間がかかる（数分）
- ⚠️ インターネット接続が必要
- ⚠️ 外部サービスに依存（httpbin.org、GitHub）
- ✅ 本番環境に近い検証

**実行方法:**
```bash
# 方法1: マーカー指定
pytest tests/integration/ -m integration -v

# 方法2: 環境変数で制御
INTEGRATION_TEST=1 pytest tests/ -v

# 方法3: 特定の統合テストのみ
pytest tests/integration/test_webfile_integration.py -v
```

**使用シーン:**
- リリース前の最終確認
- 外部API変更の検出
- FFmpeg互換性の確認
- 週次/月次の定期実行

### 3. 特定のモックを無効化

```python
# テストコードで個別に制御
@pytest.mark.no_mock  # すべてのモックを無効化
def test_something():
    ...

@pytest.mark.no_mock_http  # HTTPモックのみ無効化
def test_real_http():
    ...

@pytest.mark.no_mock_ffmpeg  # FFmpegモックのみ無効化
def test_real_ffmpeg():
    ...
```

## テスト実行の例

### 開発中の典型的なワークフロー

```bash
# 1. 機能開発中: 関連するテストのみ高速実行
pytest tests/test_webfile.py::TestWebFile::test_download_unlink -v

# 2. 複数ファイル修正後: 関連テストをまとめて実行
pytest tests/test_webfile.py tests/test_hlsfile.py -v

# 3. コミット前: すべてのモックテストを実行
pytest tests/ -v

# 4. リリース前: 統合テストも含めてすべて実行
pytest tests/ -m "" -v
```

### カバレッジ測定

```bash
# モックテストでカバレッジ測定
pytest tests/ --cov=pyscraper --cov-report=html

# 結果を表示
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
```

### 並列実行（高速化）

```bash
# pytest-xdist を使用した並列実行
pip install pytest-xdist

# 4プロセスで並列実行
pytest tests/ -n 4

# 自動でCPUコア数を検出
pytest tests/ -n auto
```

### デバッグモード

```bash
# 詳細出力
pytest tests/ -vv

# 標準出力を表示
pytest tests/ -s

# 最初の失敗で停止
pytest tests/ -x

# 最後に失敗したテストのみ再実行
pytest tests/ --lf

# スタックトレース省略
pytest tests/ --tb=short
```

## CI/CD での使用

### GitHub Actions 例

```yaml
# .github/workflows/test.yml
name: Tests

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main ]

jobs:
  # すべてのPRで実行: 高速なモックテスト
  mock-tests:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.9', '3.10', '3.11']

    steps:
    - uses: actions/checkout@v3

    - name: Set up Python ${{ matrix.python-version }}
      uses: actions/setup-python@v4
      with:
        python-version: ${{ matrix.python-version }}

    - name: Install dependencies
      run: |
        pip install -e ".[dev]"

    - name: Run mock tests
      run: |
        pytest tests/ -m "not integration" -v --cov=pyscraper

    - name: Upload coverage
      uses: codecov/codecov-action@v3

  # mainブランチのマージ時のみ実行: 統合テスト
  integration-tests:
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'

    steps:
    - uses: actions/checkout@v3

    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.11'

    - name: Install FFmpeg
      run: |
        sudo apt-get update
        sudo apt-get install -y ffmpeg

    - name: Install dependencies
      run: |
        pip install -e ".[dev]"

    - name: Run integration tests
      run: |
        INTEGRATION_TEST=1 pytest tests/integration/ -m integration -v
      env:
        PYTEST_TIMEOUT: 600
```

## トラブルシューティング

### テストが見つからない

```bash
# pytest の検出設定を確認
pytest --collect-only

# 特定のディレクトリを指定
pytest tests/ --collect-only

# パターンでフィルタ
pytest tests/ -k "download" --collect-only
```

### モックが効かない

```python
# conftest.py でモックが定義されているか確認
pytest tests/ --fixtures | grep mock

# テストにマーカーが付いていないか確認
pytest tests/ --markers

# 環境変数を確認
echo $INTEGRATION_TEST
```

### 統合テストが失敗する

```bash
# ネットワーク接続を確認
curl https://httpbin.org/get

# FFmpeg を確認
ffmpeg -version

# タイムアウトを延長
pytest tests/integration/ -m integration -v --timeout=300
```

### パフォーマンス問題

```bash
# 最も遅いテストを特定
pytest tests/ --durations=10

# 並列実行で高速化
pytest tests/ -n auto

# 特定のテストをスキップ
pytest tests/ -m "not slow"
```

## ベストプラクティス

### 1. 開発時はモックテスト中心

```bash
# 開発中は常にモックテストで高速フィードバック
pytest tests/ -v

# 機能が完成したら統合テストも確認
pytest tests/integration/test_webfile_integration.py -m integration
```

### 2. コミット前チェック

```bash
# コミット前に必ず実行
pytest tests/ -v && echo "✅ All tests passed"
```

### 3. リリース前の完全チェック

```bash
# すべてのテスト + カバレッジ
pytest tests/ -m "" --cov=pyscraper --cov-report=term-missing

# 統合テストを明示的に実行
INTEGRATION_TEST=1 pytest tests/integration/ -m integration -v
```

### 4. 新しいテストの追加

```python
# モックテスト（tests/test_*.py）
def test_new_feature():
    """新機能のテスト（モック使用）"""
    # 通常のテストコード
    ...

# 統合テスト（tests/integration/test_*_integration.py）
@pytest.mark.integration
def test_new_feature_integration():
    """新機能の統合テスト（実際のHTTP）"""
    # 実際の外部依存を使用
    ...
```

## 参考リンク

- [pytest 公式ドキュメント](https://docs.pytest.org/)
- [pytest-cov プラグイン](https://pytest-cov.readthedocs.io/)
- [pytest-xdist プラグイン](https://pytest-xdist.readthedocs.io/)
- [TEST_STRATEGY.md](./TEST_STRATEGY.md) - 詳細なテスト戦略
- [tests/integration/README.md](./tests/integration/README.md) - 統合テストの詳細
