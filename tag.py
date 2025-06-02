import re

# 내부 태그 저장소
tags = {}  # key: tag, value: content

def extract_nouns(text: str) -> list:
    """
    한글 텍스트에서 2글자 이상의 명사 후보를 추출 (정규식 기반)
    """
    if not text or not isinstance(text, str):
        return []

    # 한글 2자 이상 단어만 필터링
    return re.findall(r"[\uAC00-\uD7A3]{2,}", text)


def tag_store(content: str) -> str:
    """
    입력된 문장에서 중복되지 않는 새로운 태그를 추출 및 저장
    이미 저장된 태그가 모두 있다면 '기억'으로 대체
    """
    nouns = extract_nouns(content)

    for noun in nouns:
        if noun not in tags:
            tags[noun] = content
            return noun

    return "기억"  # fallback


def get_all_tags() -> list:
    """
    현재 저장된 태그 목록 반환
    """
    return list(tags.keys())


def get_tagged_content(tag: str) -> str:
    """
    특정 태그에 연결된 콘텐츠 반환
    """
    return tags.get(tag, "")


def reset_tags():
    """
    모든 태그 초기화
    """
    tags.clear()