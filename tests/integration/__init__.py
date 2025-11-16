"""Integration tests using real external dependencies.

These tests require:
- Network access to httpbin.org and GitHub
- FFmpeg installed for HLS tests
- Longer timeouts

Run with: pytest tests/integration/ -m integration
"""
