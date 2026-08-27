# 5일신고가 · 3일신저가 자동매매 봇 (high5-screener) - 전체 컨텍스트 요약 v7

새 채팅창에서 이 파일을 업로드하고 "이 프로젝트 이어서 작업할게, v7 컨텍스트 파악해줘"라고
하면 바로 이어서 작업 가능. **터틀 스크리너(turtle-screener)와는 완전히 별도의 봇/저장소.**

**코드 수정 규칙: 항상 부분수정이 아닌 전체 파일 재작성 방식으로 진행할 것.**

---

## ⚠️ v7 최중요 변경 — "완전자동매매"라는 애초 설계가 틀렸음을 발견, 터틀 방식(알림전용)으로 전면 수정

v1~v6까지는 "신호가 뜨면 시스템이 알아서 매수/매도까지 다 한다(완전자동)"는 전제로
만들었는데, 사용자가 "지금 내가 하는 터틀 역시 자동매매는 아니다"라고 알려줘서
**터틀의 실제 소스코드(`turtle-screener-source-1.md`)를 처음부터 다시 대조**했고,
터틀은 애초에 이런 구조였음이 확인됨:

- 전체스캔/재확인은 **알림만** 함 (holdings.csv에 아무것도 안 씀)
- 실제 매수는 사용자가 텔레그램으로 **`buy` 명령을 직접 입력**해야만 등록됨
- 손절선 이탈해도 **자동으로 안 팖** — "매도 검토" 알림만 가고 `status='stop_hit'`,
  사용자가 `sell` 명령을 쳐야 비로소 `closed_manual`로 종료됨
- 휩쏘 필터(직전 거래 승/패 학습)는 **자동스캔 파이프라인 자체의 신호 상태**
  (관심→확정→확정이탈)로만 판단하고 기록함. 실제 보유종목(holdings)의 매수/매도와는
  완전히 무관 (bot_commands.py가 trade_history를 아예 import도 안 함)

이걸 몰랐던 상태로 v1~v6에서 만든 "신호 뜨면 자동 매수, 3일신저가/하드스탑 걸리면
자동 매도" 로직은 전부 터틀과 다른 설계였고, 이번에 전면 재설계함.

### 3가지 데이터가 완전히 분리됨 (사용자가 지적한 "집중추적과 보유종목 분리" 요청의 최종 해법)

| 파일 | 역할 | 누가 채우나 | 자동매매 여부 |
|---|---|---|---|
| `scan.csv` | 자동 전체스캔/재확인 신호 캐시 (진입/관심/확정/확정이탈/탈락) | `full_scan_*.py`/`recheck_*.py` | **알림만, 매수 절대 안 함** |
| `positions.csv` | 실제 보유종목 | 텔레그램 `buy`/`sell` 명령 (사용자가 직접) | 감시(위험도 체크)만 자동, 매매 실행은 수동 |
| `tracked.csv` | 수동 추적목록 | 텔레그램 `코드 추적시작`/`추적종료` | 상태변화 감시만 자동, 매매 없음 |

세 파일은 서로 완전히 독립적. `scan.csv`에서 '진입'이 떠도 `positions.csv`엔
아무 일도 안 일어남 — 사용자가 알림을 보고 `buy 코드 가격`을 직접 쳐야만
`positions.csv`에 등록됨.

### full_scan_*.py / recheck_*.py 전면 재작성 (터틀과 동일한 상태머신)
- `common.py`에 `check_high5_system(df)` 신설: 5일신고가(진입)+3일신저가(청산) 판정을
  한 번에 묶어서 반환 (터틀의 `check_turtle_breakout`과 동일한 인터페이스)
- `common.py`에 `pick_top_entry(df)` 신설: 진입신호가 여러 개면 초과율(방금 막 돌파한
  정도)이 가장 작은 1개만 골라서 알림 (터틀과 동일 철학, 스팸 방지)
- 신호 상태: 진입(신선돌파+추격필터통과, 알림) → 관심(근접) → 확정(재확인에서 재검증+
  휩쏘필터 통과, "매수 검토" 알림) → 확정이탈(3일신저가 이탈, "매도 검토" 알림 + 휩쏘
  이력 기록) → 탈락
- 전체스캔이 재실행돼도 '확정' 상태였던 종목은 유지됨 (`storage.save_scan_for_market`이
  기존 확정 종목을 새 결과에 없어도 보존 — 터틀 로직 그대로)
- 알림 문구에 `buy {code} {price} 명령으로 등록할 수 있어요` 안내 추가 (사용자가
  바로 복사해서 칠 수 있게)

### position_check.py 전면 재작성 (터틀 holdings_check.py 방식)
- **자동 청산 완전히 제거**. 3일신저가/하드스탑 이탈 시 `status='stop_hit'`으로
  바뀌고 "매도 검토" 알림만 감 (1회, 상태가 바뀌었으니 반복 스팸 안 됨)
- `status != 'closed_manual'`인 것 전부 계속 감시 (active + stop_hit 둘 다),
  `sell` 명령이 들어와야 비로소 감시 종료
- **trade_history(휩쏘 이력) 관련 코드 완전 제거** — 실제 보유종목 매매는
  휩쏘 학습과 무관 (터틀과 동일)
- 5분 무조건 요약(📦)에서 stop_hit 상태는 "🔴 손절확정 (매도대기)" 태그로 별도 표시

### bot_commands.py 수정
- `handle_sell`: `status != 'closed_manual'`인 것을 찾도록 수정 (stop_hit 상태도
  sell로 찾아서 종료 가능해야 함 — 터틀이 v2 세션에서 겪었던 버그를 처음부터 방지)
- `handle_list`: stop_hit 상태는 `[손절확정/매도대기]` 태그 추가 표시
- `already_holding`(storage.py): `status != 'closed_manual'` 기준으로 변경
  (stop_hit도 '아직 안 판' 상태라 중복 buy 방지 대상에 포함)

### watchlist_check.py 수정
- 데이터 소스를 `watch.csv`(폐지) → `scan.csv`(signal=='관심' 행)로 변경
- 나머지(5분 무조건 요약, 추세표시)는 동일

### 검증한 것 (합성 데이터)
- `check_high5_system`: entry+exit 통합판정 정상 (fresh_entry_signal, exit_signal,
  n_low 모두 한 dict에 포함됨)
- `pick_top_entry`: 여러 진입신호 중 초과율 최솟값(가장 신선한 돌파)을 정확히 선택
- `save_scan_for_market`: 확정종목 보존 + 탈락종목 제거 + 신규종목 추가가 동시에
  일어나는 케이스 정상 동작
- `list`/`sell`: stop_hit 상태도 `[손절확정/매도대기]`로 표시되고 sell 명령으로
  정상 종료됨을 확인

---

## v6 변경 이력 (명령어를 터틀과 정확히 일치)

v4에서 만든 명령어 세트가 터틀에 없는 한글 별칭(보유종목확인/포지션확인/관심종목확인 등)을
임의로 추가한 상태였음. **터틀의 실제 소스코드(`bot_commands.py`)를 직접 대조**해서
명령어 집합과 동작 방식을 정확히 일치시키고, 판정 기준만 5일신고가/3일신저가로 교체함.

### 터틀과 다르게 되어있던 부분 (이번에 맞춤)
- ❌ 제거: `목록`/`보유종목확인`/`포지션확인`/`포지션목록` 별칭 → 터틀처럼 **`list`만** 인식
- ❌ 제거: `관심종목확인` 명령어 → 터틀에 없는 기능이라 삭제
- ❌ 제거: sell 시 현재가 자동조회 → 터틀처럼 매도가 없으면 손익계산 없이 종료만
  (v4에선 fetch_current_price로 자동조회했으나 터틀 소스엔 그런 로직이 없음)
- ❌ 제거: 명령어 처리에서 휩쏘이력(trade_history) 갱신 → 터틀도 수동거래(buy/sell)는
  자동 스캔의 휩쏘필터와 완전히 무관하게 동작함 (`bot_commands.py`가 애초에
  trade_history를 import조차 안 함)
- ✅ 추가: 터틀처럼 `/buy`, `/sell`, `/list`, `/help`처럼 앞에 슬래시 붙여도 인식
  (`cmd = parts[0].lower().lstrip('/')`)
- ✅ 추가: **신규 스크립트 `scripts/tracked_check.py`**: 터틀의 실제 watchlist_check.py
  (감시목록 터틀신호 체크, 직전 상태와 다를 때만 알림)를 그대로 이식. 지금까진
  `추적확인`을 직접 쳐야만 상태를 알 수 있었는데, 이제 **5분마다 자동으로 상태
  변화(예: 관찰중→관심→진입)가 생기면 먼저 알림**이 옴 (터틀과 동일한 사용자 경험)
- ✅ 신규 워크플로우 `.github/workflows/tracked_check.yml` (5분마다)
- **`storage.py`**: `TRACKED_COLUMNS`를 `['market','code','name']`→`['code','market','status']`로
  변경 (터틀 watchlist.csv의 `sys1_status`/`sys2_status`에 해당하는 단일 `status`
  필드 추가, high5는 시스템이 하나뿐이라 컬럼도 하나만 필요)
- **`bot_commands.py` 전체 재작성**: `dispatch()` 반환값을 터틀과 동일한
  **6-튜플** `(pos_df, tracked_df, reply, is_long, pos_changed, tracked_changed)`로
  단순화 (v4의 8-튜플에서 hist_df 관련 2개 제거)
- **`telegram_listener.py`/`webhook_handler.py`**: 위 시그니처 변경에 맞춰 재작성,
  trade_history 로드/세이브 코드 전부 제거

### 검증한 것 (합성 데이터, 네트워크 우회)
- `buy 005930 105` / `/buy 000660 200` (슬래시 포함) → 등록 정상, 문구가 터틀과 동일 톤
- `list` → 터틀과 동일 문구("현재 감시 중인 거래:") 확인
- `sell 거래번호` (매도가 생략) → 손익계산 없이 그냥 청산 (터틀과 동일 동작, v4의
  자동조회 로직 제거됨을 확인)
- `BTC 추적시작` → `추적확인` → 상태(관심/진입/청산/관찰중) 정상 표시
- `명령어확인` / `/help` → 동일 도움말 출력
- 3줄 동시 `추적시작` 명령 → 3개 모두 처리됨 (다중 라인 처리 유지 확인)

### 다음 세션에서 확인해야 할 것 (v6 추가분)
1. `tracked_check.py`가 실제로 상태 변화 시에만 알림을 보내고, 변화 없을 때는
   조용한지 실운영에서 확인
2. 웹훅(v5) 배포를 아직 진행 안 한 상태 — 사용자가 터미널 작업에 부담을 느껴
   보류 중. 5분 폴링만으로 계속 운영할지, 나중에 재도전할지는 사용자 선택 사항
3. `detect_market`의 COIN 판별(빗썸 API 조회)이 실제 배포 환경(GitHub Actions)에서
   네트워크 제한 없이 정상 동작하는지 확인 (로컬 테스트 환경에서는 아웃바운드
   제한으로 인해 항상 US로 폴백되는 것을 확인했으나 코드 자체는 정상)

---

## v4 → v5 변경 이력 (웹훅, 사용자가 진행 보류 중 — 아래 안내는 나중에 재도전 시 참고용)

터틀은 Cloudflare Worker + GitHub PAT로 즉시응답 웹훅을 만들었지만, "대시보드
Quick Edit로는 Secret 환경변수가 계속 undefined로 나온다"는 문제를 하드코딩으로
우회한 채 미해결로 남겨뒀음. 이번엔 **wrangler CLI로 Secret을 등록하는 방식**으로
원인을 회피하고, 코드에는 민감정보를 전혀 하드코딩하지 않도록 처음부터 설계함.

### 중요한 제약사항 (설계에 반영됨)
**텔레그램은 웹훅과 폴링(`getUpdates`)을 동시에 못 씀.** 웹훅이 활성화된 상태에서
`getUpdates`를 호출하면 에러가 남. 따라서:
- 웹훅이 켜져 있으면 `telegram_listener.py`(폴링)는 자동으로 조용히 스킵됨
  (에러를 잡아서 그냥 "웹훅이 활성화되어 있어 폴링을 건너뜁니다" 로그만 남김)
- 나중에 웹훅을 해제하면 폴링이 별도 코드 수정 없이 자동으로 되살아남
- 즉 "웹훅 우선, 폴링은 웹훅을 안 쓰기로 하면 자동으로 대체되는 예비 수단"

### 신규 구성요소
1. **`cloudflare-worker/index.js`**: 텔레그램 웹훅 수신 → `chat_id` 검증 →
   GitHub `repository_dispatch` API 호출. `GITHUB_PAT`, `GITHUB_OWNER`,
   `GITHUB_REPO`, `ALLOWED_CHAT_ID` 전부 `env.*`로만 참조, 코드에 하드코딩 없음.
   (이 파일은 high5-screener 저장소용이 아니라 **별도의 Cloudflare Worker
   프로젝트**로 배포하는 코드 — GitHub Actions에서는 실행되지 않음)
2. **`cloudflare-worker/wrangler.toml`**: Worker 배포 설정. 민감정보는 여기에도
   적지 않고 `wrangler secret put`으로만 등록
3. **신규 스크립트 `scripts/webhook_handler.py`**: `repository_dispatch`로 전달된
   명령어 텍스트(`COMMAND_TEXT` 환경변수) 1건을 즉시 `dispatch_lines`로 처리
4. **신규 워크플로우 `.github/workflows/telegram_webhook.yml`**:
   `repository_dispatch` (type: `telegram_message`)로 트리거
5. **`telegram_listener.py` 수정**: `getUpdates` 응답이 "webhook is active" 류
   에러면 예외 없이 조용히 빈 리스트 반환하도록 방어 로직 추가

### 배포 절차 (사용자가 직접 진행, Wrangler CLI 방식)
1. Node.js 설치 확인 (`node -v`) — 없으면 nodejs.org에서 설치
2. `npm install -g wrangler`
3. `wrangler login` (브라우저로 Cloudflare 계정 인증)
4. `cloudflare-worker` 폴더에서 `wrangler deploy` 실행 전에 시크릿 4개 등록:
   ```
   wrangler secret put GITHUB_PAT
   wrangler secret put GITHUB_OWNER
   wrangler secret put GITHUB_REPO
   wrangler secret put ALLOWED_CHAT_ID
   ```
   - `GITHUB_PAT`: GitHub에서 **fine-grained PAT** 발급, 이 저장소(high5-screener)
     만 대상으로, 권한은 **Contents: Read and write** (repository_dispatch에 필요)
   - `GITHUB_OWNER`: 예) `harmi6005`
   - `GITHUB_REPO`: 예) `high5-screener`
   - `ALLOWED_CHAT_ID`: 텔레그램 chat_id (기존 시크릿과 동일 값)
5. `wrangler deploy` → 배포 URL(`https://high5-telegram-webhook.[계정].workers.dev`) 확인
6. curl로 Worker 자체가 살아있는지 먼저 확인 (텔레그램 연결 전 독립 테스트):
   ```
   curl -X POST https://high5-telegram-webhook.[계정].workers.dev \
     -H "Content-Type: application/json" \
     -d '{"message":{"chat":{"id":"실제챗아이디"},"text":"명령어확인"}}'
   ```
   → `GitHub API status: 204`가 나와야 정상 (실패하면 텔레그램 연결 전에 먼저 여기서 디버깅)
7. 텔레그램 웹훅 등록:
   ```
   https://api.telegram.org/bot{토큰}/setWebhook?url=https://high5-telegram-webhook.[계정].workers.dev
   ```
8. `https://api.telegram.org/bot{토큰}/getWebhookInfo`로 정상 등록 확인
9. 실제 텔레그램에서 `명령어확인` 보내서 몇 초 내로 답장 오는지 확인

### 다음 세션에서 확인해야 할 것 (v5 추가분)
1. **wrangler secret put이 이번엔 정상적으로 반영되는지 확인** (터틀의 반복 실패 지점)
2. curl 직접 테스트에서 `GitHub API status: 204`가 나오는지 (안 나오면 PAT 권한/이름 확인)
3. 텔레그램 실제 메시지로 몇 초 내 응답 오는지 확인
4. fine-grained PAT 만료 주기(발급 시 설정한 기간) 도래 시 재발급 필요 — 만료일 메모해둘 것
5. 웹훅 등록 후 `telegram_listener.py`(폴링) 워크플로우가 에러 없이 조용히 스킵되는지 확인
   (Actions 로그에 "웹훅이 활성화되어 있어 폴링을 건너뜁니다" 정상 출력되는지)

---

## v3 → v4 변경 이력 (이번 세션) — 터틀식 텔레그램 명령어 전체 도입

터틀 스크리너의 모든 명령어(buy/sell/list/추적시작/추적종료/추적확인/명령어확인)를
high5 구조에 맞게 응용해서 추가함. **응답속도는 5분 폴링으로 채택** (터틀의 웹훅
방식은 Cloudflare Worker+GitHub PAT 인프라가 필요하고 PAT 노출이라는 미해결 보안
이슈가 있었음 — high5는 자동매매가 메인이라 명령어는 보조 기능이므로 5분 폴링으로
충분하다고 판단, 간단하고 안전한 쪽 채택).

1. **신규 `bot_commands.py`**: 터틀의 동명 파일을 응용, 명령어 공통 처리 로직
   - `buy 코드 매수가`: 수동 포지션 등록. 시장 자동판별(`detect_market`: KR=6자리숫자,
     COIN=빗썸 KRW 마켓 실존 확인, 나머지=US), ATR(10일) 자동계산 후 하드스탑 계산
     (`calc_hard_stop` 재사용), 4자리 거래번호 발급 — 자동 진입 파이프라인과 동일한
     계산 로직을 그대로 재사용해서 일관성 유지
   - `sell 거래번호 [매도가]`: 청산 처리. 매도가 생략 시 `fetch_current_price`로
     현재가 자동조회. `status='closed_manual'`로 표시(자동청산 `closed`와 구분,
     `position_check.py`는 `status=='active'`만 감시하므로 두 상태 모두 자연히 제외됨).
     휩쏘 이력에도 승/패 기록
   - `list`: 보유 포지션 목록 (매수가/현재가/손익률/하드스탑/최고가)
   - `코드 추적시작` / `추적종료`(`추적해제`/`추적중지`): **자동 진입 파이프라인과
     완전히 별개인** 수동 감시목록(`tracked.csv`) 등록/해제
   - `추적확인`(`추적목록`): 추적목록 종목들을 그 순간 실시간 재조회해서
     5일고가선 근접도, 3일저가선, 진입가능/관심/관찰중 상태를 보여줌
   - `명령어확인`(`명령어 확인`/`도움말`/`help`/`/help`): 전체 사용법 안내
   - `dispatch(text, pos_df, tracked_df, hist_df)`: 한 줄 명령어 처리
   - `dispatch_lines(...)`: 여러 줄 명령어를 줄 단위로 각각 처리 후 답장을 합쳐서
     발송 (터틀에서 겪었던 "여러 줄 중 첫 줄만 처리되는" 버그를 처음부터 방지,
     실제 테스트로 3줄 동시 명령이 모두 처리됨을 확인함)
2. **`common.py`에 명령어 처리용 공용 함수 추가**:
   - `detect_market(code_raw)`: 코드만 보고 KR/US/COIN 자동 판별
   - `fetch_ohlc(market, code, days)`: 시장별 최근 OHLC 히스토리 조회 (buy/추적확인용)
   - `fetch_current_price(market, code)`: 현재가만 가볍게 조회 (sell 매도가 생략 시)
3. **신규 `storage.py`에 `tracked.csv` 로드/세이브 추가**: `TRACKED_COLUMNS =
   ['market','code','name']`, `load_tracked()`, `save_tracked(df)`
4. **신규 스크립트 `scripts/telegram_listener.py`**: 5분마다 `getUpdates` 폴링,
   `telegram_offset.txt`로 중복처리 방지, 등록된 `chat_id`가 아닌 메시지는 무시,
   `dispatch_lines`로 처리 후 결과를 `positions.csv`/`tracked.csv`/`trade_history.csv`에 반영
5. **신규 워크플로우 `.github/workflows/telegram_listener.yml`** (5분마다)

### 검증한 것 (합성 데이터, 네트워크 우회)
- `buy` → ATR/하드스탑 계산, 포지션 등록 정상
- `list` → 보유 포지션 표시 정상
- `sell`(매도가 생략) → 현재가 자동조회 후 손익률 계산, `status=closed_manual`,
  휩쏘 이력(`loss`) 기록 정상
- `추적시작`/`추적종료`/`명령어확인` 정상
- 3줄 동시 `추적시작` 명령 → 3개 모두 처리됨 (다중 라인 버그 방지 확인)

---

## v2 → v3 변경 이력 (이번 세션) — 터틀식 상세 추적 알림 도입

터틀 스크리너의 "보유종목/집중추적종목 5분 무조건 요약 + 상승하락 추세표시"를 응용:

1. **`common.py`에 `trend_arrow(current, previous)`, `fmt_pct(v)` 신설**
   - 터틀과 동일 스타일: 상승 `🔴▲+값` / 하락 `🔵▼-값` / 보합 `🟡➖보합` / 최초 `🆕`
2. **`positions.csv`에 `last_n_low` 컬럼 추가**: 직전 5분 체크 때의 3일저가선(청산가) 값을
   저장해서, 이번 체크 때 청산가 자체가 오르는지 내리는지 추세 표시 가능해짐
3. **`position_check.py` 5분 요약 강화**: 기존 현재가 추세에 더해
   - **3일저가선(청산가) 추세** 추가 표시
   - **하드스탑까지 남은 거리(%)** 추가 표시 (위험도 체감용, `fmt_pct` 사용)
4. **`watch.csv`에 `last_close` 컬럼 추가**: 관심종목의 직전 체크 대비 현재가 추세
   표시를 위한 필드. `save_watch_for_market`이 시장별 행을 갈아끼울 때도 같은 코드면
   `last_close`를 이어받도록(carry-forward) 구현 — 신규 스캔 때마다 추세가 끊기지 않음
5. **신규 스크립트 `scripts/watchlist_check.py` 추가**: 터틀의 "집중추적종목" 5분
   무조건 요약을 응용, `watch.csv`의 관심종목들도 5분마다 현재가·5일고가선 대비
   근접도·추세를 `🎯 [관심종목 현황]` 헤더로 요약 발송 (상태 전환 자체는 여전히
   `recheck_*.py`가 담당, 이 스크립트는 순수 현황 보고만)
6. **신규 워크플로우 `.github/workflows/watchlist_check.yml`** 추가 (5분마다)
7. `storage.py`에 `save_watch_full(df)` 신설: 행 추가/삭제 없이 필드값만 갱신할 때 사용

---

## v1 → v2 변경 이력

- **청산 로직 전면 교체**: v1의 "목표가 없이 트레일링(최고가-2×ATR)" 방식을
  **"3일 신저가 이탈(채널청산)"** 방식으로 변경 (진입 5일 / 청산 3일, 터틀식 채널
  진입·청산 구조를 초단기 호흡에 맞게 응용)
- **하드스탑 방식 변경**: 기존 "진입가-2×ATR"이 손실폭 대비 너무 크게 느껴진다는
  문제 제기 → **"1.5×ATR(10일) 과 진입가 대비 -7% 중 더 타이트한(가까운) 쪽"**을
  고정 하드스탑으로 채택 (트레일링 아님, 안전판 역할만 함)
- **ATR 계산기간 단축**: 20일 → **10일** (진입5일/청산3일의 짧은 호흡에 맞춤)
- `positions.csv`의 `stop_price`(트레일링) 필드를 `hard_stop_price`(고정)로 대체,
  `highest_price`는 이제 순수 정보성 기록(마일스톤 알림용)으로만 남음

---

## 저장소/봇 설정 (사용자가 직접 준비해야 함)

1. **새 GitHub 저장소** 생성 (터틀과 별도, 예: `high5-screener`)
2. **새 텔레그램 봇**을 BotFather로 새로 발급 (터틀봇과 다른 봇, 만료 없음)
3. 저장소 시크릿 등록: `HIGH5_TELEGRAM_BOT_TOKEN`, `HIGH5_TELEGRAM_CHAT_ID`
4. 이 zip 안의 파일 전체를 저장소 최상위에 커밋/푸시 (경로 착각 주의 —
   `common.py`, `storage.py`는 최상위, `scripts/`, `.github/`는 각각 그 이름의 폴더)

> 카카오톡 알림은 검토 후 기각함: "나에게 보내기" API는 액세스토큰 수시간,
> 리프레시토큰 약 2개월 만료 구조라 방치형 자동화(5분마다 무기한 실행)에 부적합.
> 텔레그램 봇 토큰은 만료가 없어서 그대로 채택.

---

## 전략 핵심 규칙 (v2 확정사항)

| 항목 | 값 |
|---|---|
| 대상 시장 | 국장(코스피) + 미장(S&P500) + 코인(빗썸 KRW) 전부 |
| 진입 기준 | 최근 5거래일 동안 못 넘던 5일 최고가를 오늘 종가로 최초 돌파 (`fresh_entry_signal`) |
| **청산 기준(주 로직)** | **3일 신저가 이탈** (채널청산, 5분마다 저가 기준 장중 체크) |
| **하드스탑(안전판)** | **진입가 − min(1.5×ATR(10일), 진입가×7%)**, 고정값(트레일링 아님) |
| 추격매수 필터 | 진입가(5일 신고가) 대비 0.5% 초과해서 오른 상태면 스킵 |
| 휩쏘 필터 | 직전 거래가 수익(win)이었으면 다음 신규 돌파 스킵, 스킵가 대비 2×ATR 더 유리해지면 강제 진입 (터틀과 동일 철학, ATR은 10일 기준) |
| 관심 기준 | 당일 고가/5일 최고가 ≥ 99% (아직 미돌파) |
| ATR 기간 | **10일** (진입5/청산3의 짧은 호흡에 맞춤, v1의 20일에서 단축) |

### 하드스탑 설계 근거 (다음 세션에서 재검토 시 참고)
- 진입5일/청산3일처럼 호흡이 매우 짧은 시스템에 20일 ATR·2×배수를 그대로 쓰면
  손절폭이 실제 거래 호흡보다 과도하게 넓어짐 → ATR기간을 10일로 단축, 배수도 1.5로 하향
- 자산마다 변동성 편차가 큼(코인 vs 저변동 우량주) → ATR distance와 %(7%) distance
  중 더 타이트한 쪽을 택해서 어느 쪽 자산이든 손실이 한쪽으로 과도하게 커지지 않게 함
- 3일 신저가(채널청산)가 정상 상황의 청산을 담당하고, 하드스탑은 갭하락 등
  채널청산이 못 잡는 극단 상황만 방어 (평소엔 3일 신저가가 먼저 걸릴 것으로 예상)

---

## 파일 구조

```
high5-screener/
├── common.py                    # 진입판정(check_high5_breakout), 채널청산판정(check_channel_exit),
│                                 # 통합판정(check_high5_system, 자동스캔 전용), pick_top_entry,
│                                 # 하드스탑계산(calc_hard_stop, 실제보유종목 전용), 휩쏘필터, 추세표시,
│                                 # 시장판별/시세조회(명령어용), 텔레그램발송
├── storage.py                   # scan.csv / positions.csv / tracked.csv 완전분리 로드-세이브 헬퍼
├── bot_commands.py               # 텔레그램 명령어 공통 처리 (터틀과 동일: buy/sell/list/추적/도움말)
├── requirements.txt
├── cloudflare-worker/            # high5-screener 저장소와 별개로 배포하는 웹훅 브릿지 (배포는 보류 중)
│   ├── index.js
│   └── wrangler.toml
├── data/
│   ├── scan.csv                 # [v7] 자동스캔 신호 캐시 전용 (진입/관심/확정/확정이탈/탈락),
│   │                             # market 컬럼으로 국장/미장/코인 통합. 알림만, 매매 절대 안 함
│   ├── positions.csv            # 실제 보유종목 (buy 명령으로만 생성), market 컬럼으로 통합
│   ├── tracked.csv              # 수동 추적목록 (추적시작/추적종료로 관리), code/market/status
│   ├── trade_history.csv        # 휩쏘필터 이력 — scan.csv 파이프라인(확정/확정이탈) 전용,
│   │                             # positions.csv(실제 매매)와는 완전히 무관
│   └── telegram_offset.txt      # 텔레그램 폴링 오프셋
├── scripts/
│   ├── full_scan_korea.py       # [v7 재작성] 국장 전체스캔, 알림전용(자동매수 없음)
│   ├── full_scan_us.py          # [v7 재작성] 미장 전체스캔, 알림전용
│   ├── full_scan_bithumb.py     # [v7 재작성] 코인 전체스캔, 알림전용
│   ├── recheck_korea.py         # [v7 재작성] 관심→확정→확정이탈 상태머신 + 휩쏘필터, 알림전용
│   ├── recheck_us.py            # [v7 재작성] 상동
│   ├── recheck_bithumb.py       # [v7 재작성] 상동 (24시간)
│   ├── position_check.py        # [v7 재작성] 보유종목 감시, 자동청산 없음(알림만, status=stop_hit)
│   ├── watchlist_check.py       # [v7 수정] scan.csv(signal=='관심') 기반 5분 무조건 현황요약 (🎯)
│   ├── tracked_check.py         # 추적목록(수동) 상태변화 시에만 알림 (터틀 watchlist_check 응용)
│   ├── telegram_listener.py     # 텔레그램 명령어 폴링 리스너 (5분마다, 웹훅 활성 시 자동 스킵)
│   └── webhook_handler.py       # 웹훅으로 받은 명령어 즉시 처리 (웹훅 배포 시에만 트리거됨)
└── .github/workflows/
    ├── full_scan_korea.yml      # 04:00, 11:00 UTC
    ├── full_scan_us.yml         # 19:00, 23:00 UTC
    ├── full_scan_bithumb.yml    # 6시간마다
    ├── recheck.yml              # */5 * * * * (국장/미장/코인 3개 스크립트)
    ├── position_check.yml       # */5 * * * * (data/positions.csv만 커밋)
    ├── watchlist_check.yml      # */5 * * * * (data/scan.csv 커밋)
    ├── tracked_check.yml        # */5 * * * *
    ├── telegram_listener.yml    # */5 * * * * (웹훅 활성 시 사실상 no-op)
    └── telegram_webhook.yml     # repository_dispatch (즉시, 웹훅 배포해야 트리거됨)
```

---

## 데이터 모델 (v7)

### `data/scan.csv` — 자동스캔 신호 캐시 (알림 전용, 매매 없음)
`market,code,name,signal,entry_price,close,high,n_high,n_high_ratio,atr,low,n_low,last_close`
- `signal`: 진입 / 관심 / 확정 / 확정이탈 / 탈락
- `entry_price`: '확정' 전환 시점의 종가 (확정이탈 시 휩쏘 이력 기록에 사용, 실제
  매수가와 무관 — 사용자가 실제로 샀는지 여부와 독립적으로 시스템이 자체 학습함)
- `last_close`: `watchlist_check.py`가 5분마다 갱신하는 직전 현재가 (추세 표시용)
- `save_scan_for_market`: 전체스캔이 재실행돼도 기존 '확정' 종목은 새 결과에 없어도
  보존함 (재확인이 계속 감시할 수 있게, 터틀과 동일 로직)

### `data/positions.csv` — 실제 보유종목 (buy 명령으로만 생성)
`position_id,market,code,name,entry_price,atr_entry,hard_stop_price,highest_price,last_milestone,last_price,last_n_low,status,entry_date`
- `status`: **active**(감시중) / **stop_hit**(매도검토 알림 나감, 여전히 감시중,
  자동으로 안 팔림) / **closed_manual**(sell 명령으로 실제 종료)
- `hard_stop_price`: buy 시점에 1회 계산되어 고정 (트레일링 아님)
- scan.csv와 완전 무관 — scan.csv에서 '진입'/'확정'이 아무리 떠도 여기엔 아무 일도
  안 일어남. 오직 텔레그램 `buy` 명령만이 이 파일에 행을 추가함

### `data/tracked.csv`
`code,market,status` — 변경 없음 (텔레그램 `추적시작`/`추적종료`로만 관리)

### `data/trade_history.csv`
`market,code,last_result,skip_active,skip_price`
- **scan.csv 파이프라인(관심→확정→확정이탈) 전용**. `recheck_*.py`만 이 파일을 읽고 씀.
- `position_check.py`/`bot_commands.py`(실제 buy/sell)는 이 파일을 전혀 건드리지 않음
  (터틀과 동일 — 실제 매매와 자동스캔의 학습은 서로 독립적)

---

## 신호 처리 흐름 (v7, 터틀과 동일한 3단계 분리 구조)

### A. 자동스캔 파이프라인 (알림 전용)
1. **전체스캔**: 5일 신고가 신선돌파 감지 → 추격필터 통과 시 signal='진입', 근접
   시 signal='관심'으로 scan.csv에 기록. 진입신호가 여러 개면 `pick_top_entry`로
   가장 신선한 것 1개만 골라 "매수 검토" 알림(`buy 코드 가격` 안내 포함) 발송.
   기존 '확정' 종목은 이번 결과에 없어도 보존.
2. **재확인(5분, 장중/코인24h)**: scan.csv에서 signal이 관심/확정인 것만 재조회.
   - 기존 '확정' → 3일신저가 이탈이면 '확정이탈'(휩쏘 이력에 승/패 기록, "매도 검토"
     알림), 아니면 '확정유지'
   - 기존 '관심' 중 신선돌파 재확인되면 → 휩쏘필터 통과 시 '확정'("매수 검토" 알림),
     탈락 시 '관심' 유지
3. **관심종목 현황요약(5분, watchlist_check.py)**: scan.csv의 관심 종목들 현재가만
   가볍게 조회해서 무조건 요약(🎯). 상태 판정은 안 함, 순수 보고용.

### B. 실제 보유종목 관리 (수동 매매, 자동 감시)
4. **buy 명령**: 사용자가 알림 보고 직접 입력 → positions.csv에 등록, ATR10 계산해서
   하드스탑(1.5×ATR10/-7% 중 타이트한 쪽) 확정
5. **보유종목 감시(5분, position_check.py)**: 3일신저가 또는 하드스탑 이탈 시
   **"매도 검토" 알림만** 발송, status='stop_hit'으로 변경 (자동으로 안 팔림).
   ATR 마일스톤 도달 시 진행상황 알림. 매 실행마다 무조건 현황 요약(📦), stop_hit은
   "🔴 손절확정 (매도대기)" 태그로 구분 표시.
6. **sell 명령**: 사용자가 직접 입력해야 status='closed_manual'로 실제 종료됨.
   active든 stop_hit이든 상관없이 sell로 찾아서 종료 가능.

### C. 수동 추적목록 (별도 관심 관리)
7. **추적시작/추적종료**: scan.csv/positions.csv와 무관하게 사용자가 지정한 종목만
   별도로 tracked.csv에 등록/해제
8. **추적목록 상태변화 알림(5분, tracked_check.py)**: 상태(진입/관심/청산/관찰중)가
   바뀔 때만 알림. `추적확인` 명령으로 그 순간 실시간 재조회도 가능.

---

## 설계 시 채택한 가정 (다음 세션에서 재검토 필요할 수 있음)

1. **가격 필터 없음**(국장): 후보 과다 문제 생기면 `full_scan_korea.py` 상단
   `PRICE_MIN`/`PRICE_MAX`를 채워서 필터링 가능.
2. **하드스탑 숫자(1.5×ATR10, -7%)는 경험적 기본값**: 실운영 며칠 후 승률/손익비
   보고 조정 여지 있음.
3. **웹 대시보드 없음**.
4. **채널청산과 하드스탑이 동시에 걸리면** 알림 문구에 "동시 이탈"로 표기 (판정
   자체는 둘 중 하나만 걸려도 stop_hit 처리, 동작 차이 없음).
5. **실제 매매(positions.csv)는 휩쏘필터 학습과 무관**: scan.csv 파이프라인 자체의
   신호이력만으로 휩쏘를 학습함 (터틀과 동일 설계 — 사용자가 실제로 샀는지와
   무관하게 시스템 자체 신호 사이클로 판단).

---

## 다음 세션에서 확인해야 할 것

1. 새 저장소/새 텔레그램 봇 생성 + 시크릿 등록 완료 여부
2. **[v7]** 첫 전체스캔 실행 후 scan.csv에 진입/관심 신호가 의도대로 기록되고,
   `buy {code} {price}` 안내 문구가 포함된 알림이 정상 발송되는지 확인
3. **[v7]** recheck 재실행 시 '확정' → '확정이탈' 전환이 정상 동작하고, 3일신저가
   재확인 로직이 실제 장중 데이터로 잘 걸리는지 확인
4. **[v7]** position_check.py가 3일신저가/하드스탑 이탈 시 **자동으로 안 팔고**
   "매도 검토" 알림만 보내는지, status가 stop_hit으로만 바뀌는지 (closed로 바뀌면
   버그) 실운영에서 확인
5. **[v7]** stop_hit 상태에서도 `sell` 명령으로 정상 종료되는지, `list`에
   `[손절확정/매도대기]` 태그로 표시되는지 확인
6. 하드스탑(1.5×ATR10 / -7%) 중 실제로 어느 쪽이 더 자주 채택되는지 며칠 지켜보고
   숫자 조정 필요 여부 판단
7. 휩쏘 필터가 scan.csv 파이프라인 자체 사이클(확정→확정이탈→다음 확정 스킵)에서
   잘 작동하는지 확인
8. 국장 KRX 조회 실패 시 재시도(3회, 15초 간격) 로직이 실제 장애 상황에서 잘 동작하는지
9. `buy`/`sell`/`list`/`추적시작`/`추적종료`/`추적확인`/`명령어확인` 명령어가
   실제 텔레그램에서 5분 내로 정상 응답하는지 확인
10. `telegram_offset.txt` 기반 중복처리 방지가 실제 GitHub Actions 동시실행
    상황에서도 잘 작동하는지 확인

---

## 저장소/봇 정보 (실제 배포된 것, 확인됨)

- GitHub: `harmi6005/high5-screener` (Public)
- 시크릿: `HIGH5_TELEGRAM_BOT_TOKEN`, `HIGH5_TELEGRAM_CHAT_ID` 등록 완료
- 배포 중 겪은 실수와 해결 (다음에 비슷한 실수 방지용 기록):
  1. zip을 풀어서 생긴 폴더 **자체**를 통째로 드래그 업로드 → 저장소 안에
     `high5-screener/high5-screener/...`처럼 폴더가 한 겹 더 생기는 문제 발생
     → 폴더를 열어서 **내용물**을 드래그해야 함
  2. `.github` 폴더가 점(`.`)으로 시작하는 숨김 폴더라서 Windows 탐색기 기본
     설정에서 드래그 시 누락됨 → 탐색기 "보기" 탭에서 "숨김 항목" 체크 후 다시
     업로드하거나, GitHub 웹의 "Create new file"에서 파일명에
     `.github/workflows/파일명.yml`처럼 슬래시 포함 경로를 직접 입력해서
     한 파일씩 생성하는 방법으로 우회 가능
  3. `.github/workflows`가 비어있으면 Actions 탭이 "Get started with GitHub
     Actions" 추천 템플릿 화면만 보여줌 (워크플로우 인식 자체가 안 된 상태라는 신호)

---

## v7 버그 수정 (실제 배포 후 발견) — entry_price/low 필드 누락

첫 배포 후 국내 전체스캔 실행 시 아래 에러로 실패:
```
KeyError: "['entry_price', 'low'] not in index"
```
**원인**: `SCAN_COLUMNS`에는 `entry_price`, `low` 필드가 있는데, `check_high5_system()`이
반환하는 dict와 `full_scan_*.py`가 만드는 행(row) dict에는 이 두 필드가 없었음.
신호가 하나라도 잡히면 그 즉시 컬럼 불일치로 `save_scan_for_market`이 죽음.

**수정**:
1. `common.py`의 `check_high5_system()`이 `check_channel_exit()`의 `low`(오늘 저가)
   값도 함께 반환하도록 수정
2. `full_scan_korea.py`/`full_scan_us.py`/`full_scan_bithumb.py`가 행을 만들 때
   `'entry_price': ''`를 명시적으로 채우도록 수정 (확정 전까지는 빈 값, recheck에서
   '확정' 전환 시 실제 값 채워짐)

**검증**: 신호 0개/1개 케이스, 확정종목 보존 케이스 모두 합성 데이터로 재현 후
정상 동작 확인함.
