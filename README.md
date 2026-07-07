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
* Метаданные запроса передаются внутри `model_input["request_metadata"]`; аргумент `request_metadata` сохранен для совместимости.
* Функция предсказания обязана возвращать схему ответа модели `MLModelResponseSchema`.
* Инстанс `ModelServer` обязан находиться в файле `main.py` в корне проекта.

```python
from tropass_sdk.server import ModelServer
from tropass_sdk.schemas.model_contract_schema import MLModelRequestMetadataSchema, MLModelResponseSchema

def predict_handler(
    model_input: dict[str, typing.Any],
    common_resources: dict[str, typing.Any],
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

### Метаданные запроса

`ModelServer` автоматически извлекает метаданные из HTTP-заголовков запроса к `/prediction` и добавляет их в
`model_input` по ключу `request_metadata`.

Поддерживаемые заголовки:

* `X-User-ID` — идентификатор пользователя. Доступен как `model_input["request_metadata"]["user_id"]`.
* `X-User-Locale` — локаль пользователя. Доступна как `model_input["request_metadata"]["locale"]`, значение по умолчанию — `ru`.
* `X-User-Api-Token` — API-токен пользователя. Доступен как `model_input["request_metadata"]["user_api_token"]`.

Пример использования:

```python
def predict_handler(
    model_input: dict[str, typing.Any],
    common_resources: dict[str, typing.Any],
) -> MLModelResponseSchema:
    request_metadata = model_input["request_metadata"]
    user_id = request_metadata["user_id"]
    locale = request_metadata["locale"]

    # Логика инференса модели с учетом пользователя и локали
    return MLModelResponseSchema(panel_items=[])
```

После обработки заголовков `model_input` получает такой вид:

```python
{
    "input_name": ["input_value"],
    "request_metadata": {
        "user_id": "user_id",
        "locale": "ru",
        "user_api_token": "token",
    },
}
```

## ⚡ Варианты запуска

Для запуска создайте экземпляр приложения c помощью метода `build_application`. Важно! Имя приложения обязательно должно быть `application`:

```python
application = server.build_application()
```

Запуск: `uvicorn main:application --host 0.0.0.0 --port 8000 --workers 4`

## 🌉 Клиент для вызова моделей через Gateway

`GatewayClient` — асинхронный клиент для вызова моделей через Gateway. Клиент сам создает HTTP-соединение,
добавляет приватный токен в заголовок `Authorization: Bearer ...`, выполняет retry через `stamina` и защищает вызов circuit breaker
через `circuitbreaker`.

```python
import typing
import uuid

from tropass_sdk.client import GatewayClient


async def call_gateway_model() -> dict[str, typing.Any]:
    async with GatewayClient(
        gateway_url="https://api.tropass.me",
        gateway_api_token="private-token",
    ) as gateway_client:
        return await gateway_client.call_model(
            model_id=uuid.UUID("00000000-0000-0000-0000-000000000123"),
            model_request_data={
                "input_name": ["input-value"]
            },
        )
```

`call_model` отправляет запрос на `api/rpc/call-model` в формате:

```python
{
    "model_id": "00000000-0000-0000-0000-000000000123",
    "model_request_data": {
        "input_name": ["input-value"]
    },
}
```

Для настройки клиента можно передать `GatewayClientConfig` в аргумент `client_config`.

Параметры конфигурации:

* `timeout_seconds` — HTTP timeout одного запроса к Gateway.
* `retry_attempts` — максимальное количество попыток выполнить запрос.
* `retry_timeout_seconds` — общий лимит времени на retry-цикл.
* `retry_wait_exp_base` — база экспоненциального роста паузы между retry.
* `circuit_failure_threshold` — количество неуспешных вызовов до открытия circuit breaker.
* `circuit_recovery_seconds` — время до попытки восстановить circuit breaker.
* `circuit_success_threshold` — зарезервирован для совместимости конфигурации.

Метод возвращает `dict` с ответом Gateway или выбрасывает `GatewayCallError`.

Оригинальная причина ошибки доступна через `__cause__`: например открытый circuit breaker, некорректный JSON,
HTTP-ошибка или ошибка транспорта после всех retry.


## 🔍 Мониторинг и наблюдаемость

Благодаря интеграции с [microbootstrap](https://github.com/community-of-python/microbootstrap), сервис из коробки поддерживает:

* **Метрики:** Доступны по эндпоинту `/metrics` в формате Prometheus.
* **Health Checks:** Проверка состояния сервиса доступна по пути `/health`.
* **Логирование:** Структурированные логи готовы к сбору в ELK/Loki.

---
