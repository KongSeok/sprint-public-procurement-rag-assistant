# Streamlit 팀 시연 방법

Streamlit 서버는 GCP VM의 `127.0.0.1:8010`에서 한 번만 실행한다. 포트를
인터넷 전체에 공개하지 않고 각 팀원이 자신의 VM 계정으로 SSH 터널을 열어
접속한다. OpenAI API 키는 서버의 `.env`에만 남고 팀원 PC로 전달되지 않는다.

SSH 터널 없이 보여줄 때는 아래의 `Cloudflare Quick Tunnel`을 사용한다.
이 방식은 시연용 임시 HTTPS 주소를 만들며, 도메인이나 GCP 인바운드
방화벽 개방이 필요 없다.

## 1. 서버 담당자

```bash
cd ~/sprint-public-procurement-rag-assistant
git switch develop
git pull --ff-only origin develop
bash scripts/run_streamlit_team_demo.sh
```

이 터미널은 시연 중 닫지 않는다.

## 2. 팀원 접속

각 팀원은 자신의 PC 터미널에서 아래 명령을 실행한다. `<VM_USER>`에는 본인의
VM 계정명, `<VM_EXTERNAL_IP>`에는 현재 VM 외부 IP를 넣는다.

```bash
ssh -L 8010:127.0.0.1:8010 <VM_USER>@<VM_EXTERNAL_IP>
```

Windows에서 별도 SSH 키를 쓰는 경우:

```powershell
ssh -i "$env:USERPROFILE\.ssh\개인키파일명" `
  -L 8010:127.0.0.1:8010 `
  <VM_USER>@<VM_EXTERNAL_IP>
```

연결을 유지한 채 브라우저에서 `http://127.0.0.1:8010`을 연다. 이 주소는 각
팀원의 자기 PC를 가리키지만 SSH 터널을 통해 같은 GCP Streamlit 서버로 연결된다.

## SSH 없이 링크로 공유

1. GCP VM에 `cloudflared`가 없으면 한 번만 설치한다.

```bash
curl -L -o /tmp/cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i /tmp/cloudflared.deb
cloudflared version
```

2. 위 1번처럼 Streamlit을 실행한 터미널을 유지한다.
3. GCP에 두 번째 터미널을 열고 실행한다.

```bash
cd ~/sprint-public-procurement-rag-assistant
bash scripts/share_streamlit_demo.sh
```

4. 출력된 `https://....trycloudflare.com` 주소와 시연 암호를 팀원에게
   공유한다. 팀원은 SSH 없이 브라우저만으로 접속한다.
5. 시연이 끝나면 두 터미널에서 `Ctrl+C`로 Streamlit과 터널을 종료한다.

Quick Tunnel 주소는 다시 실행할 때 바뀐다. 고정 주소가 필요하면 이후
관리형 Cloudflare Tunnel이나 리버스 프록시로 전환한다.

## 화면 구성

- `전체 문서 찾기`: 통합 RAG, 복합 메타데이터 필터, VLM 캐시, 검색 근거
- `문서 한 건 빠른 검토`: 문서명 검색, 11종 빠른 질문, 누적 대화, 후보 원문,
  선택적 AI 요약, 실패 후 재시도, 선택 문서 범위 자유 질문

## 문제 해결

- 연결 거부: 서버 담당자의 Streamlit 터미널이 실행 중인지 확인한다.
- 포트 사용 중: 팀원 PC에서 로컬 포트만 `8011` 등으로 바꾼다.
  `ssh -L 8011:127.0.0.1:8010 ...` 후 `http://127.0.0.1:8011`로 접속한다.
- 이전 화면: 서버에서 최신 `develop`을 pull한 뒤 Streamlit을 재시작한다.
