# Supabase 설정 (20~30분)

Streamlit Community Cloud 는 앱이 잠들거나 재배포되면 파일이 사라집니다.
편지를 12월까지 지키려면 이 설정이 반드시 필요합니다.

## 1. 프로젝트 만들기

1. https://supabase.com 가입 (GitHub 계정으로 가능)
2. **New project** → 이름 아무거나, **Region 은 Northeast Asia (Seoul)**
3. Database Password 는 적어 두기 (나중에 안 써도 분실하면 곤란)
4. 만들어지는 데 2~3분 걸립니다

## 2. 표 만들기

왼쪽 메뉴 **SQL Editor** → **New query** → 아래를 통째로 붙여넣고 **Run**

```sql
create table letters (
  id          bigserial primary key,
  class_key   text not null,
  number      text not null,
  nickname    text not null,
  body        text not null,
  written_at  text not null,
  created_at  timestamptz default now(),
  unique (class_key, number)
);

create table garden (
  id         bigserial primary key,
  class_key  text not null,
  op         text not null,          -- add / remove / water / fruit
  event_id   text not null,
  number     text,
  item       text,
  x          real,
  y          real,
  flip       boolean default false,  -- 좌우 뒤집기
  by         text,
  at         text,
  created_at timestamptz default now()
);

create index on letters (class_key);
create index on garden  (class_key, id);

-- 앱에서만 접근하므로 외부 공개는 막습니다
alter table letters enable row level security;
alter table garden  enable row level security;
```

`unique (class_key, number)` 덕분에 같은 반 같은 번호가 두 번 저장되지 않습니다.

## 3. 열쇠 가져오기

왼쪽 아래 **Project Settings → API**

- **Project URL** — `https://xxxxx.supabase.co`
  뒤에 아무것도 붙이지 마세요. `/rest/v1` 을 붙이면 연결되지 않습니다.
- **service_role** 키 (`Project API keys` 아래, 눈 모양을 눌러 확인)

> service_role 키는 모든 권한을 가집니다.
> **절대 GitHub 에 올리지 마세요.** 아래 Secrets 에만 넣습니다.

## 4. Streamlit 에 넣기

앱 화면 우하단 **Manage app → ⋮ → Settings → Secrets** 에 붙여넣고 Save

```toml
SUPABASE_URL = "https://xxxxx.supabase.co"
SUPABASE_KEY = "eyJhbGciOi...(service_role 키)"
```

저장하면 앱이 자동으로 다시 시작합니다.

## 나중에 칸이 늘었을 때

기능을 더하면서 저장할 칸이 늘어나면 이런 오류가 납니다.

```
PGRST204  Could not find the 'flip' column of 'garden'
```

표에 그 칸을 더해 주면 됩니다. SQL Editor 에서:

```sql
alter table garden add column if not exists flip boolean default false;
```

그래도 같은 오류가 이어지면 Supabase 가 표 구조를 캐싱하고 있는 것입니다.
**Project Settings → API → Reload schema cache** 를 누르거나 1분쯤 기다리세요.

앱은 없는 칸을 만나면 **그 칸만 빼고 저장을 계속합니다.**
아이 화면이 멈추지는 않지만, 그 값(예: 좌우 뒤집기)은 기록되지 않으니
위 SQL 을 실행해 주세요.

## 흔한 오류

교사 화면에 상태 코드가 표시됩니다.

| 코드 | 뜻 | 할 일 |
|---|---|---|
| **PGRST125** | 주소가 잘못됨 | `SUPABASE_URL` 에 **프로젝트 기본 주소만** 넣기. 뒤에 `/rest/v1` 을 붙이면 안 됩니다 |
| **PGRST205** | 표가 없음 | 2단계 SQL 을 실행하지 않았거나, **다른 프로젝트**에서 실행함 |
| **401** | 키가 틀림 | `SUPABASE_KEY` 를 다시 복사 (앞뒤 공백·따옴표 주의) |
| **403** | 권한 없음 | anon 키를 넣었을 가능성. **service_role** 키로 바꾸기 |

404 가 가장 흔합니다. SQL Editor 에서 Run 을 눌렀을 때
아래에 초록색 **Success** 가 떴는지 확인하세요. 빨간 글씨가 떴다면
표가 만들어지지 않은 것입니다.

Secrets 의 `SUPABASE_URL` 이 그 프로젝트의 주소가 맞는지도 확인하세요.
프로젝트를 두 개 만들었다면 엉뚱한 쪽을 보고 있을 수 있습니다.

## 5. 확인

교사 코드로 들어갔을 때 **"지금은 임시 저장(로컬 파일)입니다"** 경고가
사라지면 연결된 것입니다. 경고가 그대로면 URL 이나 키를 다시 보세요.

편지를 하나 넣고, Supabase 의 **Table Editor → letters** 에 줄이 생기는지
확인하면 확실합니다.

## 내 컴퓨터에서 시험할 때

프로젝트 안에 `.streamlit/secrets.toml` 을 만들고 같은 두 줄을 넣습니다.
이 파일은 `.gitignore` 에 들어 있어 GitHub 에 올라가지 않습니다.

설정이 없으면 앱은 `data/` 폴더에 저장합니다. 연습용으로는 괜찮지만
실제 수업에는 쓰면 안 됩니다.

## 그래도 종이 사본은 남기세요

한 달에 한 번은 반별로 **인쇄용으로 내려받기** 를 눌러 보관하세요.
Supabase 든 무엇이든 사고는 납니다.
