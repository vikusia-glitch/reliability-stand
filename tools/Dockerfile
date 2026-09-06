# Контейнер с инструментами разработки.
#
# Всё, что нужно для работы с репозиторием, кроме самого Docker:
# Python с тестами, promtool для правил алертов, Ansible для
# развёртывания. Позволяет ничего не ставить на машину — на хосте
# нужен только Docker.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

ARG PROMETHEUS_VERSION=3.1.0

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

# promtool кладём из релиза Prometheus: он же используется в CI,
# значит проверка правил локально и в CI делается одним бинарём.
RUN arch="$(dpkg --print-architecture)" \
 && curl -fsSL "https://github.com/prometheus/prometheus/releases/download/v${PROMETHEUS_VERSION}/prometheus-${PROMETHEUS_VERSION}.linux-${arch}.tar.gz" \
    -o /tmp/prom.tgz \
 && tar -xzf /tmp/prom.tgz -C /tmp \
 && mv "/tmp/prometheus-${PROMETHEUS_VERSION}.linux-${arch}/promtool" /usr/local/bin/ \
 && rm -rf /tmp/prom.tgz "/tmp/prometheus-${PROMETHEUS_VERSION}.linux-${arch}"

COPY service/requirements-dev.txt /tmp/requirements-dev.txt
COPY service/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements-dev.txt \
 && pip install ansible-core ansible-lint

WORKDIR /work
CMD ["bash"]
