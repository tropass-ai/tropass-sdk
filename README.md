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
    debug=False,
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
добавляет приватный токен в заголовок `Authorization: Bearer ...`, отправляет задачу через v2-протокол
Gateway (submit + polling), выполняет retry submit через `stamina` и защищает submit circuit breaker
через `circuitbreaker`. Polling скрыт внутри клиента.

### Автоматический режим

`call_model` отправляет запрос, получает `task_id`, опрашивает результат и возвращает финальный payload.
Сигнатура сохранена для совместимости — бизнес-код переписывать не нужно.

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
            model_request_data={"input_name": ["input-value"]},
        )
```

Внутри `call_model`:

1. генерирует `Idempotency-Key` (uuid4) и отправляет `POST api/rpc/call-model` с заголовком
   `Tropass-Model-Call-Version: 2`. Тело — форма с полем `model_payload`, содержащим JSON-строку
   `{model_id, model_request_data}`; при передаче файлов тело становится `multipart/form-data`,
   файлы уходят в поле `files`;
2. получает `{task_id, status: "distributed"}`;
3. опрашивает `GET api/rest/model-tasks/{task_id}` до терминального статуса;
4. возвращает поле `result` финального ответа.

Retry submit переиспользует тот же `Idempotency-Key`, поэтому дубликаты задач не создаются.

### Передача файлов

`call_model` и `submit_model_task` принимают опциональный keyword-аргумент `files` — список `GatewayFile`.
Содержимое файла передается как `bytes`, поэтому retry submit отправляет его повторно без потерь.

```python
import uuid

from tropass_sdk.client import GatewayClient, GatewayFile


async def call_model_with_files() -> None:
    async with GatewayClient(
        gateway_url="https://api.tropass.me",
        gateway_api_token="private-token",
    ) as gateway_client:
        await gateway_client.call_model(
            model_id=uuid.UUID("00000000-0000-0000-0000-000000000123"),
            model_request_data={"input_name": ["input-value"]},
            files=[
                GatewayFile(
                    file_name="report.csv",
                    file_content=b"column\nvalue\n",
                    content_type="text/csv",
                ),
            ],
        )
```

`content_type` опционален: если не указать, его определит `httpx`.

### Ручной lifecycle

Для низкоуровневого управления задачей доступны три метода:

```python
from tropass_sdk.client import GatewayClient


async def manual_lifecycle() -> None:
    async with GatewayClient(
        gateway_url="https://api.tropass.me",
        gateway_api_token="private-token",
    ) as gateway_client:
        submission = await gateway_client.submit_model_task(
            model_id=model_id,
            model_request_data={"input_name": ["input-value"]},
        )
        task_id = uuid.UUID(submission.task_id)

        task = await gateway_client.fetch_model_task(task_id)

        result = await gateway_client.wait_for_model_task(task_id)
```

* `submit_model_task` — отправляет задачу, возвращает `{task_id, status}`. Параметр `idempotency_key`
  опционален: без него ключ генерируется автоматически. Параметр `files` — опциональный список `GatewayFile`.
* `fetch_model_task` — однократный poll, возвращает текущий статус задачи.
* `wait_for_model_task` — poll-loop до терминального статуса, возвращает `result`.

### Конфигурация

Для настройки клиента передайте `GatewayClientConfig` в аргумент `client_config`.

Параметры конфигурации:

* `http_timeout_seconds` — HTTP timeout одного запроса (submit/poll).
* `result_deadline_seconds` — общий deadline ожидания результата модели в `call_model`/`wait_for_model_task`.
* `poll_interval_seconds` — интервал между poll-запросами (fallback, т.к. Gateway не возвращает `Retry-After`).
* `retry_attempts` — количество попыток submit/poll при транзиентных ошибках.
* `retry_timeout_seconds` — общий лимит времени на retry-цикл одного запроса.
* `retry_wait_exp_base` — база экспоненциального роста паузы между retry.
* `circuit_failure_threshold` — количество неуспешных submit до открытия circuit breaker.
* `circuit_recovery_seconds` — время до попытки восстановить circuit breaker.
* `circuit_success_threshold` — зарезервирован для совместимости конфигурации.

Circuit breaker оборачивает только submit. Pending-статусы poll (`distributed`, `processing_started`)
не считаются ошибками и не открывают breaker.

### Исключения

Все ошибки наследуются от `GatewayClientError`:

* `GatewayCallError` — общий сбой вызова (транспорт, 5xx, auth, `processing_error`).
* `GatewayCircuitOpenError` — submit circuit breaker открыт.
* `GatewayTaskTimeoutError` — задача не завершена в пределах `result_deadline_seconds`.
* `GatewayTaskNotFoundError` — задача не найдена или принадлежит другому пользователю (404 на poll).
* `GatewayIdempotencyConflictError` — `Idempotency-Key` переиспользован с другим payload (409 на submit).
* `GatewayResponseError` — некорректный JSON или схема ответа Gateway.
* `GatewayClientConfigValidationError` — невалидная конфигурация клиента.

Оригинальная причина ошибки доступна через `__cause__`.


## 🔍 Мониторинг и наблюдаемость

Благодаря интеграции с [microbootstrap](https://github.com/community-of-python/microbootstrap), сервис из коробки поддерживает:

* **Метрики:** Доступны по эндпоинту `/metrics` в формате Prometheus.
* **Health Checks:** Проверка состояния сервиса доступна по пути `/health`.
* **Логирование:** Структурированные логи готовы к сбору в ELK/Loki.

---
