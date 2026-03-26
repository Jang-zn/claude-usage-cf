# claude-usage

Claude Code CLI의 토큰 사용량을 실시간으로 모니터링하는 터미널 대시보드입니다.

> `/usage` 명령은 순간 스냅샷만 보여줍니다 — 이 앱은 항상 켜두고 자동 갱신됩니다.

---

## 보여주는 것

| 패널 | 내용 |
|------|------|
| **Token Usage** | 오늘/이번 주/이번 달 모델별 사용 토큰 |
| **Quota Status** | 현재 세션 사용률 + 리셋 시간, 주간 한도 현황 |
| **Project Usage** | 프로젝트별 토큰 소비량 순위 |
| **Daily Usage** | 일별 사용량 바 차트 |
| **Cost Estimate** | 모델별 예상 비용 + 캐시 절감액 |
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
claude-usage
```

이것으로 끝입니다. Claude Code 로그인 정보를 자동으로 읽어와서 바로 시작됩니다.

---

## 키 조작

| 키 | 동작 |
|----|------|
| `q` | 종료 |
| `r` | 수동 새로고침 |
| `a` | 계정 전환 (다계정 설정 시) |
| `1` | 오늘 사용량 보기 |
| `7` | 이번 주 사용량 보기 |
| `3` | 이번 달 사용량 보기 |

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
  refresh_interval: 5   # 초
  default_period: "day" # day / week / month
```

---

## 어떻게 데이터를 가져오나요?

- **토큰 사용량** — `~/.claude/projects/` 하위 JSONL 로그 파일을 직접 파싱합니다 (증분 방식, 빠름)
- **Quota 현황** — Anthropic API로 실제 한도값을 역산한 뒤, 이후엔 로컬 토큰 수치로 계산합니다 (30분 주기 + 리셋 시간 도달 시 자동 재동기화)
- **비용 계산** — 공개된 모델별 단가 기준 추정값입니다

---

## 보안

**이 앱은 어떤 정보도 외부로 전송하지 않습니다.**

- 인증 토큰은 **런타임에만 읽습니다** — macOS는 Keychain, Windows/Linux는 `~/.claude/.credentials.json`에서 읽으며 코드나 별도 파일에 저장되지 않습니다
- JSONL 로그는 **로컬에서만 파싱**하며, 내용을 서버로 보내지 않습니다
- Anthropic API (`/api/oauth/usage`) 호출은 **최소화**됩니다 — 한도값 역산 후 로컬 계산, 30분 주기 또는 리셋 시간 도달 시에만 재호출합니다
- 네트워크 없이도 토큰/비용/프로젝트 현황은 모두 로컬에서 동작합니다

소스 코드가 전부 공개되어 있으니 직접 확인하실 수 있습니다.

---

## 참고

- macOS / Windows / Linux 지원 (Claude Code 공식 지원 플랫폼)
- Claude Max / Pro / Team 플랜 모두 동작합니다
- 토큰 수치는 input + output 기준입니다 (cache 토큰 별도)
