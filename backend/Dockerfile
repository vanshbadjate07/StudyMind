# StudyMind backend.
#
# python:3.12-slim has official linux/amd64 AND linux/arm64 images, so this
# builds natively on Apple Silicon and on an x86 host without emulation -
# which is the whole point of pinning this base rather than something that
# only ships amd64.
FROM python:3.12-slim

# PYTHONDONTWRITEBYTECODE: no .pyc litter in a layer that is read-only anyway.
# PYTHONUNBUFFERED: logs appear immediately instead of being held in a pipe
# buffer, which is what makes a container's logs useless when it crashes.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# libgomp1 is needed by onnxruntime (pulled in by chromadb) and by torch.
# Installed as a runtime library only; no compilers, because every Python
# dependency here ships prebuilt wheels for both architectures.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Requirements are copied and installed before the application code, so a
# code change does not invalidate the dependency layer. That layer takes
# minutes to rebuild (torch alone is hundreds of megabytes); the code layer
# takes seconds.
COPY requirements.txt .
# torch is installed first, from the CPU-only wheel index. Left to the
# default index, torch on linux pulls the full CUDA stack - cuDNN alone is
# ~600MB - which is several gigabytes of GPU libraries no free CPU host can
# use. Installing the cpu build up front satisfies sentence-transformers'
# torch requirement, so the requirements install below does not replace it.
RUN pip install --no-cache-dir torch==2.15.0 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

# A non-root user, and one with uid 1000 specifically: Hugging Face Spaces
# runs containers as uid 1000 and mounts persistent storage owned by it, so
# matching here avoids a permission error on the first write. /app changes
# hands too, so the app can create its data directory at startup.
RUN useradd --create-home --uid 1000 studymind && chown studymind:studymind /app

# HF_HOME points the sentence-transformers cache somewhere the non-root
# user owns; without it the download lands in a root-owned directory the
# app cannot write to.
ENV HF_HOME=/home/studymind/.cache/huggingface
USER studymind

# Download the embedding model at BUILD time, and BEFORE the code is
# copied, for two separate reasons. At build time rather than first
# request: a free host's cold start otherwise pays a ~90MB download before
# the first upload can do anything, which reads as the app being broken.
# Before the code copy: this layer only depends on the installed packages,
# so an ordinary code change rebuilds in seconds instead of re-downloading
# the model every time.
RUN python -c "from sentence_transformers import SentenceTransformer; \
SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

COPY --chown=studymind:studymind . .

# Created ahead of time so a bind or named volume mounted here inherits a
# directory the app user owns.
RUN mkdir -p /app/data

# PORT rather than a fixed 8000: Hugging Face Spaces expects 7860, Render and
# Fly inject their own, and docker-compose sets 8000. One image serves all of
# them instead of needing a variant per host.
ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

# Shell form so ${PORT} is expanded at run time. Schema migrations run on
# startup inside the app's lifespan, so there is no separate migrate step to
# forget: a fresh database is built and an existing one upgraded by the act
# of starting.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
