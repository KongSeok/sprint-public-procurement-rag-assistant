# Current Requirements (Working)

## Goal
스포일러 방지 필터링 서비스 - 사용자의 시청 상태(K)를 기준으로 안전한 정보만 노출하는 위키/Q&A 서비스

## Scope (IN)
- 드라마/에피소드 선택 + 사용자 상태 저장
- 메인 페이지: 승인 데이터 기반 캐릭터 목록 + 안전 요약
- 위키: 기여/검수/승인(N명) 흐름
- 온톨로지: LabelDraft 승인 → Event 자동 생성 + Q&A Event 기반 에피소드 범위 응답
- Episode Range 기반 모든 정보 관리

## Scope (OUT)
- 자동 이미지 수집/처리
- 리뷰어 평판 시스템
- AI 자가학습
- 다국어 지원
- 커뮤니티 기반 학습/피드백 루프
- MVP 관계(INVOLVES, REVEALS, PRECEDES) 이상의 온톨로지 확장

## Definition of Done (DoD)
1. K 값 변화에 따라 같은 인물/요약이 달라진다
2. PENDING 데이터는 어떤 방식으로도 사용자에게 노출되지 않는다
3. 위키에서 N명 승인 → APPROVED 전환이 된다
4. Q&A는 Event 기반으로 `X~Y화 범위`를 응답한다
5. WikiEntry + LabelDraft가 승인되면 Event가 자동 생성된다

## Constraints
- AI는 보조 도구로만 사용 (진실/스포일러 안전성 판단 금지)
- 모든 최종 노출 결정은 규칙 기반
- 성능: 메인 페이지 ≤1.5s, 캐릭터 상세 ≤1s, Q&A 평균 2s/최대 4s

## Open Questions
- 온톨로지 레이어 구현 기술 스택 (RDB vs GraphDB)
- N명 승인 기준값 결정
- 초기 시드 데이터 드라마 선정

---

# Full Requirements Document

## 1. Document Purpose
This document defines the requirements for the No-Spoiler Filtering team project. Developers should be able to implement features, divide roles, design APIs, and construct UI flows using this document alone. It serves simultaneously as a product plan, a requirements specification, and a collaboration guideline.

## 2. Project Overview

### 2.1 Background
Spoilers significantly damage content consumption experiences, yet existing services rely mainly on keyword blocking or user reports. These approaches fail when expressions change, ignore the user's actual viewing progress, and cannot explain why content is blocked. This project redefines spoilers as a contextual information problem centered on episodes, events, and characters.

### 2.2 Core Questions
- How much information is safe for the user to know at their current viewing state?
- Can information be delivered safely without fully hiding it?
- How can AI-based judgments become trustworthy to users?

### 2.3 Strategy Summary
- Explicitly model user state based on episodes
- Manage all information as Event + Valid Episode Range
- Use AI only as a decision assistant; final exposure is rule-based

### 2.4 Success Criteria
- Users browse and ask questions without spoiler anxiety
- Exposure/blocks are explained with episode ranges and clear grounds
- Contributor workflow produces reviewed, labeled data that powers context-aware retrieval

## 3. User Definitions

### 3.1 Primary User: Active Viewer
**Characteristics**
- Watching episodes sequentially
- Wants to browse community or reference information
- Highly spoiler-sensitive

**Goals**
- Organize what has already been watched
- Understand character relationships clearly

**Concerns**
- Even small hints may reveal future plot developments

### 3.2 Secondary User: Contributor / Reviewer
**Characteristics**
- Deep understanding of the work
- Values accuracy and proper expression

**Goals**
- Record accurate information systematically
- Prevent the spread of incorrect or misleading content

### 3.3 Shared Assumptions
- Users understand the system is not perfect
- Safety-first behavior is expected

## 4. Core User Scenarios

### S-1 Main Page Browsing
1. User visits the service
2. Selects a drama
3. Sets the last watched episode
4. System displays safe character list
5. User opens character details

**Success**: No spoiler anxiety during exploration

### S-2 Memory-Based Episode Q&A
1. User inputs a remembered scene in natural language
2. System analyzes the event
3. Responds with an estimated episode range

**Success**: User can infer their viewing position

### S-3 Wiki Contribution & Review
**Contributor Flow**
1. Select character
2. Write information in natural language
3. Specify episode range
4. Select EventType + involved characters (controlled)
5. Use AI assistance for structuring (optional)

**Reviewer Flow**
1. Review pending entries
2. Evaluate factual and spoiler safety
3. Approve or reject

**Success**: Only reviewed information is exposed

## 5. Page-Based Functional Requirements

### P-1 Main Page
**Purpose**
- Enable safe exploration up to the watched episode
- Character-centric information with spoiler control

**Flow**
- Drama selection → Episode selection → Character cards → Character detail

**Key Requirements**
- Drama has a unique ID
- Episodes are ordered
- Selected episode is stored as user state
- Characters shown only if referenced up to that episode
- Characters sorted by importance score (frequency, involvement, review score)

**Image Policy**
- Revealed appearance before episode: real image
- Otherwise: blurred or placeholder image

**Detail Policy**
- Name (only if safe)
- Spoiler-free summary
- Facts limited to selected episode
- Future-sensitive info must be abstracted

### P-2 Q&A Page
**Purpose**
- Assist memory without spoilers

**Functions**
- Infer episode range from event description
- Answer character questions using only prior information

**Safety**
- Explicit future spoiler questions are rejected with warnings

### P-3 Wiki Page
**Purpose**
- Build a trusted human-verified knowledge base

**Roles**
- Contributor: writes information with episode range + labels
- Reviewer: verifies facts and spoiler safety

**Process**
- Contributor selects labels from controlled vocabulary
- Label drafts are reviewed with WikiEntry; approved labels generate Events
- AI assists with structuring (optional)
- Final approval requires N reviewers
- Only approved data is used by the system

## 6. Non-Functional Requirements

### Performance
- Main page load: ≤ 1.5s
- Character detail: ≤ 1s
- Q&A response: avg 2s, max 4s

### Reliability
- Service must remain functional on AI failure
- Conservative fallback behavior is mandatory

### Explainability
Each piece of information must store:
- Episode range
- Source wiki ID
- Review status

### Consistency
- Same drama + episode state must yield consistent results across pages

### Scalability
- New dramas added via data only
- Character list limited to top-N by importance

### Security & Abuse Prevention
- Repeated spoiler-seeking behavior triggers limits
- Wiki access is role-based

## 7. AI Usage (Minimal Scope)

AI is used strictly as an auxiliary tool. Its role is limited to text structuring and episode-range inference under explicit system rules.

- AI does not determine truth or spoiler safety
- All final exposure decisions are rule-based

If AI output is missing required structure or episode range, the system defaults to conservative blocking.

## 8. Error & Exception Handling

### Error Types
- User Error
- System Error
- AI Error

### User Error Handling
- Action-guiding messages without technical terms

### System Error Handling
- Retry UI
- Cached data fallback

### AI Error Handling
- Default to safe summaries
- Range-only or rejected answers
- Disable AI assistance in Wiki if needed

## 9. MVP Definition

### Must-Have
- Drama & episode selection
- User state storage
- Character list filtering
- Spoiler-safe summaries
- Event-based episode inference
- Wiki contribution and review flow

### Demo Success
- Character list/summary changes when episode state K changes
- Q&A returns Event-based episode ranges and rejects out-of-range spoilers
- Unapproved WikiEntry or LabelDraft is never exposed; Events are created only from approved labels

## 10. Ontology Layer Definition

*Contextual Search & Interpretation*

### 10.1 온톨로지 레이어의 역할 (Why)

온톨로지는 이 프로젝트에서 **지식을 더 많이 저장하기 위한 장치가 아니다**.
유일한 목적은 하나다.

> "같은 단어·같은 인물·같은 사건이라도
> **맥락이 다르면 다른 것으로 취급**하기 위해"

즉, 일반 위키가 못 하는 것을 딱 한 가지 한다:

* ❌ 키워드 매칭
* ❌ 문서 단위 탐색
* ✅ **맥락 단위 탐색 (Context-aware retrieval)**

### 10.2 일반 위키와의 구조적 차이

**일반 위키**
* 문서 중심
* 링크는 느슨함
* "A는 B다" 수준의 정적 정보

**이 프로젝트의 온톨로지**
* **사건(Event) 중심**
* 모든 정보는 **관계(Relation)** 를 가진다
* 시간(에피소드 범위)이 **1급 속성**

### 10.3 온톨로지의 최소 구성 요소 (MVP Scope)

**핵심 노드(Node)**

**Event**
* 사건의 최소 의미 단위
* 속성: `eventId`, `eventType` (controlled), `episodeStart`, `episodeEnd`, `summary`

**Character**
* 기존 도메인 모델과 동일
* 온톨로지에서는 **행위 주체**로만 사용

**핵심 관계(Relation)**

**INVOLVES**: Event ↔ Character
**REVEALS**: Event → Character / Attribute (⚠️ 스포일러 핵심 관계)
**PRECEDES**: Event → Event (시간적 선후 관계)

### 10.4 성공 기준 (Ontology Layer)

* 같은 질문이라도 키워드가 아니라 **사건 기준**으로 응답한다
* 차단 시 "왜"를 **관계와 에피소드로 설명**할 수 있다
* 개발자가 "이건 온톨로지라서 이렇게 동작한다"고 명확히 설명할 수 있다

## 11. Scope Boundary

The following items are explicitly excluded from the current scope:
- Automated image collection or image-based spoiler handling
- Reviewer reputation system
- AI self-learning
- Multi-language support
- Community-driven learning or reporting feedback loops
- Ontology expansion beyond Event/Character nodes and the MVP relations
