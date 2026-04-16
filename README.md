# claude-usage

Claude Code CLI의 토큰 사용량·비용·생산성 지표를 실시간으로 보여주는 터미널 대시보드입니다.

> `/usage` 명령은 순간 스냅샷만 보여줍니다 — 이 앱은 항상 켜두고 자동 갱신됩니다.

---

## 보여주는 것

| 패널 | 내용 |
|------|------|
| **Token Usage** | 오늘/이번 주/이번 달 모델별 사용 토큰 + **One-shot 성공률** |
| **Quota Status** | 5시간 윈도우 사용률 + 리셋 시간, 주간 한도 현황 |
| **Project Usage** | 프로젝트별 토큰 소비량 순위 (`c`로 Category 토글) |
| **Category Panel** | 13 카테고리별 작업 분류 (Coding/Debug/Feature/Testing…) + Top Tools |
| **Daily Usage** | 일별 사용량 바 차트 |
| **Cost Estimate** | 모델별 예상 비용 + 캐시 절감액 (LiteLLM 기반 동적 가격) |
| **Active Sessions** | 현재 실행 중인 Claude Code 세션 목록 |

---

## 설치

**요구 사항**
- Python 3.10+
- Claude Code가 설치되어 로그인된 상태 (macOS / Windows / Linux)

```bash
pip install git+https://github.com/Jang-zn/claude-usage-cf.git
```

또는 로컬에서 직접 설치:

```bash
git clone https://github.com/Jang-zn/claude-usage-cf.git
cd claude-usage-cf
pip install -e .
```

---

## 실행

```bash
claude-usage                        # TUI 대시보드
claude-usage export --format json   # JSON/CSV 내보내기
claude-usage menubar install        # macOS SwiftBar 메뉴바 위젯 설치
```

Claude Code 로그인 정보를 자동으로 읽어와서 바로 시작됩니다.

---

## 키 조작

| 키 | 동작 |
|----|------|
| `q` | 종료 |
| `r` | 수동 새로고침 |
| `a` | 계정 전환 (다계정 설정 시) |
| `c` | Project ↔ Category 패널 토글 |
| `1` | 오늘 사용량 보기 |
| `7` | 이번 주 사용량 보기 |
| `3` | 이번 달 사용량 보기 |

---

## 내보내기 (Export)

```bash
# 기본: 이번 주 데이터를 ~/.claude-usage/exports/ 에 CSV로 저장
claude-usage export

# JSON 포맷 + 경로 지정
claude-usage export --format json --out ~/usage.json

# 기간 선택
claude-usage export --period month
```

CSV에는 `section` 열로 `model`, `daily`, `project`, `category` 각 집계가 구분되어 한 파일에 들어갑니다. JSON에는 `models`, `daily`, `projects`, `categories`, `one_shot_rate`가 포함됩니다.

---

## 메뉴바 위젯 (macOS)

[SwiftBar](https://swiftbar.app) 가 설치되어 있으면 메뉴바에 주간 토큰 사용률을 상시 표시할 수 있습니다.

```bash
claude-usage menubar install --interval 1m   # 1분마다 갱신
claude-usage menubar uninstall
```

플러그인은 stdlib만 사용하는 독립 스크립트라 이 앱이 실행 중이지 않아도 동작합니다.

---

## 설정 (선택)

설정 파일 없이도 동작하지만, 커스텀하려면:

```bash
mkdir -p ~/.config/claude-usage
cp config.example.yaml ~/.config/claude-usage/config.yaml
```

```yaml
# ~/.config/claude-usage/config.yaml

accounts:
  - name: "Personal"
    claude_home: "~/.claude"
  # 다계정 사용 시 추가 가능
  # - name: "Work"
  #   claude_home: "~/.claude-work"

limits:
  - model: "opus"
    weekly_tokens: 45_000_000
  - model: "sonnet"
    weekly_tokens: 45_000_000
  - model: "haiku"
    weekly_tokens: 45_000_000

display:
  refresh_interval: 5    # 초
  default_period: "day"  # day / week / month
  show_cost: true        # false 설정 시 Cost 패널 숨김

menubar:
  enabled: false
  interval: "1m"         # 30s / 1m / 5m / 1h
```

---

## 어떻게 데이터를 가져오나요?

- **토큰 사용량** — `~/.claude/projects/` 하위 JSONL 로그를 증분 파싱합니다. 메시지 ID 기반 dedup으로 중복 집계를 방지하고, `subagents/` 하위 로그도 함께 스캔합니다.
- **Quota 현황** — Anthropic API로 실제 한도값을 역산한 뒤, 이후엔 로컬 토큰 수치로 계산합니다 (30분 주기 + 리셋 시간 도달 시 자동 재동기화)
- **비용 계산** — [LiteLLM 가격 DB](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json)를 24시간 캐시로 다운로드해 **모델별 정확한 단가**를 적용합니다. 오프라인 시 하드코딩된 fallback 테이블 사용. `server_tool_use.web_search_requests` 비용도 포함됩니다.
- **작업 분류** — `tool_use` 패턴과 첫 사용자 메시지 키워드로 13 카테고리 결정론적 분류 (LLM 호출 없음).
- **One-shot 성공률** — edit turn(`Edit`/`Write`/`MultiEdit`/`NotebookEdit`) 중 같은 세션에서 30초 이내 추가 edit이 없는 비율.

---

## 보안

**이 앱은 어떤 정보도 외부로 전송하지 않습니다.**

- 인증 토큰은 **런타임에만 읽습니다** — macOS는 Keychain, Windows/Linux는 `~/.claude/.credentials.json`에서 읽으며 코드나 별도 파일에 저장되지 않습니다
- JSONL 로그는 **로컬에서만 파싱**하며, 내용을 서버로 보내지 않습니다
- Anthropic API (`/api/oauth/usage`) 호출은 **최소화**됩니다 — 한도값 역산 후 로컬 계산, 30분 주기 또는 리셋 시간 도달 시에만 재호출합니다
- LiteLLM 가격 DB는 공개 JSON 파일만 다운로드하며 토큰/사용 데이터는 전송하지 않습니다
- 네트워크 없이도 토큰/비용/프로젝트 현황은 모두 로컬에서 동작합니다

소스 코드가 전부 공개되어 있으니 직접 확인하실 수 있습니다.

---

## 참고

- macOS / Windows / Linux 지원 (Claude Code 공식 지원 플랫폼)
- Claude Max / Pro / Team 플랜 모두 동작합니다
- 토큰 수치는 용도에 따라 분리되어 있습니다:
  - **ITPM/쿼터 윈도우**: input + output + cache_creation (cache_read 제외)
  - **비용 계산**: input + output + cache_read + cache_creation (모두 포함)
