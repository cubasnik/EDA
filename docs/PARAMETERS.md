# Параметры EDA (Enhanced Dynamic Activation)

Машиночитаемый каталог параметров — `parameters/eda_parameters.json`, в
формате, аналогичном отраслевому параметрическому файлу MRCF (`type`,
`name`, `path`, `group`, `format`, `mandatory`, `default`,
`recommended_value`, `category`, `comments`, `release`, `functionality`).
Ниже — читаемая версия того же каталога.

Все параметры, кроме двух в конце (`day-1`, применяются per-request через
`params` при создании активации), относятся к типу `day-0` — задаются один
раз при развёртывании (переменные окружения контейнера / параметры
Heat-стека) и не меняются в процессе работы элемента.

## General

| Параметр | По умолчанию | Обязателен | Описание |
|---|---|---|---|
| `eda.ne.name` (`EDA_NE_NAME`) | `eda-vne-01` | нет | Имя элемента в `GET /health` и имя Nova-сервера |
| `eda.ne.type` (`EDA_NE_TYPE`) | `virtual-network-element` | нет | Тип элемента в `GET /health` |
| `eda.vendor.name` | `EricssonSoft` | нет | Бренд, отображаемый в `GET /version` и документации |
| `eda.registry.url` | `registry.ericsonsoftware.ru` | нет | Реестр контейнеров для образа `eda-vne` |
| `eda.docker.image` (Heat `eda_docker_image`) | `registry.ericsonsoftware.ru/eda-vne:1.1.0` | да | Образ, который разворачивает Heat-шаблон |

## Network Connectivity

| Параметр | По умолчанию | Обязателен | Описание |
|---|---|---|---|
| `eda.api.host` (`EDA_API_HOST`) | `0.0.0.0` | нет | Адрес, на котором слушает REST API |
| `eda.api.port` (`EDA_API_PORT`, Heat `api_port`) | `8080` | нет | Порт REST API (1–65535) |
| `eda.api.url` (`EDA_API_URL`) | `http://localhost:8080` | нет | Базовый URL для `eda-cli` |
| `eda.network.id` (Heat `network_id`) | — | да | Neutron-сеть для порта VNE |
| `eda.network.externalId` (Heat `external_network_id`) | пусто | при floating IP | Внешняя сеть для floating IP |
| `eda.network.assignFloatingIp` (Heat `assign_floating_ip`) | `true` | нет | Выделять ли floating IP |
| `eda.network.managementCidr` (Heat `management_cidr`) | `0.0.0.0/0` | нет | CIDR, которому разрешён доступ к API/SSH — сузьте перед прод-использованием |

## OpenStack Deployment

| Параметр | По умолчанию | Обязателен | Описание |
|---|---|---|---|
| `eda.openstack.image` (Heat `image`) | `ubuntu-22.04` | нет | Glance-образ для инстанса |
| `eda.openstack.flavor` (Heat `flavor`) | `m1.small` | нет | Флейвор Nova |
| `eda.openstack.keyName` (Heat `key_name`) | — | да | Существующий keypair для SSH |

## Storage

| Параметр | По умолчанию | Обязателен | Описание |
|---|---|---|---|
| `eda.storage.dbPath` (`EDA_DB_PATH`) | `/var/lib/eda/eda.db` | нет | Путь к SQLite-файлу состояния |
| `eda.storage.backend` | `sqlite` | нет | Бэкенд хранения (справочно; см. `docs/ARCHITECTURE.md` про переход на Postgres) |

## Activation Engine

| Параметр | По умолчанию | Обязателен | Описание |
|---|---|---|---|
| `eda.engine.stepMinDelaySeconds` (`EDA_STEP_MIN_DELAY`) | `0.4` | нет | Нижняя граница случайной задержки шага |
| `eda.engine.stepMaxDelaySeconds` (`EDA_STEP_MAX_DELAY`) | `1.2` | нет | Верхняя граница случайной задержки шага |
| `eda.activation.autoRetry.maxAttempts` *(day-1, per-request)* | `1` | нет | Число попыток workflow перед FAILED + аларм (`params.auto_retry.max_attempts`) |
| `eda.activation.autoRetry.backoffSeconds` *(day-1, per-request)* | `1.0` | нет | Пауза между авто-попытками (`params.auto_retry.backoff_seconds`) |

## Container Security

| Параметр | По умолчанию | Обязателен | Описание |
|---|---|---|---|
| `eda.security.apiKey` (`EDA_API_KEY`, Heat `eda_api_key`) | пусто | нет | Общий секрет для AAA; пусто = аутентификация выключена. Клиенты передают его в заголовке `X-API-Key`; `/health` и `/metrics` остаются открытыми всегда |

## Как редактировать

`parameters/eda_parameters.json` — источник истины; эта страница — просто
его читаемое отражение. При добавлении нового параметра обновляйте оба
файла и указывайте `release`, с которого он появился, как это сделано для
`eda.security.apiKey` 