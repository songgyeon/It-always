#!/usr/bin/env bash
# Render 빌드 스크립트 (v2 — 정리됨)
set -e
echo "=== Q Server 빌드 시작 ==="

# Python 의존성 설치
echo ">> pip install 중..."
pip install --upgrade pip
pip install -r requirements.txt

echo "=== 빌드 완료 ==="
