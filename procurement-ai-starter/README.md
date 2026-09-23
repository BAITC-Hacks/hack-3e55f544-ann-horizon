# Procurement AI Demo

Локальная платформа для закупочных планов B2B/B2C и подбора event-подрядчиков. Она поддерживает поиск и сопоставление, запасы и прогноз, риск/compliance-проверки, согласования, локальные черновики заказов, ручной учёт поставок/приёмки, сверку счетов и закупочную аналитику. Внешние заказы, платежи и сообщения поставщикам не отправляются.

## Что работает

- B2B workflow для запроса на закупку с количеством, характеристиками, бюджетом и сроком доставки.
- Локальный русский/английский parser работает без API-ключа. Опционально можно включить OpenAI Agents SDK для структурированного извлечения требований; арифметика и валидация при этом остаются в Python.
- Поиск выполняется по replaceable catalog adapter и локальным JSON sample-данным.
- Product Matching проверяет минимальные RAM/SSD/capacity и интерфейс. Неподходящие варианты не попадают в план.
- Supplier Agent показывает доступные demo-рейтинг/reliability и честно помечает отсутствие истории поставок.
- Pricing использует `Decimal`; weighted optimizer соблюдает жёсткие ограничения по валюте, цене, сроку, количеству и наличию.
- Validator повторно проверяет IDs, количество, цену, сумму строк, бюджет, остаток, срок и характеристики.
- Все планы требуют ручной проверки. `READY_FOR_REVIEW` означает только проверенный проект рекомендации, не заказ.
- FastAPI сохраняет каждый план в SQLite; исходный текст запроса не сохраняется. Сохранённые планы и события видны через API.
- Forecast использует скользящее среднее четырёх месячных периодов. Reorder рассчитывает порог и спрос на время доставки; недостающая история явно помечается.
- Риск-оценка отделяет отсутствующие данные от подтверждённого риска. Исторический ценовой риск помечается как неизвестный, пока нет истории цен.
- Compliance настраивается через `data/procurement_policy.json`: минимум коммерческих предложений, allowlist поставщиков, запрещённые категории, лимит и роли согласующих по сумме.
- Крупные B2B планы создают `PENDING` approval. Согласование или отклонение записывается в SQLite и audit log; план остаётся черновиком и заказ не создаёт.
- Smart Contractor Matching по городу, дате, формату, категории, бюджету, длительности и языку возвращает до 3 детерминированно ранжированных карточек с конкретными причинами подбора. Занятые даты исключаются; сервис показывает, если категория отсутствует или подходящих профилей меньше трёх.
- Каталог подрядчиков загружается из `data/hackathon-dataset-anonymized.csv`: 66 анонимизированных профилей, включая 13 явно помеченных синтетических и сохранённые флаги импутации. Ответы отмечают источник/синтетические профили. Подбор не бронирует подрядчиков и не отправляет запросы.
- Локальный order draft можно создать из готового плана. После согласования API принимает введённые вручную статусы поставки, ETA и трек-номер; задержка позволяет перепланировать количество, закреплённое за поставщиком, исключив его из подбора.
- Приёмка сохраняет полученное и повреждённое количество. Только принятые единицы увеличивают локальный складской остаток; события и действия пишутся в audit log.
- История цены содержит 84 явно синтетических наблюдения; анализ сравнивает предложение с медианой за 90 дней, требует минимум три даты и сообщает об аномалии от 20%.
- Seed-каталог содержит 10 товаров, 5 поставщиков и 21 связанных предложений; данные помечены `DEMO DATA`.
- B2C включает предпочтения, записанную историю покупок, повторные рекомендации, проверку совместимости, подбор комплектов и локальные черновики возврата.
- B2B UI включает каталог, склад/прогноз/пополнение, планы и согласования, заказы/доставку/приёмку/счета, журнал и аналитику.
- `GET /api/procurement/analytics/overview` отдаёт числовые показатели по всей локальной базе. Экономия, фактические сроки поставки и надёжность без подтверждённых данных обозначаются как неизвестные.

## Архитектура

`FastAPI → Manager Agent / Contractor Matching Agent → typed tools → services → repositories → SQLite / file catalog`. Исходные закупочные sample-данные для первого seed берутся из JSON; каталог подрядчиков читается из CSV. Опциональные LLM агенты создаются программно из Python через OpenAI Agents SDK; отдельные агенты в OpenAI Platform не настраиваются.

Менеджер обращается к хранилищу только через tools/services/repository. Core использует FastAPI, Pydantic и SQLite; денежные вычисления и подбор подрядчиков детерминированы. `SampleCatalogAdapter` и `SQLiteCatalogAdapter` реализуют общий интерфейс закупочного каталога. Database файл по умолчанию — `data/procurement.db` (игнорируется Git). Черновики заказов остаются локальными: `external_order_created=false`.

## Установка и запуск на Windows

Требуется Python 3.13+.

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup.ps1
```

`setup.ps1` создаёт `.venv`, устанавливает `requirements.txt` и копирует `.env.example` в `.env`. API key не нужен для локального demo.

Запустить B2B пример:

```powershell
.\run.ps1
```

Своя заявка:

```powershell
.\.venv\Scripts\python.exe -m backend.run_agent "Нужно купить 100 ноутбуков, бюджет 50 000 000 ₸, RAM минимум 32 GB, SSD минимум 1 TB, срок максимум 10 дней"
```

Запустить API:

```powershell
.\api.ps1
```

После запуска веб-интерфейс доступен на `http://127.0.0.1:8000`, документация API — на `http://127.0.0.1:8000/docs`.

## API

- `GET /health`
- `GET /api/products` и `GET /api/products/{id}`
- `GET /api/offers` (можно добавить `?product_id=4`)
- `GET /api/suppliers`
- `GET /api/inventory`
- `GET /api/forecast/{product_id}`
- `POST /api/reorders` — расчёт рекомендаций пополнения и запись audit event
- `GET /api/procurement/plans`
- `GET /api/procurement/approvals?status=PENDING`
- `POST /api/procurement/approvals/{approval_id}/decision`
- `GET /api/audit-log`
- `POST /api/chat` — естественно-языковой запрос
- `POST /api/procurement/requests` — структурированный `PurchaseRequest`
- `POST /api/contractors/search` — подобрать до трёх event-подрядчиков
- `GET /api/contractors/demo-scenarios` — четыре демонстрационных сценария подбора
- `POST /api/procurement/plans/{plan_id}/order` — создать локальный черновик заказа
- `GET /api/procurement/orders` и `GET /api/procurement/orders/{order_id}`
- `POST /api/procurement/orders/{order_id}/delivery-events` и `GET .../delivery-events`
- `POST /api/procurement/orders/{order_id}/receipts` и `GET .../receipts`
- `POST /api/procurement/orders/{order_id}/invoices` и `GET .../invoices`
- `POST /api/procurement/invoices/{invoice_id}/review` — повторная сверка после приёмки
- `GET /api/procurement/invoices/{invoice_id}`
- `GET /api/procurement/analytics/finance` — суммы по валютам/поставщикам, статусы счетов и итоги приёмки
- `/api/personal/wishlist` — добавить, показать и удалить позиции списка желаний
- `/api/personal/price-watches` — создать/показать наблюдения за ценой; `POST .../evaluate` выполняет ручную проверку каталога, `GET .../{watch_id}/events` показывает сохранённые события
- `/api/personal/reminders` — создать и показать напоминания; `?due_only=true` фильтрует наступившие
- `POST /api/procurement/orders/{order_id}/replan` — заменить количество задержанного/отменённого поставщика

Пример для PowerShell:

```powershell
$body = @{
  message = "Нужно закупить 300 SSD минимум 1 TB по цене до 25 000 ₸ за штуку, доставка максимум 7 дней."
  user_context = @{ user_type = "business"; organization_id = "demo-org"; currency = "KZT" }
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Uri http://127.0.0.1:8000/api/chat -Method Post -ContentType "application/json" -Body $body
```

На seed data запрос планирует 300 SSD, распределяет их между тремя предложениями и считает 7 340 000 ₸ стоимости товара. Статус — `READY_FOR_REVIEW`; доставка и налоги неизвестны и исключены из суммы. Каталог и предложения помечены `DEMO DATA`. Ответ содержит `plan_id`, запись доступна в `GET /api/procurement/plans`, а действие отражено в `GET /api/audit-log`.

`POST /api/reorders` выявляет demo-SSD с 32 доступными единицами при пороге 50, берёт средний спрос 34 единицы в месяц и 3 дня доставки и рекомендует 22 единицы. Endpoint также собирает и сохраняет план закупки `READY_FOR_REVIEW`; складской остаток не меняется.

Для B2B запроса на 300 SSD seed policy создаёт approval на роль `finance`. Получить ожидающие согласования можно через `GET /api/procurement/approvals?status=PENDING`. Решение отправляется JSON-ом вида `{"decision":"approved","reviewer_id":"demo-finance","reviewer_role":"finance","comment":"Проверено"}` на `POST /api/procurement/approvals/{approval_id}/decision`. Demo reviewer IDs из policy не являются аутентифицированными аккаунтами; production deployment должен подключить проверку личности и ролей.

### Smart Contractor Matching

Пример запроса:

```powershell
$body = @{
  city = "Алматы"
  event_date = "2026-10-17"
  event_type = "корпоратив"
  category = "Ведущий"
  budget_kzt = 1200000
  duration_hours = 4
  language = "русский"
} | ConvertTo-Json

Invoke-RestMethod -Uri http://127.0.0.1:8000/api/contractors/search -Method Post -ContentType "application/json" -Body $body
```

Каждая карточка содержит цену «от», конкретные совпадения по формату/языку/длительности и фрагмент описания профиля. Возможные итоги: `MATCHES`, `CATEGORY_NOT_FOUND` (категория не найдена в городе) и `NO_MATCHES` (кандидаты есть, но не проходят бюджет, формат, занятость или ограничения запроса). Каталог содержит календарные данные на 2026-09-23—2026-12-31; API не экстраполирует доступность за этот срок.

### Local orders, delivery and receiving

После согласования можно сохранить local draft через `POST /api/procurement/plans/{plan_id}/order` с телом `{"buyer_note":"Проверить условия поставки"}`. Для ручного статуса поставки передайте `supplier_id`, `status` (`ORDERED`, `SHIPPED`, `DELAYED`, `DELIVERED` или `CANCELLED`), а при задержке/отмене добавьте `note`. Все статусы, ETA и трек-номера — введённые оператором сведения, не интеграция с перевозчиком.

При задержке вызов `POST /api/procurement/orders/{order_id}/replan` автоматически исключит этого поставщика и сформирует план только на количество из его строк заказа. Статус нового плана покажет, достаточно ли доступных предложений. Приёмка принимает `items` с `order_item_id`, `quantity_received` и `damaged_quantity`. При задержке заказа можно принять строки уже доставленных поставщиков; поставщик каждой строки должен иметь ручной статус `DELIVERED`. Склад увеличивается только на принятое количество.

### Счета и закупочная аналитика

После ручной отметки заказа как `ORDERED` можно сохранить счёт на `POST /api/procurement/orders/{order_id}/invoices`. Передайте supplier, номер/дату и строки с `order_item_id`, количеством и ценой; `subtotal`, налог, доставку и итоговую сумму система проверит детерминированно. Сверка сравнивает поставщика, цену и количество со строками локального заказа и записями приёмки.

Счёт получает `PENDING_RECEIVING`, если указанное количество ещё не принято. После записи приёмки вызовите `POST /api/procurement/invoices/{invoice_id}/review`; система повторит сверку. Несовпадения показываются в `findings` со статусом `VARIANCE`. Счёт `MATCHED` означает, что данные заказа, принятого количества и арифметики совпали; платёж не выполняется, а `payment_status` остаётся `NOT_PAID`.

`GET /api/procurement/analytics/finance` суммирует суммы заказов и счетов отдельно по валютам и поставщикам, статусы сверки, принятое и повреждённое количество. Конвертации валют, OCR, бухгалтерская проводка и проведение платежей не включены.

### B2C: wishlist, ручной мониторинг цены и напоминания

Список желаний привязан к `user_id` и локальному товару. Если `offer_id` не задан, текущая цена берётся из самой дешёвой доступной demo-цены в выбранной валюте; при заданном offer отображается конкретное предложение.

```powershell
$body = @{ user_id = "demo-user"; product_id = 4; target_price = 20000; currency = "KZT"; note = "Проверить перед покупкой" } | ConvertTo-Json
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/personal/wishlist -Method Post -ContentType "application/json" -Body $body
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/personal/wishlist?user_id=demo-user"
```

Наблюдение фиксирует стартовую цену локального предложения и целевую цену. Проверка выполняется вручную через `POST /api/personal/price-watches/evaluate?user_id=demo-user`; снижение цены и достижение цели записываются в историю событий.

```powershell
$watch = @{ user_id = "demo-user"; product_id = 4; target_price = 18000; currency = "KZT" } | ConvertTo-Json
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/personal/price-watches -Method Post -ContentType "application/json" -Body $watch
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/personal/price-watches/evaluate?user_id=demo-user" -Method Post
```

Напоминание принимает товар из каталога либо текстовый запрос, количество и `remind_at` с часовым поясом, например `2026-12-01T09:00:00+05:00`. Статус `DUE` вычисляется при чтении; активного планировщика и каналов уведомлений нет. Все цены являются локальными demo-данными, а `user_id` пока не подтверждается аутентификацией и не обеспечивает tenant isolation.

## Опциональные агенты OpenAI Agents SDK

Offline режим не обращается к модели и работает без Agents SDK и API key. SDK агенты — Intake, Procurement Manager и профильные Search, Matching, Supplier, Pricing, Delivery, Inventory, Forecast, Optimization, Risk, Compliance, Validator и Approval reviewers — конструируются в коде `backend/integrations/agents_sdk.py`. Их не нужно создавать вручную в OpenAI Platform. Установите необязательную зависимость:

```powershell
python -m pip --python .\.venv\Scripts\python.exe install -r requirements-ai.txt
```

После ротации ключа выполните `.\enable-ai.ps1` в локальном PowerShell. Скрипт скрыто запросит новый ключ, установит SDK и сохранит ключ только в игнорируемый Git файл `.env`; затем перезапустите сервер командой `.\api.ps1`. Для API включатся `PROCUREMENT_LLM_INTAKE=1` и `PROCUREMENT_AGENT_REVIEW=1`; для CLI доступны `--llm-intake` и `--agent-review`. Эти агенты используются на текстовом маршруте `POST /api/chat`. Сводка SDK хранится отдельно в `ai_summary`: агентам нельзя менять суммы, количества, policy/approval-статусы или создавать действия. Расчёты и проверки остаются детерминированными. См. [официальный OpenAI Docs quickstart для Agents SDK](https://developers.openai.com/api/docs/guides/agents/quickstart).

## Тесты

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Проверено в финальном прогоне: 65 тестов, все прошли.

Тесты покрывают intake и точные товарные совпадения, спецификации, арифметику, оптимизацию, ценовую историю, миграции SQLite, approval, подбор подрядчиков, частичную доставку, финансы, аналитический обзор, B2C API, возвраты и комплекты. SDK bundle проверяется без вызова модели.

## Веб-интерфейс

Главная страница на `http://127.0.0.1:8000` работает без отдельной сборки frontend и использует API того же FastAPI процесса. B2C экраны покрывают wishlist, цену, напоминания, историю и повторные покупки, комплекты, совместимость и возвраты; B2B экраны — каталог, склад, согласования, заказы, приёмку, счета и аналитику. UI использует локальные demo-reviewer IDs и фиксированный `demo-user`; входа и разграничения между арендаторами нет.

## Ограничения и demo режим

- Все текущие товары, цены, остатки, рейтинги и reliability являются синтетическими `DEMO DATA`; это не текущие рыночные предложения.
- У поставщиков отсутствует история успешных/задержанных поставок, дефектов и возвратов. Поля истории остаются `null`/`insufficient_data`.
- В seed data нет стоимости доставки и налогов. `total_cost` равен стоимости товара и не является landed cost.
- Внешняя валюта без отдельного предложения не пересчитывается.
- Черновики заказов и статусы закупки локальные; приложение не отправляет заказы, платежи, письма, запросы подрядчикам и уведомления.
- Подрядчики — анонимизированные записи исходного CSV плюс 13 синтетических профилей; поля `synthetic`, `city_imputed` и `price_imputed` сохраняются и показываются.
- Forecast и reorder работают на demo history. Stock не резервируется и не уменьшается после рекомендации.
- Reviewer role проверяется по локальной demo-конфигурации, но API пока не аутентифицирует reviewer identity и не обеспечивает tenant isolation.
- Реальный вызов модели не проверен: ключи были отправлены в чат, поэтому проект их не сохранял и не использовал. После ротации запускайте локальный `.\enable-ai.ps1`.
- Повторные покупки, история, совместимость, комплект и возврат оперируют ручными записями; real order execution, автоматический delivery tracking, OCR счетов и проведение платежей не подключены.
- Нет live price feed и планировщика уведомлений. Анализ цены использует лишь явно помеченную синтетическую историю.
- Локальный demo не включает вход и tenant isolation; не публикуйте его как многопользовательскую production-службу.

## Docker

Пробный запуск: `docker compose up --build`. Контейнер запускается непривилегированным пользователем, порт привязан к `127.0.0.1`, SQLite сохраняется в named volume. По умолчанию модельные агенты выключены; `INSTALL_AI=1` добавляет Agents SDK в образ. Docker-команды в этой среде не запускались.
