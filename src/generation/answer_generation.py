# ============================================
# answer_generation.py
# RFP 질문에 대해 문서 힌트 추출 -> 조건 필터링 -> 컨텍스트 구성 -> LLM 답변 생성까지
# 담당하는 최종 답변 생성 파이프라인
#
# 개발 히스토리:
# - extract_doc_hints_multi (v1): 기관명/사업명/파일명 유사도 매칭 3단계로
#   문서 힌트를 찾고, 같은 발주기관에 문서가 여러 개면 질문 키워드와 파일명을
#   정확 매칭해서 하나를 선택
# - extract_doc_hints_multi_v2: 같은 발주기관 내 문서 선택 단계에서, 질문에
#   포함된 발주기관명이나 "용역은/사업은" 같은 흔한 조사형 단어가 모든 후보
#   문서에 동일하게 매칭되면서 노이즈로 작용해 정답 판별 신호(예: "운행기록"
#   ↔ 파일명의 "운행정보기록")가 묻히는 문제 발견. 해당 단어들을 stopwords에
#   추가하고, 조사를 뗀 뒤 부분 문자열로 매칭하도록 완화해 해결.ls -la
# - ask_rfp_v9: keyword_chunks만 쓰던 기존 로직에, 질문이 여러 항목을
#   물을 때 법률 키워드에 안 걸리는 항목이 통째로 누락되는 문제를 발견해
#   문서 앞쪽 청크(사업개요/범위가 보통 위치)를 함께 포함하도록 개선
# ============================================

import re

from src.generation.generation_prompts import (
    METADATA_DISTINCTION_INSTRUCTION,
    SYSTEM_PROMPT_V9,
    needs_metadata_distinction,
)

# ============================================
# 기관명 별칭 / 흔한 단어 블랙리스트 / 법률 키워드 맵
# ============================================
ORG_ALIAS_MAP = {
    "대검찰청": ["검찰"],
    "고려대학교": ["고려대"],
    "한국산업단지공단": ["산단"],
    "그랜드코리아레저": ["GKL"],
}

COMMON_SUFFIX_WORDS = {
    "박물관",
    "시스템",
    "센터",
    "공단",
    "진흥원",
    "협회",
    "재단",
    "연구원",
    "공사",
    "대학교",
    "사업",
    "관리",
    "운영",
    "구축",
    "개선",
    "개발",
    "지원",
    "정보",
    "용역",
    "기관",
    "기술",
    "고도화",
    "확대",
    "기능",
    "서비스",
    "일자리",
    "플랫폼",
    "통합",
    "접수",
    "일자리재단",
    "일자리플랫폼",
    "보험",
    "입찰공고",
    "공고",
    "과학연구",
    "과학연",
    "학연구",
    "연구소",
    "기록관리",
    "경기기록",
    "학교",
    "학교 ",
    " 학교",
    "산학협력단",
    "산학협력",
    "학협력단",
    "통합시스템",
    "2024년",
    "2025년",
}
COMMON_FILENAME_WORDS = COMMON_SUFFIX_WORDS | {
    "용역",
    "수립",
    "2차",
    "1차",
    "3차",
    "운영",
    "및",
    "구축용역",
}

LEGAL_KEYWORDS_MAP = {
    "하도급": ["하도급"],
    "공동수급": ["공동수급", "지분율", "컨소시엄"],
    "지분율": ["지분율", "공동수급"],
    "계약보증금": ["계약보증금", "보증금"],
    "평가": ["배점", "평가비율", "기술평가", "가격평가"],
    "제안서 보상": ["제안서 보상"],
    "불이익": ["부정당업자", "입찰보증금", "귀속"],
    "제출물": ["제출서류", "부", "USB", "제출규격"],
    "제출": ["제출서류", "USB"],
    "수량": ["부", "USB"],
    "구축기간": ["사업기간", "구축기간", "개월"],
    "사업기간": ["사업기간", "구축기간", "개월"],
    "유지보수": ["무상유지보수", "유지보수기간", "하자보수", "무상 하자보수"],
    "참가자격": ["참가자격", "참가 자격"],
    "유지관리": ["하자보수", "유지관리 인력", "무상 하자보수"],
    "교육 의무": ["유지관리 인력", "사용자 및 관리자", "하자보수"],
    "교육을": ["유지관리 인력", "사용자 및 관리자", "하자보수"],
    "검수 후": ["하자보수", "유지관리 인력"],
    "재입찰": ["재입찰", "재공고입찰", "최초의 입찰"],
    "재공고": ["재입찰", "재공고입찰", "최초의 입찰"],
    "조건 변경": ["재입찰", "재공고입찰", "최초의 입찰"],
    "지역 요건": ["주된 영업소", "소재지"],
    "부산에": ["주된 영업소", "소재지"],
    "지역요건": ["주된 영업소", "소재지"],
    "소재지": ["주된 영업소", "소재지"],
    "보유인력": ["보유인력", "배점한도"],
    "배점한도": ["보유인력", "배점한도"],
    "계량평가": ["보유인력", "배점한도", "재무구조"],
    "규모비율": ["규모비율", "환산점수", "점수비중"],
    "환산점수": ["규모비율", "환산점수", "점수비중"],
    "수행실적": ["규모비율", "환산점수", "수행실적"],
    "신인도": ["신인도", "가점"],
    "가점표": ["신인도", "가점"],
    "연구원 승인": ["Lesson", "회람"],
    "발생한 경우": ["Lesson", "회람"],
    "회람": ["Lesson", "회람"],
}


def find_relevant_keywords(question):
    """질문에 법률·절차 관련 트리거 단어가 있으면, 실제 문서에서 쓰이는 관련 표현들을 반환"""
    matched = []
    for trigger, kws in LEGAL_KEYWORDS_MAP.items():
        if trigger in question:
            matched.extend(kws)
    return list(set(matched))


def is_aggregation_question(question):
    """전체 개수/집계를 묻는 질문인지 판별"""
    keywords = ["몇 개", "개수", "다 나열", "몇 건"]
    strong_total = "전부" in question or (
        "총" in question and ("개" in question or "건" in question)
    )
    return any(kw in question for kw in keywords) or strong_total


def extract_filter_conditions(query):
    """질문에서 금액/지자체/공사/긴급 등 구조화된 필터 조건을 추출"""
    conditions = {}
    if "억" in query and ("이상" in query or "넘는" in query):
        match = re.search(r"(\d+)억", query)
        if match:
            conditions["금액_최소"] = int(match.group(1)) * 100000000
    if "지자체" in query or "지방자치단체" in query:
        conditions["지자체"] = True
    if "공사" in query and ("OO공사" in query or "발주기관이" in query):
        conditions["공사"] = True
    if "AI" in query:
        conditions["주제_AI"] = True
    if "긴급" in query:
        conditions["긴급"] = True
    if "보안" in query:
        conditions["보안"] = True
    if "재난" in query:
        conditions["재난"] = True
    return conditions


def is_local_gov(org):
    """발주기관명이 지자체(시/도/군/구로 끝남)인지 판별"""
    if org is None or (isinstance(org, float)):
        return False
    return bool(
        re.search(
            r"(광역시|특별시|특별자치도|특별자치시|[가-힣]+도|[가-힣]+시|[가-힣]+군|[가-힣]+구)$",
            str(org).strip(),
        )
    )


def normalize_org_name(name):
    return re.sub(r"(특별시|광역시|특별자치시|특별자치도)", "", name)


def extract_doc_hints_multi(question, all_filenames_with_biz):
    """질문에서 기관명 -> 사업명 -> 파일명 유사도 순으로 관련 문서를 찾아
    문서 힌트 리스트를 반환. 같은 발주기관에 문서가 여러 개면 4단계에서
    질문 키워드와 가장 많이 겹치는 문서 하나를 선택한다 (v2: fuzzy 매칭 개선)."""
    q_no_space = question.replace(" ", "").replace("&", "")
    org_candidates = []
    for fname, biz_name in all_filenames_with_biz:
        org_part = fname.replace("refined_", "").split("_")[0].strip()
        org_core = re.sub(r"\s*\(.*?\)\s*", "", org_part).strip()
        org_core_clean = re.sub(r"^\(사\)", "", org_core).strip()
        org_core_clean = re.sub(r"\s*입찰공고\s*$", "", org_core_clean).strip()
        org_core_norm = normalize_org_name(org_core_clean)
        if len(org_core_clean) < 2:
            continue

        matched = False
        if (
            org_core_clean in question
            or len(org_core_norm) >= 3
            and org_core_norm in question
            or org_core_clean in ORG_ALIAS_MAP
            and any(alias in question for alias in ORG_ALIAS_MAP[org_core_clean])
        ):
            matched = True
        else:
            min_len = 4
            for target_str in [org_core_clean, org_core_norm]:
                for start in range(len(target_str) - min_len + 1):
                    for length in range(len(target_str) - start, min_len - 1, -1):
                        substr = target_str[start : start + length]
                        if (
                            substr.strip() in question
                            and substr.strip() not in COMMON_SUFFIX_WORDS
                        ):
                            matched = True
                            break
                    if matched:
                        break
                if matched:
                    break
        if matched:
            org_candidates.append((fname, org_core_clean))

    biz_candidates = []
    quoted = re.findall(r"['\"]([^'\"]+)['\"]", question)
    for fname, biz_name in all_filenames_with_biz:
        biz_name = str(biz_name).strip()
        if len(biz_name) >= 4 and biz_name in question:
            biz_candidates.append(fname)
            continue
        for q_ in quoted:
            if q_ in biz_name or biz_name in q_:
                biz_candidates.append(fname)
                break
        eng_words = re.findall(r"[A-Za-z][A-Za-z&\s]{2,}[A-Za-z]", biz_name)
        for ew in eng_words:
            ew_no_space = ew.strip().replace(" ", "").replace("&", "")
            if len(ew_no_space) >= 4 and ew_no_space in q_no_space:
                biz_candidates.append(fname)
                break

    stopwords_general = {
        "사업의",
        "사업에서",
        "사업은",
        "어떻게",
        "되나요",
        "되나요?",
        "몇",
        "어떤",
        "얼마",
        "비교",
        "알려줘",
        "정리해줘",
        "무엇인가요",
        "관련",
        "입찰공고일",
        "공고일",
        "입찰공고",
    }
    raw_keywords = [
        w.rstrip(".,?!") for w in re.split(r"[ ,·]", question) if len(w) >= 4
    ]
    keywords_all = [
        w
        for w in raw_keywords
        if w not in stopwords_general
        and w not in COMMON_FILENAME_WORDS
        and "입찰공고" not in w
    ]

    def fuzzy_match(kw, text, min_overlap=4):
        kw_ns = kw.replace(" ", "")
        text_ns = text.replace(" ", "")
        if kw_ns in text_ns:
            return True
        for n in range(len(kw_ns), min_overlap - 1, -1):
            if kw_ns[:n] in text_ns:
                return True
        return False

    def keyword_weight(kw):
        return 3 if re.search(r"[A-Za-z]", kw) else 1

    filename_candidates = []
    for fname, biz_name in all_filenames_with_biz:
        fname_clean = (
            fname.replace("refined_", "").replace(".hwp", "").replace(".pdf", "")
        )
        matched_kws = [kw for kw in keywords_all if fuzzy_match(kw, fname_clean)]
        score = sum(keyword_weight(kw) for kw in matched_kws)
        if score > 0:
            filename_candidates.append((fname, score, len(matched_kws)))

    if filename_candidates:
        filename_candidates.sort(key=lambda x: -x[1])
        max_score = filename_candidates[0][1]
        for top_fname, score, cnt in filename_candidates:
            if score >= max_score * 0.6 or score >= 1:
                if (
                    top_fname not in [f for f, _ in org_candidates]
                    and top_fname not in biz_candidates
                ):
                    if len(filename_candidates) <= 3 or score >= max(
                        max_score * 0.6, 1
                    ):
                        biz_candidates.append(top_fname)

    org_groups = {}
    for fname, org_core in org_candidates:
        org_groups.setdefault(org_core, []).append(fname)

    # 4단계: 같은 발주기관에 문서가 여러 개일 때 문서 선택
    # (v2 개선: 발주기관명/조사형 단어 노이즈 제거, 조사 뗀 부분 문자열 매칭)
    stopwords = {
        "사업의",
        "사업에서",
        "어떻게",
        "되나요?",
        "되나요",
        "몇",
        "어떤",
        "얼마",
        "비교",
        "용역은",
        "용역이",
        "용역을",
        "사업은",
        "사업이",
        "사업을",
    }
    keywords = [
        w for w in re.split(r"[ ,]", question) if len(w) >= 2 and w not in stopwords
    ]

    def _fuzzy_kw_match(kw, text):
        kw_clean = re.sub(r"(은|는|이|가|을|를|에|의|와|과|로|으로)$", "", kw)
        if len(kw_clean) < 2:
            return False
        return kw_clean in text.replace(" ", "")

    final_hints = []
    for org_core, fnames in org_groups.items():
        fnames = list(set(fnames))
        if len(fnames) == 1:
            final_hints.append(fnames[0])
        else:
            fname_to_biz = dict(all_filenames_with_biz)
            best_doc, best_score2 = None, -1
            for fname in fnames:
                biz_name = fname_to_biz.get(fname, "")
                score2 = sum(
                    1
                    for kw in keywords
                    if _fuzzy_kw_match(kw, fname) or _fuzzy_kw_match(kw, str(biz_name))
                )
                if score2 > best_score2:
                    best_score2, best_doc = score2, fname
            final_hints.append(best_doc)

    for fname in biz_candidates:
        if fname not in final_hints:
            final_hints.append(fname)

    return list(dict.fromkeys(final_hints))


def meta_header_from_metadata(doc_id, metadata):
    """검색된 청크 앞에 붙일 메타데이터 헤더 생성"""
    org = metadata.get("발주_기관", "")
    amt = metadata.get("사업_금액")
    amt_str = f"{amt:,.0f}원" if amt not in (None, "") else "확인되지 않음"
    return f"[문서: {doc_id}]\n[발주기관(메타데이터): {org}]\n[사업금액(메타데이터): {amt_str}]"


def ask_rfp_v9(
    question,
    client,
    index,
    child_chunks,
    all_filenames_with_biz,
    model_name="gpt-5-mini",
    max_retries=2,
):
    """RFP 질문에 대한 최종 답변 생성 함수.

    Args:
        question: 사용자 질문
        client: OpenAI 클라이언트
        index: HybridIndex (검색기)
        child_chunks: 검색 대상 청크 리스트
        all_filenames_with_biz: (doc_id, 발주기관) 튜플 리스트
    """
    doc_hints = extract_doc_hints_multi(question, all_filenames_with_biz)
    doc_hints = doc_hints[:3]
    keywords = find_relevant_keywords(question)
    conditions = extract_filter_conditions(question)

    doc_to_meta = {}
    for c in child_chunks:
        if c.doc_id not in doc_to_meta:
            doc_to_meta[c.doc_id] = c.metadata

    context_parts = []

    def get_doc_chunks(doc_id):
        return [c for c in child_chunks if c.doc_id == doc_id]

    def build_meta_filter(conds):
        if not conds:
            return None

        def _filter(meta):
            if "금액_최소" in conds:
                amt = meta.get("사업_금액")
                if amt is None or amt < conds["금액_최소"]:
                    return False
            if conds.get("지자체"):
                if not is_local_gov(meta.get("발주_기관")):
                    return False
            if conds.get("공사"):
                org = str(meta.get("발주_기관", ""))
                if "공사" not in org:
                    return False
            return True

        return _filter

    if is_aggregation_question(question) and len(doc_hints) >= 1:
        stopwords_q = {
            "사업의",
            "사업에서",
            "어떻게",
            "되나요?",
            "되나요",
            "몇",
            "어떤",
            "얼마",
            "비교",
        }
        qkeywords = [
            w
            for w in re.split(r"[ ,]", question)
            if len(w) >= 2 and w not in stopwords_q
        ]
        best_doc, best_score = doc_hints[0], -1
        for fname in doc_hints:
            biz = doc_to_meta.get(fname, {}).get("발주_기관", "")
            score = sum(1 for kw in qkeywords if kw in fname or kw in str(biz))
            if score > best_score:
                best_score, best_doc = score, fname
        doc_hint = best_doc
        header = meta_header_from_metadata(doc_hint, doc_to_meta.get(doc_hint, {}))
        for c in get_doc_chunks(doc_hint):
            context_parts.append(f"{header}\n{c.text}")

    elif len(doc_hints) == 1 and keywords:
        doc_hint = doc_hints[0]
        doc_c = get_doc_chunks(doc_hint)
        keyword_chunks = [c for c in doc_c if any(kw in c.text for kw in keywords)]
        header = meta_header_from_metadata(doc_hint, doc_to_meta.get(doc_hint, {}))
        if keyword_chunks:
            # 키워드 매칭 청크 + 문서 앞쪽 청크(사업개요/범위가 보통 위치)를 함께 사용
            # (v9: 질문이 여러 항목을 물을 때 키워드에 안 걸리는 항목이 누락되는 문제 해결)
            combined = keyword_chunks[:20] + doc_c[:10]
            seen_ids = set()
            for c in combined:
                if c.chunk_id in seen_ids:
                    continue
                seen_ids.add(c.chunk_id)
                context_parts.append(f"{header}\n{c.text}")
        else:
            hits = index.hybrid_search(question, k=10, expand_to_parent=True)
            for h in hits:
                context_parts.append(
                    f"{meta_header_from_metadata(h.doc_id, doc_to_meta.get(h.doc_id, {}))}\n{h.text}"
                )

    elif len(doc_hints) >= 2:
        for doc_hint in doc_hints:
            doc_c = get_doc_chunks(doc_hint)
            if keywords:
                matched = [c for c in doc_c if any(kw in c.text for kw in keywords)]
                selected = matched[:8] if matched else doc_c[:8]
            else:
                selected = doc_c[:8]
            header = meta_header_from_metadata(doc_hint, doc_to_meta.get(doc_hint, {}))
            for c in selected:
                context_parts.append(f"{header}\n{c.text}")

    elif doc_hints:
        doc_hint = doc_hints[0]
        doc_c = get_doc_chunks(doc_hint)
        header = meta_header_from_metadata(doc_hint, doc_to_meta.get(doc_hint, {}))
        for c in doc_c[:15]:
            context_parts.append(f"{header}\n{c.text}")

    elif conditions:
        meta_filter = build_meta_filter(conditions)
        hits = index.hybrid_search(
            question, k=80, meta_filter=meta_filter, expand_to_parent=True
        )
        for h in hits:
            context_parts.append(
                f"{meta_header_from_metadata(h.doc_id, doc_to_meta.get(h.doc_id, {}))}\n{h.text}"
            )

    else:
        hits = index.hybrid_search(question, k=10, expand_to_parent=True)
        for h in hits:
            context_parts.append(
                f"{meta_header_from_metadata(h.doc_id, doc_to_meta.get(h.doc_id, {}))}\n{h.text}"
            )

    context = "\n\n---\n\n".join(context_parts)

    prompt_base = SYSTEM_PROMPT_V9
    if needs_metadata_distinction(question):
        prompt_base = prompt_base.replace(
            "## 컨텍스트 (검색된 문서 조각)",
            METADATA_DISTINCTION_INSTRUCTION + "\n## 컨텍스트 (검색된 문서 조각)",
        )

    final_prompt = prompt_base.format(context=context, question=question)

    for attempt in range(max_retries):
        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": final_prompt}],
            max_completion_tokens=8000,
            reasoning_effort="low",
        )
        answer = response.choices[0].message.content
        if answer:
            return answer
    return "(답변 생성 실패)"
