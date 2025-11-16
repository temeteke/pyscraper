# 統合テスト (Integration Tests)

このディレクトリには、実際の外部依存を使用する統合テストが含まれています。

## 概要

統合テストは以下を使用します：
- **実際のHTTPエンドポイント**: httpbin.org、GitHub など
- **実際のFFmpeg**: HLS動画処理のテスト
- **ネットワーク接続**: インターネットアクセスが必要

## 実行方法

### 統合テストのみ実行

```bash
# マーカーを指定して実行
pytest tests/integration/ -m integration -v

# または環境変数で指定
INTEGRATION_TEST=1 pytest tests/integration/ -v
```

### すべてのテストから統合テストを除外

```bash
# モックテストのみ実行（デフォルトの動作）
pytest tests/ -m "not integration" -v
```

### すべてのテストを実行（モック + 統合）

```bash
# マーカーフィルタなしで実行
pytest tests/ -v --override-ini="addopts="
```

## 必要な環境

### ネットワーク
- インターネット接続が必要
- httpbin.org へのアクセスが可能である必要があります

### FFmpeg (HLS テスト用)
```bash
# Ubuntu/Debian
sudo apt-get install ffmpeg

# macOS
brew install ffmpeg

# 確認
ffmpeg -version
```

## テストの種類

### WebFile 統合テスト
- `test_webfile_integration.py`: 実際のHTTPリクエストを使用したWebFileのテスト

### HLSFile 統合テスト (未実装)
- `test_hlsfile_integration.py`: 実際のHLS動画ストリームのダウンロードとFFmpeg処理

## 注意事項

### テスト失敗の原因

統合テストは以下の理由で失敗する可能性があります：

1. **ネットワーク問題**
   - インターネット接続が不安定
   - httpbin.org がダウン
   - ファイアウォールが外部アクセスをブロック

2. **レート制限**
   - httpbin.org のレート制限に達した
   - GitHub API の制限に達した

3. **依存ソフトウェア**
   - FFmpeg がインストールされていない
   - FFmpeg のバージョンが古い

### 推奨される運用

- **ローカル開発**: モックテストのみ実行（高速フィードバック）
- **CI/CD**: Pull Request ではモックテストのみ、main マージ時に統合テスト
- **リリース前**: 必ず統合テストを実行して外部依存の互換性を確認

## CI/CD での使用例

### GitHub Actions

```yaml
name: Tests

on: [push, pull_request]

jobs:
  # 常に実行: モックテスト
  mock-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Run mock tests
        run: pytest tests/ -m "not integration" -v

  # mainブランチのみ: 統合テスト
  integration-tests:
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v3
      - name: Install FFmpeg
        run: sudo apt-get install -y ffmpeg
      - name: Run integration tests
        run: INTEGRATION_TEST=1 pytest tests/integration/ -m integration -v
```

## テストの追加

新しい統合テストを追加する場合：

1. **必ず `@pytest.mark.integration` デコレータを付ける**
   ```python
   @pytest.mark.integration
   def test_real_download():
       # テストコード
   ```

2. **クラスレベルでもマーカーを付ける**
   ```python
   @pytest.mark.integration
   class TestWebFileIntegration:
       @pytest.mark.integration
       def test_something(self):
           # テストコード
   ```

3. **タイムアウトを考慮する**
   - ネットワークI/Oは時間がかかる可能性があります
   - 適切なタイムアウト設定を行ってください

4. **クリーンアップを忘れずに**
   - ダウンロードしたファイルは削除
   - 作成したディレクトリは削除
   - `tmp_path` フィクスチャを活用

## トラブルシューティング

### httpbin.org に接続できない

```python
# 接続テストを実行
curl https://httpbin.org/get

# 失敗する場合は別のエンドポイントを検討
# または、テストをスキップ
```

### FFmpeg が見つからない

```bash
# インストール確認
which ffmpeg
ffmpeg -version

# PATH確認
echo $PATH
```

### タイムアウトエラー

ネットワークが遅い場合、タイムアウト値を増やす：

```python
wf = WebFile(url, timeout=60)  # 60秒に延長
```

## 参考

- [pytest markers documentation](https://docs.pytest.org/en/stable/example/markers.html)
- [httpbin.org documentation](https://httpbin.org/)
