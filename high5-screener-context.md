# 5일신고가 · 3일신저가 자동매매 봇 (high5-screener) - 전체 컨텍스트 요약 v5

새 채팅창에서 이 파일을 업로드하고 "이 프로젝트 이어서 작업할게, v5 컨텍스트 파악해줘"라고
하면 바로 이어서 작업 가능. **터틀 스크리너(turtle-screener)와는 완전히 별도의 봇/저장소.**

**코드 수정 규칙: 항상 부분수정이 아닌 전체 파일 재작성 방식으로 진행할 것.**

---

## v4 → v5 변경 이력 (이번 세션) — 즉시응답 웹훅 구축 (터틀의 미해결 숙제 해결)

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
├── common.py                    # 진입판정, 채널청산판정, 하드스탑계산, 휩쏘필터, 추세표시,
│                                 # 시장판별/시세조회(명령어용), 텔레그램발송
├── storage.py                   # positions.csv / watch.csv / tracked.csv 공용 로드-세이브 헬퍼
├── bot_commands.py               # 텔레그램 명령어 공통 처리 (buy/sell/list/추적/도움말)
├── requirements.txt
├── cloudflare-worker/            # [v5 신규] high5-screener 저장소와 별개로 배포하는 웹훅 브릿지
│   ├── index.js                  # 텔레그램 웹훅 → GitHub repository_dispatch 호출
│   └── wrangler.toml             # 배포 설정 (민감정보는 여기 없음, wrangler secret put으로만)
├── data/
│   ├── positions.csv            # 전체 시장 포지션 통합 (market 컬럼으로 구분)
│   ├── watch.csv                # 전체 시장 관심종목 통합 (market 컬럼으로 구분, 자동 파이프라인용)
│   ├── tracked.csv              # 수동 추적목록 (추적시작/추적종료로 관리, 자동과 별개)
│   ├── trade_history.csv        # 휩쏘필터용 거래이력 (market+code 기준)
│   └── telegram_offset.txt      # 텔레그램 폴링 오프셋
├── scripts/
│   ├── full_scan_korea.py       # 국장 전체스캔 (KOSPI, 가격필터 없음)
│   ├── full_scan_us.py          # 미장 전체스캔 (S&P500)
│   ├── full_scan_bithumb.py     # 코인 전체스캔 (빗썸 KRW)
│   ├── recheck_korea.py         # 국장 5분 재확인 (장중에만, 관심→진입 전환 감지)
│   ├── recheck_us.py            # 미장 5분 재확인 (장중에만)
│   ├── recheck_bithumb.py       # 코인 5분 재확인 (24시간)
│   ├── position_check.py        # 포지션 청산체크(3일신저가+하드스탑) + 5분 요약(추세+거리% 포함)
│   ├── watchlist_check.py       # 관심종목 5분 무조건 현황요약 (🎯, 터틀 집중추적종목 응용)
│   ├── telegram_listener.py     # 텔레그램 명령어 폴링 리스너 (5분마다, 웹훅 활성 시 자동 스킵)
│   └── webhook_handler.py       # [v5 신규] 웹훅으로 받은 명령어 즉시 처리
└── .github/workflows/
    ├── full_scan_korea.yml      # 04:00, 11:00 UTC
    ├── full_scan_us.yml         # 19:00, 23:00 UTC
    ├── full_scan_bithumb.yml    # 6시간마다
    ├── recheck.yml              # */5 * * * * (국장/미장/코인 3개 스크립트)
    ├── position_check.yml       # */5 * * * *
    ├── watchlist_check.yml      # */5 * * * *
    ├── telegram_listener.yml    # */5 * * * * (웹훅 활성 시 사실상 no-op)
    └── telegram_webhook.yml     # [v5 신규] repository_dispatch (즉시)
```

---

## 데이터 모델 (v3)

### `data/positions.csv`
`position_id,market,code,name,entry_price,atr_entry,hard_stop_price,highest_price,last_milestone,last_price,last_n_low,status,entry_date`
- `market`: KR / US / COIN
- `status`: active(감시중) / closed(청산됨 — 3일신저가 또는 하드스탑)
- `hard_stop_price`: 진입 시 1회 계산되어 고정, 이후 변하지 않음
- `highest_price`: 순수 정보 기록용 (마일스톤 알림 계산에만 사용, 청산 판정과 무관)
- `last_n_low` **[v3 신규]**: 직전 5분 체크 때의 3일저가선(청산가) 값, 청산가 추세 표시용

### `data/watch.csv`
`market,code,name,close,n_high,n_high_ratio,atr,last_close`
- `last_close` **[v3 신규]**: 직전 5분 체크 때의 현재가, 추세 표시용. `watchlist_check.py`가
  갱신하고, `save_watch_for_market`이 시장별 행을 갈아끼울 때 같은 코드면 이 값을
  이어받아서(carry-forward) 추세 표시가 끊기지 않게 함

### `data/trade_history.csv`
`market,code,last_result,skip_active,skip_price` — v1과 동일 구조

---

## 신호 처리 흐름 (v3)

1. **전체스캔**: 5일 신고가 신선돌파 감지 → 추격필터+휩쏘필터 통과 시
   `entry_price`, `atr_entry`(ATR10), `hard_stop_price`(하이브리드 계산)를 채워서
   포지션 즉시 등록. `highest_price`는 진입가로 초기화.
2. **재확인(5분, 장중/코인24h)**: watch.csv 관심종목만 재조회, 장중 돌파 시 즉시
   포지션 등록 (전체스캔과 동일한 하드스탑 계산 로직 재사용)
3. **포지션 체크(5분)**: 활성 포지션마다 최근 히스토리(20일치) 조회 →
   `check_channel_exit`(3일 신저가)과 하드스탑 이탈 여부를 함께 판정 →
   둘 중 하나라도 걸리면 `status=closed` + 휩쏘 이력 기록 + 청산 알림.
   최고가 갱신 시 마일스톤(ATR배수) 알림도 별도로 발송 (청산과 무관한 정보성 알림).
   매 실행마다 활성 포지션 전체 현황을 무조건 요약 발송 — **[v3]** 현재가 추세,
   **3일저가선(청산가) 추세**, **하드스탑까지 남은 거리(%)** 함께 표시.
4. **[v3 신규] 관심종목 현황요약(5분, 장중/코인24h)**: `watchlist_check.py`가
   watch.csv 전체를 대상으로 현재가만 가볍게 조회해서 5일고가선 대비 근접도와
   현재가 추세를 `🎯 [관심종목 현황]` 헤더로 무조건 요약 발송. 상태 전환(진입/탈락)
   판정은 하지 않음 (그건 `recheck_*.py` 담당) — 순수 보고 전용.

---

## 설계 시 채택한 가정 (다음 세션에서 재검토 필요할 수 있음)

1. **가격 필터 없음**(국장): 후보 과다 문제 생기면 `full_scan_korea.py` 상단
   `PRICE_MIN`/`PRICE_MAX`를 채워서 필터링 가능.
2. **포지션 수 제한 없음**: 조건 통과하는 모든 종목이 각각 포지션으로 등록됨.
3. **텔레그램 명령어 없음**: buy/sell/list 같은 수동 명령 없음, 전량 자동 진입/청산.
4. **웹 대시보드 없음**.
5. **하드스탑 숫자(1.5×ATR10, -7%)는 경험적 기본값**: 실운영 며칠 후 승률/손익비
   보고 조정 여지 있음. 특히 코인처럼 변동성이 아주 큰 자산에서 -7%가 여전히
   크게 느껴지면 %캡을 낮추는 것(예: -5%)을 고려.
6. **채널청산과 하드스탑 우선순위**: 코드상 "둘 다 걸리면 채널청산 우선 표기"로
   처리했지만 실제 청산 처리(포지션 종료)는 둘 중 하나만 걸려도 즉시 발생 — 동작에
   차이는 없고 알림 문구만 다름.

---

## 다음 세션에서 확인해야 할 것

1. 새 저장소/새 텔레그램 봇 생성 + 시크릿 등록 완료 여부
2. 첫 전체스캔 실행 후 진입/관심 분류 및 하드스탑 계산값이 의도대로 나오는지 확인
3. `position_check.py`의 채널청산(3일 신저가) 판정이 실제 장중 데이터로 잘 걸리는지 확인
4. 하드스탑(1.5×ATR10 / -7%) 중 실제로 어느 쪽이 더 자주 채택되는지 며칠 지켜보고
   숫자 조정 필요 여부 판단
5. 휩쏘 필터가 실제 거래 사이클(진입→청산→다음 진입 스킵)에서 잘 작동하는지 확인
6. 국장 KRX 조회 실패 시 재시도(3회, 15초 간격) 로직이 실제 장애 상황에서 잘 동작하는지
7. **[v4]** `buy`/`sell`/`list`/`추적시작`/`추적종료`/`추적확인`/`명령어확인`
   명령어가 실제 텔레그램에서 5분 내로 정상 응답하는지 확인 (합성 데이터로는
   검증했으나 실제 네트워크/실거래 데이터로는 미확인 상태)
8. **[v4]** `telegram_offset.txt` 기반 중복처리 방지가 실제 GitHub Actions
   동시실행 상황에서도 잘 작동하는지 확인 (여러 워크플로우가 동시에 커밋을
   시도하면 git push 충돌 가능성 있음 — 발생 시 재시도 로직 추가 검토)

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
