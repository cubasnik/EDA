# EDA — Enhanced Dynamic Activation

Виртуальный сетевой элемент (VNE) с движком динамической активации сервисов —
идейный аналог промышленных платформ динамической активации сервисов, реализованный
под нейтральным именем и с полностью открытой реализацией. Разворачивается как
обычный сетевой элемент на OpenStack (Nova instance / Docker), управляется через
REST API и CLI.

Архитектура сверена с типовым описанием отраслевых EDA-платформ (функциональные
блоки Inbound Interfaces / OAM / Activation Core / Activation Support / Security &
Connectivity / Data) — см. `docs/ARCHITECTURE.md` для таблицы соответствий.

## Что внутри

- **REST API** (FastAPI) — северный интерфейс элемента: шаблоны сервисов,
  активации, управляемые сетевые элементы, алармы, health/version/metrics.
- **eda-cli** — тонкий CLI-клиент поверх этого же API (то есть всё, что может
  оператор через CLI, может и внешняя OSS/BSS-система через API).
- **Движок активации** — симулированный workflow с состояниями
  `CREATED → VALIDATING → ACTIVATING → ACTIVE/FAILED`, деактивацией, ручным и
  автоматическим retry.
- **Mutex по целевому NE** — конкурентные активации на один и тот же сетевой
  элемент (или "self", если `ne_id` не указан) сериализуются; второй запрос
  получает `409`, пока первый не завершится.
- **Блокировка NE (maintenance mode)** — элемент можно перевести в состояние
  "заблокирован"; новые активации на него не выполняются сразу, а встают в
  `HELD` и автоматически возобновляются при разблокировке.
- **Пакетная активация, webhook-уведомления, алармы, Prometheus-метрики,
  опциональная аутентификация по API-ключу** — подробнее ниже.
- **Docker-образ + Heat-шаблон** — готовый способ развернуть элемент как VM
  на OpenStack (Nova/Neutron/Heat).

## Быстрый старт (локально)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# запустить API-сервер (по умолчанию слушает 0.0.0.0:8080, без аутентификации)
eda-server
```

Открыть `http://localhost:8080/docs` — интерактивная OpenAPI-документация.

Либо через Docker:

```bash
docker compose -f docker/docker-compose.yml up --build
```

## Использование CLI

CLI обращается к API по адресу из `--api-url` / переменной `EDA_API_URL`
(по умолчанию `http://localhost:8080`). Если на сервере включена
аутентификация (`EDA_API_KEY`), передавайте ключ через `--api-key` / `-k`
или переменную `EDA_API_KEY`.

```bash
# состояние элемента
eda-cli health

# создать шаблон активации (аналог "Service Model" в EDA)
eda-cli template create --name vlan-activation \
    --step allocate_resources --step configure_vlan --step verify_activation
# либо из файла:
eda-cli template create --file examples/template_vlan_activation.json

eda-cli template list

# зарегистрировать управляемый сетевой элемент (опционально)
eda-cli ne register --name core-router-1 --type vrouter --ip 10.0.0.5

# запустить активацию и следить за логами до финального состояния
eda-cli activation create --template <template_id> --wait

# посмотреть статус / логи отдельно
eda-cli activation status <activation_id>
eda-cli activation logs <activation_id> -f

# деактивация и повторная попытка после сбоя
eda-cli activation deactivate <activation_id> --wait
eda-cli activation retry <activation_id> --wait

# JSON-вывод для скриптов/интеграций
eda-cli --json activation list
```

Симуляция сбоя для демонстрации retry: передайте параметр
`fail_at_step` с именем одного из шагов шаблона —
`--params '{"fail_at_step": "configure_vlan"}'`.

### Автоматический retry, webhook-уведомления

```bash
# движок сам повторит workflow до 3 раз с паузой 2с между попытками,
# прежде чем окончательно пометить активацию FAILED и поднять аларм
eda-cli activation create --template <template_id> \
    --auto-retry-max 3 --auto-retry-backoff 2 \
    --params '{"fail_at_step": "configure_vlan"}'

# по завершении (ACTIVE/FAILED/DEACTIVATED) на webhook уйдёт POST с полным
# состоянием активации
eda-cli activation create --template <template_id> --webhook https://example.com/hook
```

### Пакетная активация

```bash
eda-cli activation batch --file examples/batch_activation.json
```

Каждый элемент пакета обрабатывается независимо: ошибка в одном элементе
(например, несуществующий шаблон) не отменяет остальные.

### Блокировка сетевого элемента (maintenance mode)

```bash
eda-cli ne block <ne_id>       # новые активации на этот NE встают в HELD
eda-cli ne unblock <ne_id>     # HELD-активации автоматически запускаются
```

### Алармы

```bash
eda-cli alarm list --active
eda-cli alarm clear <alarm_id>
```

Аларм поднимается автоматически, когда активация окончательно проваливается
(после исчерпания всех auto-retry попыток).

## API (кратко)

| Метод  | Путь                                     | Назначение                          |
|--------|-------------------------------------------|--------------------------------------|
| GET    | `/health`, `/version`, `/metrics`         | состояние элемента, Prometheus-метрики |
| POST   | `/templates`                              | создать шаблон активации             |
| GET    | `/templates`, `/templates/{id}`           | список / просмотр шаблонов           |
| DELETE | `/templates/{id}`                         | удалить шаблон                       |
| POST   | `/network-elements`                       | зарегистрировать управляемый NE      |
| GET    | `/network-elements`, `/network-elements/{id}` | список / просмотр NE             |
| DELETE | `/network-elements/{id}`                  | удалить NE                           |
| POST   | `/network-elements/{id}/block`            | перевести NE в maintenance mode      |
| POST   | `/network-elements/{id}/unblock`          | снять блокировку, возобновить HELD   |
| POST   | `/activations`                            | запустить активацию сервиса          |
| POST   | `/activations/batch`                      | пакетная активация                   |
| GET    | `/activations`, `/activations/{id}`       | список / просмотр активаций          |
| GET    | `/activations/{id}/status`                | текущее состояние                    |
| GET    | `/activations/{id}/logs`                  | лог выполнения шагов                 |
| POST   | `/activations/{id}/deactivate`            | деактивировать (teardown)            |
| POST   | `/activations/{id}/retry`                 | повторить после FAILED               |
| DELETE | `/activations/{id}`                       | удалить запись активации             |
| GET    | `/alarms`                                 | список алармов (`?active=true`)      |
| POST   | `/alarms/{id}/clear`                      | снять аларм                          |

Полная спецификация — в `/docs` (Swagger UI) запущенного сервера.

### Аутентификация

По умолчанию API не требует аутентификации (удобно для локальной разработки).
Чтобы включить простую AAA-проверку по общему секрету, запустите сервер с
`EDA_API_KEY=<секрет>` — тогда все запросы к `/templates`, `/network-elements`,
`/activations` и `/alarms` должны нести заголовок `X-API-Key: <секрет>`
(`/health` и `/metrics` остаются открытыми для liveness-проверок и
Prometheus). CLI подхватывает ключ через `--api-key`/`-k` или `EDA_API_KEY`.

## Параметры

Полный каталог конфигурационных параметров (переменные окружения, параметры
Heat-стека) — в машиночитаемом виде `parameters/eda_parameters.json`
(формат аналогичен отраслевому параметрическому файлу MRCF: `type`, `path`,
`group`, `mandatory`, `default`, `release` и т.д.) и в читаемом виде —
`docs/PARAMETERS.md`.

## Развёртывание на OpenStack

1. Соберите Docker-образ и опубликуйте его в реестре, доступном из OpenStack:

   ```bash
   docker build -f docker/Dockerfile -t registry.example.com/eda-vne:1.1.0 .
   docker push registry.example.com/eda-vne:1.1.0
   ```

2. Скопируйте `heat/env.yaml.sample` в `heat/env.yaml` и подставьте свои
   значения (сеть, flavor, образ ОС, keypair, ссылка на ваш образ EDA,
   опционально `eda_api_key` для включения аутентификации).

3. Разверните стек:

   ```bash
   openstack stack create -t heat/eda_vne.yaml -e heat/env.yaml eda-vne-stack
   openstack stack output show eda-vne-stack api_url
   ```

Heat-шаблон поднимает Nova-инстанс, устанавливает Docker через cloud-init и
запускает контейнер `eda-vne`, открывая порт API (по умолчанию 8080) через
security group. Подробности — в `docs/ARCHITECTURE.md`.

## Тесты

```bash
pip install -e ".[dev]"
pytest tests/ -q
```

27 тестов, покрывающих: движок активации (успех/сбой/retry/деактивация),
REST API (жизненный цикл шаблонов, NE, активаций), CLI (end-to-end через
реальный HTTP-сервер), а также второй слой возможностей — mutex по цели,
блокировку NE и возобновление HELD, auto-retry с алармами, webhook,
пакетную активацию, `/metrics`, аутентификацию по API-ключу.

## Структура проекта

```
eda/
  api/            # FastAPI-приложение, роутеры, схемы, AAA-зависимость
  cli/            # eda-cli (Click) + HTTP-клиент к API
  core/           # модели, SQLite-хранилище (+ target mutex), движок, метрики
  config.py       # настройки через переменные окружения
  server.py       # точка входа uvicorn
docker/           # Dockerfile, entrypoint, docker-compose
heat/             # Heat-шаблон и пример параметров для OpenStack
tests/            # pytest: движок, API, CLI, второй слой возможностей
examples/         # примеры JSON для шаблонов/NE/активаций/batch
docs/             # архитектурные заметки, таблица соответствий с отраслевыми EDA-платфо