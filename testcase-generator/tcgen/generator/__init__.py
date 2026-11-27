"""테스트 케이스 생성 모듈 (규칙 기반).

generate(results, ctx_opts) : 분석 결과(Fact) → 테스트 케이스 초안 목록
merge_cases(existing, generated) : 재분석 시 개발자 수정 내용을 보존하며 병합
"""
from .engine import generate, CATEGORIES, STATUSES, PRIORITIES
from .merge import merge_cases, next_test_id

__all__ = ["generate", "merge_cases", "next_test_id", "CATEGORIES", "STATUSES", "PRIORITIES"]
