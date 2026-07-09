# Архитектура EDA (Enhanced Dynamic Activation)

## Идея

Ericsson Dynamic Activation (EDA) — это платформа динамической активации
сетевых сервисов: оператор (или OSS/BSS-система) описывает сервис в виде
Service Model, а платформа прогоняет этот шаблон через набор шагов
(резервирование ресурсов, конфигурация оборудования, верификация), управляя
состоянием каждого экземпляра активации через набор специализированных
микросервисов (eric-act-*), сгруппированных в функциональные блоки: Inbound
Interfaces, OAM, Activation Core, Activation Support (+ Security &
Connectivity), Data.

Этот проект переносит ту же модель в упрощённом, полностью открытом виде —
единый Python-процесс вместо десятков Kubernetes-подов, но с теми же
поведенческими гарантиями там, где это осмысленно для демонстрационного VNE.
Ниже — прямое соответствие между тем, что реализовано здесь, и конкретными
микросервисами реального EDA (по официальному Technical Product Description,
6/221 02-CRH 109 1516).

| Функциональный блок EDA   | Микросервис Ericsson              | Что реализовано в этом проекте |
|----------------------------|------------------------------------|----------------------------------|
| Activation Core            | Activation Orchestrator Deployer   | CRUD шаблонов (`/templates`) — Service Model |
| Activation Core            | Activation Engine / Orchestrator   | `ActivationEngine` — машина состояний, выполнение шагов |
| Activation Core            | Activation Replicator              | Авто-retry с backoff (`params.auto_retry`) |
| Activation Core            | Inbound Async                      | Webhook-уведомление о финальном состоянии (`params.webhook_url`) |
| Activation Support         | Mutex Handler                      | `Store.try_acquire_target()` — сериализация по `ne_id` (или "self") |
| Activation Support         | CUDB Activation Blocker             | `POST /network-elements/{id}/block` + состояние `HELD` |
| Activation Support         | ProcLog Manager                     | `GET /activations/{id}/logs` |
| Inbound Interfaces         | Inbound Batch Handler                | `POST /activations/batch` |
| Inbound Interfaces         | REST Provisioning                    | Весь REST API |
| OAM                        | Alarm Handler                        | `Alarm`-модель, `/alarms`, авто-рейз при окончательном FAILED |
| OAM                        | PM Server (Prometheus)               | `GET /metrics` (prometheus_client) |
| Security & Connectivity    | AAA                                  | Опциональный API-ключ (`EDA_API_KEY` / `X-API-Key`) |
| Data                       | Wide Column DB / Document DB и т.д.  | SQLite (см. раздел "Данные" ниже) |

Некоторые блоки оригинала намеренно не переносились в проект (Backup and
Restore Orchestrator, License Manager, Functional Verifier, Service Locator
Registry, полноценный AAA с ролями/OAuth2) — они добавляют операционную
сложность без демонстрационной ценности для учебного/пилотного VNE.

## Компоненты

```
                    ┌────────────────────────────┐
  eda-cli  ───HTTP──▶│   FastAPI northbound API   │
  (Click)            │   /templates /activations  │
                      │   /network-elements /alarms │
                      │   /health /metrics          │
                      └──────────────┬─────────────┘
                                     │
                          ┌──────────▼───────────┐
                          │  ActivationEngine     │
                          │  (state machine,      │
                          │   auto-retry, webhook, │
                          │   alarms, metrics)     │
                          └──────────┬───────────┘
                                     │
                          ┌──────────▼───────────┐
                          │  SQLite Store          │
                          │  + in-memory target    │
                          │    mutex (Mutex Handler)│
                          │  templates/activations  │
                          │  network_elements/alarms│
                          └────────────────────────┘
```

- `eda/core/models.py` — доменные сущности: `ServiceTemplate`, `Activation`,
  `NetworkElement`, `Alarm`, состояния (`ActivationState`, `AlarmSeverity`).
- `eda/core/store.py` — персистентность на SQLite (переживает рестарт
  контейнера/VM без внешней БД) плюс in-memory target-mutex (Mutex Handler
  equivalent — не персистится намеренно, процесс-рестарт естественным
  образом снимает все локи).
- `eda/core/engine.py` — движок динамической активации: проводит
  `Activation` через состояния, авто-retry, шлёт webhook, поднимает алармы,
  пишет Prometheus-метрики.
- `eda/core/metrics.py` — Prometheus-коллекторы (PM Server equivalent).
- `eda/api/*` — REST API, роутеры по функциональным блокам, `security.py` —
  AAA-зависимость.
- `eda/cli/*` — CLI, реализован как HTTP-клиент к тому же API (никакого
  прямого доступа к хранилищу/движку в обход API — это соответствует модели
  "CLI и API равноправны").

## Машина состояний активации

```
                     ┌────────────────────────────────────┐
                     │ (NE заблокирован в момент создания) │
                     ▼                                      │
                   HELD ───(NE разблокирован)───────────────┘
                     │
                     ▼
CREATED → VALIDATING → ACTIVATING → ACTIVE
                             │
                             ▼
                           FAILED ──(auto retry, пока attempts < max)──▶ VALIDATING
                             │
                             └──(ручной retry через API/CLI)───────────▶ VALIDATING

ACTIVE  ──▶ DEACTIVATING ──▶ DEACTIVATED
FAILED  ──▶ DEACTIVATING ──▶ DEACTIVATED
```

Каждый шаг шаблона (`steps: [...]`) выполняется последовательно; для
демонстрации сбоев можно передать параметр активации `fail_at_step` — движок
искусственно завершится с ошибкой на этом шаге (аналог сбоя конфигурации на
реальном оборудовании). Комбинация с `auto_retry` показывает исчерпание
попыток и итоговый аларм.

## Mutex по целевому элементу (Mutex Handler)

Перед тем как запланировать выполнение (`create`, `deactivate`, `retry`),
API-слой синхронно резервирует цель через `Store.try_acquire_target(ne_id
or "self")`. Если цель уже занята другой активацией — запрос немедленно
получает `409`, без постановки в очередь (именно так ведёт себя реальный
Mutex Handler: "первый запрос берёт лок, остальные отклоняются с кодом
ошибки"). Лок снимается движком ровно один раз, в `finally`-блоке, когда
воркфлоу достигает терминального состояния — включая случай, когда все
auto-retry попытки исчерпаны.

Активации без явного `ne_id` разделяют один и тот же ключ `"self"` — то есть
не более одной "нецелевой" активации может выполняться одновременно, что
соответствует модели "эксклюзивность на уровне subscriber/target" в
оригинале.

## Блокировка сетевого элемента (CUDB Activation Blocker)

`POST /network-elements/{id}/block` переводит NE в режим обслуживания:
новые активации, нацеленные на этот NE, создаются сразу в состоянии `HELD`
(движок для них не запускается). `POST /network-elements/{id}/unblock`
снимает флаг и планирует возобновление (`engine.resume_held_activation`)
для каждой `HELD`-активации этого NE — то есть очередь "прожимается"
автоматически, как и в оригинале ("удерживаемые запросы возобновляются по
снятии блокировки").

## Точка расширения: реальные драйверы вместо симуляции

Вся "физика" активации инкапсулирована в
`ActivationEngine._step_with_failure_check()`. Чтобы подключить реальное
управление оборудованием, эту функцию нужно заменить/расширить вызовом
конкретного драйвера по типу шага, например:

- NETCONF/YANG (через `ncclient`) — для конфигурации маршрутизаторов;
- SSH/Ansible playbook — для legacy CLI-оборудования;
- vendor SDK / REST — для облачных сетевых функций.

Шаблон (`ServiceTemplate.steps`) при этом не меняется — меняется только
реализация обработчика шага, что сохраняет northbound API и CLI стабильными.

## Данные

Сейчас всё состояние (шаблоны, активации, NE, алармы) живёт в одном файле
SQLite — этого достаточно для одного процесса/VM. В реальном EDA этот блок
покрывают несколько специализированных хранилищ (Cassandra-подобная Wide
Column DB для подписочных данных, ZooKeeper-подобный координатор, Postgres
для документов, Kafka для журналов, Elasticsearch-подобный поисковый
движок). Если потребуется горизонтальное масштабирование — первый шаг
такой же, как в оригинале: вынести стор за интерфейс (`eda/core/store.py`
уже изолирует весь SQL) и подставить Postgres/др. вместо SQLite, не трогая
движок и API.

## Развёртывание на OpenStack

`heat/eda_vne.yaml` — HOT-шаблон (Heat Orchestration Template), который:

1. создаёт security group с портами API (по умолчанию 8080) и SSH (22);
2. создаёт Neutron-порт и (опционально) floating IP;
3. поднимает Nova-инстанс на базовом образе (например, Ubuntu 22.04);
4. через `user_data` (cloud-init) устанавливает Docker и запускает контейнер
   `eda-vne` с нужными переменными окружения, включая опциональный
   `EDA_API_KEY`.

Персистентное состояние (`/var/lib/eda/eda.db`) монтируется как volume —
при желании можно вынести его на Cinder-том, чтобы конфигурация сервисов
переживала пересоздание инстанса.

Для реального прод-окружения дополнительно рекомендуется:

- заменить `management_cidr: 0.0.0.0/0` на конкретную сеть управления;
- обязательно задать `eda_api_key` (или полноценный OAuth2/OIDC вместо
  текущего shared-secret) перед выходом за пределы доверенной сети;
- вынести SQLite на внешнюю БД (Postgres) при масштабировании горизонтально;
- поставить перед API TLS-terminating reverse proxy (сейчас трафик внутри
  security group идёт открытым HTTP).
