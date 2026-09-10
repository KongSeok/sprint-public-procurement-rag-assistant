# 입찰메이트 서빙 이미지 (FastAPI + 웹 UI)
#
# [2026-09-09] 버셀 같은 서버리스는 요청 사이에 메모리가 유지되지 않아서,
# KURE-v1 임베딩 모델(약 2.2GB)을 한 번 올려두고 계속 재사용하는 이 파이프라인과
# 구조적으로 맞지 않았다. 그래서 "상시 떠 있는 컨테이너"를 전제로 하는 이 이미지를
# 만들고 팀이 이미 쓰는 GCP VM에 올린다.
#
# 데이터(data/, output/)와 모델 캐시는 이미지에 굽지 않고 VM 호스트 볼륨으로
# 마운트한다(docker-compose.yml 참고) - 코드를 고쳐 이미지를 다시 빌드해도
# 인덱스/모델을 다시 만들 필요가 없고, 이미지도 그만큼 가볍다.
#
# Python 3.11을 고정한 이유: 전처리에 쓰는 pyhwp가 오래된 패키지라 최신
# 파이썬에서 설치가 깨질 위험이 있어, 실제로 설치가 확인된 버전으로 못 박았다.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    # 컨테이너를 새로 만들어도 모델을 다시 받지 않도록 이 경로를 볼륨으로 마운트한다
    HF_HOME=/root/.cache/huggingface

WORKDIR /app

# torch는 CPU 전용 휠로 먼저 설치한다. 그냥 두면 sentence-transformers가 PyPI
# 기본 휠(CUDA 포함, 2GB+)을 끌어와서 이미지가 몇 배로 커진다.
# GPU(L4)를 쓰기로 하면 이 줄을 CUDA 베이스 이미지 + 기본 휠로 바꾸면 된다.
# 사내/VM 네트워크에서 download.pytorch.org가 막혀 있을 수 있어, 실패하면 일반
# PyPI 휠로 폴백한다 - 이미지가 커질 뿐 동작에는 문제가 없고, 빌드가 통째로
# 실패하는 것보다 낫다(폴백이 탔는지는 빌드 로그에서 바로 보인다).
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch \
    || (echo "[build] CPU 전용 인덱스 실패 -> 기본 PyPI 휠로 폴백합니다(이미지가 커집니다)" && pip install torch)

COPY requirements.txt ./
RUN pip install -r requirements.txt

# 코드만 복사한다 - data/ 와 output/ 은 볼륨 마운트, .env 는 compose가 환경변수로
# 넘긴다(.dockerignore 참고 - API 키를 이미지에 굽지 않기 위함).
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY app/ ./app/

EXPOSE 8000

# 무거운 자원은 전부 지연 로드라 기동 자체는 몇 초면 끝난다 - 헬스체크도 바로 통과한다.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health').read()" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
