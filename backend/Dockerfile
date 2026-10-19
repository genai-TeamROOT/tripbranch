FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/opt/huggingface

WORKDIR /app

# CPU 전용 torch를 먼저 받는다. PyPI 기본 wheel은 CUDA 런타임을 함께 끌고 와
# 이미지가 GB 단위로 불어나는데, EC2에는 GPU가 없어 그 용량이 전부 낭비다.
# 아래 프로젝트 설치는 이미 만족된 torch를 그대로 쓴다.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch

# 의존성 레이어를 코드와 분리한다. 코드 한 줄 고칠 때마다 torch를 다시 받으면
# CI 한 번에 수 분이 날아간다. 빈 패키지로 먼저 설치해 의존성만 굳힌 뒤,
# 실제 코드는 아래에서 덮어쓴다.
COPY pyproject.toml ./
RUN mkdir -p app && touch app/__init__.py \
 && pip install --no-cache-dir -e ".[embeddings,mood]"

# 모델 가중치를 빌드 시점에 굽는다. 안 그러면 컨테이너가 새로 뜰 때마다
# Hugging Face Hub에서 2GB를 받고, 허브가 죽으면 서버도 못 뜬다.
RUN python -c "\
from sentence_transformers import SentenceTransformer; \
SentenceTransformer('jhgan/ko-sroberta-multitask'); \
from transformers import AutoModel, AutoProcessor; \
AutoProcessor.from_pretrained('google/siglip2-base-patch16-224'); \
AutoModel.from_pretrained('google/siglip2-base-patch16-224')"

COPY app/ ./app/
COPY resources/ ./resources/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
