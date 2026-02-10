#!/usr/bin/env bash
# Render 빌드 스크립트
# KoNLPy를 위한 Java 설치 + Python 의존성

set -e

echo "=== Q Server 빌드 시작 ==="

# Java 설치 (KoNLPy 의존성)
echo ">> Java(JDK) 설치 중..."
apt-get update -qq && apt-get install -y -qq default-jdk > /dev/null 2>&1 || {
    echo "⚠️ apt-get Java 설치 실패 — kiwipiepy 폴백으로 진행"
}

# JAVA_HOME 설정
if command -v java &> /dev/null; then
    export JAVA_HOME=$(dirname $(dirname $(readlink -f $(which java))))
    echo ">> JAVA_HOME=$JAVA_HOME"
    echo "export JAVA_HOME=$JAVA_HOME" >> ~/.bashrc
else
    echo "⚠️ Java 없음 — kiwipiepy가 자동으로 사용됨"
fi

# Python 의존성 설치
echo ">> pip install 중..."
pip install --upgrade pip
pip install -r requirements.txt

echo "=== 빌드 완료 ==="
