<p align="center">
    <img src="https://raw.githubusercontent.com/tropass-ai/tropass-sdk/main/logo.svg" width="350">
</p>
<br>
<p align="center">
    <a href="https://codecov.io/gh/tropass-ai/tropass-sdk" target="_blank"><img src="https://codecov.io/gh/tropass-ai/tropass-sdk/branch/main/graph/badge.svg"></a>
    <a href="https://pypi.org/project/tropass-sdk/" target="_blank"><img src="https://img.shields.io/pypi/pyversions/tropass-sdk"></a>
    <a href="https://pypi.org/project/tropass-sdk/" target="_blank"><img src="https://img.shields.io/pypi/v/tropass-sdk"></a>
    <a href="https://pypistats.org/packages/tropass-sdk" target="_blank"><img src="https://img.shields.io/pypi/dm/tropass-sdk"></a>
</p>

**tropass-sdk** — это инструмент для разработки и управления ML-моделями на платформе Тропасс.

---

## 📦 Установка


```bash
# Для pip
pip install tropass-sdk[server]

# Для uv
uv add tropass-sdk[server]

# Для poetry
poetry add tropass-sdk[server]

```

---

## 🛠 Подготовка приложения

Для инициализации сервера достаточно передать функцию предсказания в класс `ModelServer`.

### Ключевые требования:
* Функция предсказания обязана принимать три аргумента `model_input`, `common_resources` и `request_metadata`.
* Функция предсказания обязана возвращать схему ответа модели `MLModelResponseSchema`.
* Инстанс `ModelServer` обязан находиться в файле `main.py` в корне проекта.

```python
from tropass_sdk.server import ModelServer
from tropass_sdk.schemas.model_contract_schema import MLModelRequestMetadataSchema, MLModelRequestSchema, MLModelResponseSchema

def predict_handler(
    model_input: dict[str, list[typing.Any]],
    common_resources: dict[str, typing.Any],
    request_metadata: MLModelRequestMetadataSchema | None = None,
) -> MLModelResponseSchema:
    # Логика инференса модели
    return MLModelResponseSchema(panel_items=[])

server = ModelServer(
    model_func=predict_handler,
    model_name="my_model",
    model_description="Production model description",
    model_version="1.0.0",
    debug=False
)

```

---

## ⚡ Варианты запуска

Для запуска создайте экземпляр приложения c помощью метода `build_application`. Важно! Имя приложения обязательно должно быть `application`:

```python
application = server.build_application()

```

Запуск: `uvicorn main:application --host 0.0.0.0 --port 8000 --workers 4`

---

## 🔍 Мониторинг и наблюдаемость

Благодаря интеграции с [microbootstrap](https://github.com/community-of-python/microbootstrap), сервис из коробки поддерживает:

* **Метрики:** Доступны по эндпоинту `/metrics` в формате Prometheus.
* **Health Checks:** Проверка состояния сервиса доступна по пути `/health`.
* **Логирование:** Структурированные логи готовы к сбору в ELK/Loki.

---
