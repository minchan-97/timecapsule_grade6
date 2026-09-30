# 수업 전 31명 동시사용 부하테스트

이 스크립트는 **실제 반 데이터를 건드리지 않고** 수업 전에 두 가지를 확인합니다.

1. 배포된 Streamlit 주소가 31~50개의 동시 HTTP 요청을 받아내는지
2. Supabase가 편지 저장·물주기·꾸미기와 비슷한 동시 요청을 처리하는지

> 한계: Streamlit의 실제 브라우저 WebSocket/session rerun 전체를 자동 재현하는 도구는 아닙니다.
> 따라서 `app` 검사는 서버의 HTTP 생존성과 첫 응답을, `db-mixed`는 실제 데이터 경로의 부하를 점검합니다.
> 마지막 확인은 휴대폰 2~3대로 실제 UI를 눌러 보는 것이 가장 좋습니다.

## 1. 가장 먼저: Streamlit 접속 테스트

터미널에서 프로젝트 폴더로 이동한 뒤:

```bash
python load_test.py app --url https://내앱주소.streamlit.app --users 31 --rounds 3
```

학생 21명 + 학부모 10명을 가정한 기본 시험입니다.

조금 더 세게 하려면:

```bash
python load_test.py app --url https://내앱주소.streamlit.app --users 50 --rounds 5
```

## 2. Supabase 읽기 시험

`SUPABASE_URL`, `SUPABASE_KEY`가 `.streamlit/secrets.toml`에 있다면:

```bash
python load_test.py db-read --users 31 --rounds 5
```

읽기 전용이라 실제 데이터를 생성하지 않습니다. 존재하지 않는 임시 반(`LOADTEST_...`)을 읽습니다.

## 3. 실제 수업과 비슷한 쓰기+읽기 시험

```bash
python load_test.py db-mixed --users 31 --rounds 3 --confirm-write
```

이 시험은 다음을 동시에 만들어 봅니다.

- 31명이 거의 동시에 편지 1통씩 저장
- 물주기
- 농장 장식 추가
- 편지/농장 읽기

테스트 데이터는 매번 `LOADTEST_날짜_시간_난수`라는 별도 반에만 기록하며,
끝날 때 그 임시 반의 `letters`, `garden` 행만 자동 삭제합니다.

**실제 `namu51` 같은 반 코드는 삭제 조건으로 사용하지 않습니다.**

## 4. 한 번에 모두

```bash
python load_test.py all --url https://내앱주소.streamlit.app --users 31 --rounds 3 --confirm-write
```

## 결과 읽기

예:

```text
requests : 93
success  : 93 (100.0%)
errors   : 0
latency  : avg 0.42s | p50 0.36s | p95 0.91s | max 1.31s
```

수요일 수업 전 권장 기준:

- 오류율: **0%**가 가장 좋음
- p95: **3초 이하**면 한 학급 사용에는 대체로 편안한 편
- p95 3~6초: 사용은 가능하지만 동시에 저장시 체감 지연 가능
- p95 6초 초과 또는 429/5xx 발생: 동시 저장을 번호별로 나누는 운영 권장
- `timeout`: 서버/네트워크 병목을 우선 의심
- `401/403`: Supabase 키/권한 문제
- `409`: 테스트 데이터 중복 또는 DB unique 충돌 확인
- `5xx`: 서버 또는 Supabase 일시 오류 확인

## 수업 직전 추천 순서

```bash
python load_test.py app --url https://내앱주소.streamlit.app --users 31 --rounds 3
python load_test.py db-mixed --users 31 --rounds 3 --confirm-write
```

둘 다 오류 0%이고 p95가 무난하면, 마지막으로 휴대폰 2~3대에서
`편지 저장 → 농장 → 물주기 → 장식 → 다른 기기에서 반영 확인`을 직접 해보세요.

## 보안

`service_role` 키는 절대로 GitHub에 올리지 마세요. 이 ZIP에도 키는 들어 있지 않습니다.
`load_test.py`는 기존 앱과 동일하게 환경변수 또는 `.streamlit/secrets.toml`에서만 읽습니다.
