#!/bin/sh
set -e

echo "Применяю миграции БД…"
alembic upgrade head

if [ "${SEED_DEMO:-false}" = "true" ]; then
    echo "Заливаю демо-каталог (если база пуста)…"
    python -m scripts.seed
fi

exec python -m app
