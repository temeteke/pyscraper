# テスト実行クイックリファレンス

## 基本コマンド

```bash
# 📦 モックテスト（デフォルト・推奨）
pytest tests/                           # すべてのモックテスト
pytest tests/test_webfile.py           # 特定ファイル
pytest tests/ -k download              # キーワードフィルタ

# 🌐 統合テスト
pytest tests/integration/ -m integration          # 統合テストのみ
INTEGRATION_TEST=1 pytest tests/ -v               # 環境変数で制御

# 🔬 すべて実行
pytest tests/ -m ""                    # モック + 統合
```

## マーカー使用

```python
# テストファイル内でマーカーを使用

@pytest.mark.integration              # 統合テストとしてマーク
def test_real_http():
    # 実際のHTTPリクエスト
    ...

@pytest.mark.no_mock                  # すべてのモックを無効化
def test_without_mocking():
    ...
```

## 環境変数

```bash
# モックを無効化（統合テストとして実行）
INTEGRATION_TEST=1 pytest tests/

# 通常のモックテスト
INTEGRATION_TEST=0 pytest tests/  # または省略
```

## よく使うオプション

```bash
# 詳細出力
pytest tests/ -v                       # verbose
pytest tests/ -vv                      # more verbose

# カバレッジ
pytest tests/ --cov=pyscraper         # カバレッジ測定
pytest tests/ --cov=pyscraper --cov-report=html  # HTML レポート

# デバッグ
pytest tests/ -x                       # 最初の失敗で停止
pytest tests/ -s                       # 標準出力を表示
pytest tests/ --lf                     # 最後に失敗したテストのみ

# 並列実行
pytest tests/ -n auto                  # 自動並列化（要 pytest-xdist）
```

## シーン別使い分け

| シーン | コマンド | 実行時間 |
|--------|---------|---------|
| 日常開発 | `pytest tests/` | < 2秒 |
| コミット前 | `pytest tests/ -v` | < 2秒 |
| リリース前 | `pytest tests/ -m ""` | 数分 |
| CI/CD (PR) | `pytest tests/ -m "not integration"` | < 2秒 |
| CI/CD (main) | `INTEGRATION_TEST=1 pytest tests/` | 数分 |

## トラブルシューティング

```bash
# テスト収集を確認
pytest tests/ --collect-only

# マーカーを確認
pytest --markers

# フィクスチャを確認
pytest tests/ --fixtures | grep mock

# 遅いテストを特定
pytest tests/ --durations=10
```

## ドキュメント

- **[TEST_STRATEGY.md](./TEST_STRATEGY.md)** - 戦略的な概要と設計思想
- **[TESTING_GUIDE.md](./TESTING_GUIDE.md)** - 詳細な使い方ガイド
- **[tests/integration/README.md](./tests/integration/README.md)** - 統合テストの詳細
