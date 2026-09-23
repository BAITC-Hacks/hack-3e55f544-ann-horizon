from __future__ import annotations

import base64
import json
import os
import re
import threading
import time
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
PAGE_CACHE_SECONDS = 600
DETAIL_CACHE_SECONDS = 25
MAX_BODY_BYTES = 64 * 1024
MAX_QUANTITY = 100_000


def load_local_env() -> None:
    """Load private local settings without requiring a third-party dotenv package."""
    path = ROOT / ".env.local"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


load_local_env()


class CatalogError(Exception):
    pass


def as_int(value: object, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default


def plain(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return " ".join(plain(item) for item in value)
    return str(value)


def normalize(value: object) -> str:
    text = unicodedata.normalize("NFKC", plain(value)).casefold()
    return " ".join(re.findall(r"[0-9a-zа-яәғқңөұүһі]+", text, flags=re.IGNORECASE))


STOP_WORDS = {
    "есть", "нужен", "нужна", "нужно", "нужны", "хочу", "найди", "найти",
    "покажи", "пожалуйста", "какой", "какая", "какие", "подбери", "подобрать",
    "товар", "товара", "товаре", "продукт", "продукта", "для", "про", "у",
    "вас", "на", "и", "или", "с", "по", "в", "из", "есть", "дайте",
    "проверь", "проверить", "наличие", "наличия", "аналог", "аналоги", "замена",
}


class EktCatalog:
    def __init__(self) -> None:
        self.base_url = os.environ.get("EKT_API_BASE_URL", "https://ekt.kz/api").rstrip("/")
        self.username = os.environ.get("EKT_API_USER", "")
        self.password = os.environ.get("EKT_API_PASSWORD", "")
        self.max_pages = max(1, min(as_int(os.environ.get("EKT_SEARCH_PAGES", "8"), 8), 100))
        self._page_cache: dict[int, tuple[float, list[dict]]] = {}
        self._detail_cache: dict[int, tuple[float, dict]] = {}
        self._lock = threading.RLock()

    def _get_json(self, path: str) -> object:
        if not self.username or not self.password:
            raise CatalogError("Для подключения каталога заполните EKT_API_USER и EKT_API_PASSWORD в .env.local.")
        token = base64.b64encode(f"{self.username}:{self.password}".encode("utf-8")).decode("ascii")
        request = Request(
            f"{self.base_url}{path}",
            headers={"Authorization": f"Basic {token}", "Accept": "application/json"},
        )
        try:
            with urlopen(request, timeout=5) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code in (401, 403):
                raise CatalogError("Каталог отклонил доступ. Проверьте учётные данные API.") from None
            raise CatalogError(f"Каталог временно недоступен (HTTP {exc.code}).") from None
        except (URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
            raise CatalogError("Не удалось получить свежие данные каталога. Попробуйте ещё раз.") from None

    def page(self, number: int) -> list[dict]:
        now = time.time()
        with self._lock:
            cached = self._page_cache.get(number)
            if cached and cached[0] > now:
                return cached[1]
        data = self._get_json(f"/products?page={number}")
        items = data.get("items", []) if isinstance(data, dict) else []
        if not isinstance(items, list):
            items = []
        with self._lock:
            self._page_cache[number] = (now + PAGE_CACHE_SECONDS, items)
        return items

    def detail(self, product_id: int, refresh: bool = False) -> dict:
        now = time.time()
        with self._lock:
            cached = self._detail_cache.get(product_id)
            if not refresh and cached and cached[0] > now:
                return cached[1]
        data = self._get_json(f"/products/detail?id={product_id}")
        if not isinstance(data, dict) or not data.get("id"):
            raise CatalogError("Карточка товара не найдена в каталоге.")
        with self._lock:
            self._detail_cache[product_id] = (now + DETAIL_CACHE_SECONDS, data)
        return data

    def search(self, query: str) -> list[dict]:
        terms = [term for term in normalize(query).split() if term not in STOP_WORDS and len(term) > 1]
        compact_query = "".join(terms)
        if not terms:
            return []

        with ThreadPoolExecutor(max_workers=min(6, self.max_pages)) as pool:
            page_lists = list(pool.map(self.page, range(1, self.max_pages + 1)))

        results: list[tuple[int, dict]] = []
        seen: set[int] = set()
        for items in page_lists:
            for item in items:
                if not isinstance(item, dict):
                    continue
                product_id = as_int(item.get("id"))
                if not product_id or product_id in seen:
                    continue
                seen.add(product_id)
                article = normalize(item.get("article"))
                name = normalize(item.get("name"))
                combined = f"{article} {name} {product_id}"
                compact_article = "".join(article.split())
                compact_name = "".join(name.split())
                if compact_query and (compact_query == compact_article or compact_query == compact_name):
                    score = 1000
                elif compact_query and (compact_query in compact_article or compact_query in compact_name):
                    score = 60
                else:
                    matches = sum(1 for term in terms if term in combined)
                    if not matches:
                        continue
                    score = matches * 10
                    if all(term in combined for term in terms):
                        score += 30
                    if terms[0] in article:
                        score += 12
                results.append((score, item))

        results.sort(key=lambda pair: (pair[0], as_int(pair[1].get("id"))), reverse=True)
        return [item for _, item in results[:5]]


catalog = EktCatalog()
session_lock = threading.RLock()
sessions: dict[str, dict] = {}


PROPERTY_LABELS = {
    "TORGOVAYA_MARKA": "Бренд",
    "NOMINALNYY_TOK": "Номинальный ток",
    "NOMINALNOE_NAPRYAZHENIE": "Номинальное напряжение",
    "NOMINALNAYA_OTKLYUCHAYUSHCHAYA_SPOSOBNOST": "Отключающая способность",
    "KOLICHESTVO_POLYUSOV": "Количество полюсов",
    "TIP_USTANOVKI": "Тип установки",
    "KRATNOST_MIN": "Минимальная кратность",
    "ARTIKULPOSTAVSHCHIKA": "Артикул поставщика",
    "CML2_BAR_CODE": "Штрихкод",
    "SERIYA": "Серия",
}
HIDDEN_PROPERTY_KEYS = {
    "BRAND_PRIORITY", "CML2_ARTICLE", "CML2_TRAITS", "CML2_TAXES", "IMYAKARTINKI",
    "RECOMMEND", "NOVINKA", "SPETSPREDLOZHENIE", "OBYEM",
}


def certificates_for(product: dict) -> list[dict]:
    found: list[dict] = []
    seen: set[str] = set()
    candidates = []
    for key in ("certificates", "certificate", "documents", "files"):
        if product.get(key):
            candidates.append((key, product[key]))
    properties = product.get("properties", {})
    if isinstance(properties, dict):
        candidates.extend((key, value) for key, value in properties.items()
                          if any(token in key.casefold() for token in ("certif", "sertif", "certificate", "сертифик")))
    for key, value in candidates:
        for candidate in re.findall(r"https?://[^\s\]}'\"]+", plain(value)):
            if candidate.startswith("https://") and candidate not in seen:
                seen.add(candidate)
                found.append({"label": PROPERTY_LABELS.get(key, "Сертификат"), "url": candidate})
    return found[:5]


def public_product(product: dict, role: str = "product") -> dict:
    properties = product.get("properties", {})
    specifications = []
    if isinstance(properties, dict):
        for key, value in properties.items():
            if key in HIDDEN_PROPERTY_KEYS or value in (None, "", [], {}):
                continue
            if not any(key.startswith(prefix) for prefix in (
                "NOMINAL", "KOLICHESTVO", "TIP_", "TORGOVAYA", "KRATNOST", "ARTIKULPOSTAVSHCHIKA", "SERIYA",
            )):
                continue
            display = PROPERTY_LABELS.get(key, key.replace("_", " ").capitalize())
            text = plain(value).strip()
            if text and len(text) <= 160:
                specifications.append({"name": display, "value": text})
            if len(specifications) >= 8:
                break

    stores = product.get("stores", [])
    stock_by_store = []
    if isinstance(stores, list):
        stock_by_store = [
            {"name": plain(store.get("name", "Склад")), "quantity": as_int(store.get("quantity"))}
            for store in stores if isinstance(store, dict) and as_int(store.get("quantity")) > 0
        ]
        stock_by_store.sort(key=lambda item: item["quantity"], reverse=True)

    raw_quantity = product.get("quantity")
    quantity = as_int(raw_quantity) if raw_quantity is not None else sum(item["quantity"] for item in stock_by_store)
    url = plain(product.get("url"))
    if not url.startswith("https://ekt.kz/"):
        url = ""
    image = plain(product.get("image"))
    if not image.startswith("https://ekt.kz/"):
        image = ""
    return {
        "id": as_int(product.get("id")),
        "name": plain(product.get("name")),
        "article": plain(product.get("article")),
        "price": as_int(product.get("price"), -1),
        "currency": "KZT",
        "quantity": quantity,
        "stockKnown": raw_quantity is not None or bool(stock_by_store),
        "available": quantity > 0,
        "stores": stock_by_store[:5],
        "description": plain(product.get("description"))[:900],
        "specifications": specifications,
        "certificates": certificates_for(product),
        "url": url,
        "image": image,
        "role": role,
    }


def stock_total(product: dict) -> int:
    if product.get("quantity") is not None:
        return max(0, as_int(product.get("quantity")))
    stores = product.get("stores", [])
    if isinstance(stores, list):
        return sum(as_int(store.get("quantity")) for store in stores if isinstance(store, dict))
    return 0


def alternative_products(product: dict) -> list[dict]:
    properties = product.get("properties", {})
    ids = properties.get("RECOMMEND", []) if isinstance(properties, dict) else []
    if isinstance(ids, (str, int)):
        ids = [ids]
    unique_ids = []
    for raw_id in ids if isinstance(ids, list) else []:
        candidate_id = as_int(raw_id)
        if candidate_id and candidate_id != as_int(product.get("id")) and candidate_id not in unique_ids:
            unique_ids.append(candidate_id)
    if not unique_ids:
        return []
    with ThreadPoolExecutor(max_workers=min(3, len(unique_ids))) as pool:
        futures = [pool.submit(catalog.detail, product_id) for product_id in unique_ids[:3]]
        details = []
        for future in futures:
            try:
                details.append(future.result())
            except CatalogError:
                continue
    return [public_product(detail, "alternative") for detail in details if stock_total(detail) > 0]


def get_session(session_id: str) -> dict:
    if not session_id or len(session_id) > 80:
        raise ValueError("Не удалось определить сессию чата. Обновите страницу.")
    with session_lock:
        if session_id not in sessions:
            if len(sessions) >= 2000:
                oldest = next(iter(sessions))
                sessions.pop(oldest, None)
            sessions[session_id] = {"cart": {}, "pending": None}
        return sessions[session_id]


def cart_snapshot(session: dict) -> dict:
    items = []
    total = 0
    for item in session["cart"].values():
        line = dict(item)
        line["lineTotal"] = line["price"] * line["quantity"] if line["price"] >= 0 else None
        if line["lineTotal"] is not None:
            total += line["lineTotal"]
        items.append(line)
    return {"items": items, "itemCount": sum(item["quantity"] for item in items), "total": total}


PURCHASE_TERMS = re.compile(r"оплат|достав|минимальн|мин\.?\s*парт|самовывоз|сроки\s+постав", re.IGNORECASE)
ANALOG_WORDS = re.compile(r"аналог|замен|вместо|похож", re.IGNORECASE)


def answer_chat(message: str) -> dict:
    cleaned = message.strip()
    if PURCHASE_TERMS.search(cleaned):
        return {
            "text": (
                "В переданном API нет актуальных условий оплаты, доставки или минимальной партии. "
                "Чтобы не сообщать неподтверждённые условия, уточните их у менеджера Электрокомплекта."
            ),
            "products": [],
        }

    matches = catalog.search(cleaned)
    if not matches:
        return {
            "text": "Не нашёл подходящую позицию в доступной выборке каталога. Уточните артикул или модель товара.",
            "products": [],
        }

    detailed: list[dict] = []
    with ThreadPoolExecutor(max_workers=min(3, len(matches))) as pool:
        futures = [(item, pool.submit(catalog.detail, as_int(item.get("id")))) for item in matches[:3]]
        for item, future in futures:
            try:
                detailed.append(future.result())
            except CatalogError:
                detailed.append(item)

    primary = detailed[0]
    primary_public = public_product(primary)
    display_name = primary_public["name"] or "Найденный товар"
    status = (
        f"В наличии: {primary_public['quantity']} шт."
        if primary_public["stockKnown"]
        else "Остаток не указан в карточке API."
    )
    if primary_public["stockKnown"] and not primary_public["available"]:
        status = "Сейчас остаток равен нулю."

    if ANALOG_WORDS.search(cleaned):
        alternatives = alternative_products(primary)
        if alternatives:
            text = (
                f"{display_name}: {status} Ниже показаны позиции, которые каталог указывает как рекомендации. "
                "Проверьте их характеристики перед выбором."
            )
            return {"text": text, "products": [primary_public, *alternatives]}
        return {
            "text": f"{display_name}: {status} В карточке API не найдено подтверждённых аналогов или рекомендаций.",
            "products": [primary_public],
        }

    extra = " Характеристики и остаток показаны по текущему ответу API." if primary_public["stockKnown"] else ""
    if not primary_public["certificates"]:
        extra += " Ссылка на сертификат в карточке API не найдена."
    return {"text": f"Нашёл позицию: {display_name}. {status}{extra}", "products": [primary_public]}


class Handler(BaseHTTPRequestHandler):
    server_version = "EktAssistantPrototype/1.0"

    def log_message(self, _format: str, *_args: object) -> None:
        # Avoid logging user questions or request headers in this local prototype.
        return

    def send_json(self, status: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        length = as_int(self.headers.get("Content-Length"), 0)
        if length < 0 or length > MAX_BODY_BYTES:
            raise ValueError("Запрос слишком большой.")
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ValueError("Ожидался JSON-запрос.") from None
        if not isinstance(data, dict):
            raise ValueError("Ожидался JSON-объект.")
        return data

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self.send_json(200, {"ok": True, "catalogConfigured": bool(catalog.username and catalog.password)})
            return
        if parsed.path == "/api/cart":
            params = parse_qs(parsed.query)
            session = get_session((params.get("session", [""])[0]))
            self.send_json(200, {"cart": cart_snapshot(session)})
            return
        assets = {
            "/": (STATIC / "index.html", "text/html; charset=utf-8"),
            "/static/styles.css": (STATIC / "styles.css", "text/css; charset=utf-8"),
            "/static/app.js": (STATIC / "app.js", "text/javascript; charset=utf-8"),
        }
        asset = assets.get(parsed.path)
        if not asset:
            self.send_json(404, {"error": "Не найдено."})
            return
        path, content_type = asset
        content = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self) -> None:
        try:
            data = self.read_json()
            route = urlparse(self.path).path
            session_id = plain(data.get("sessionId"))
            session = get_session(session_id)

            if route == "/api/chat":
                message = plain(data.get("message"))[:3000]
                if not message.strip():
                    raise ValueError("Введите вопрос о товаре.")
                answer = answer_chat(message)
                self.send_json(200, answer)
                return

            if route == "/api/cart/prepare":
                product_id = as_int(data.get("productId"))
                quantity = as_int(data.get("quantity"))
                if product_id <= 0 or quantity < 1 or quantity > MAX_QUANTITY:
                    raise ValueError("Проверьте товар и количество.")
                product = catalog.detail(product_id, refresh=True)
                available = stock_total(product) - as_int(session["cart"].get(str(product_id), {}).get("quantity"))
                if available < 1:
                    raise ValueError("Этот товар сейчас нельзя добавить: доступный остаток равен нулю.")
                if quantity > available:
                    raise ValueError(f"Доступно не больше {available} шт. Измените количество и попробуйте снова.")
                token = uuid.uuid4().hex
                pending = {"token": token, "product": public_product(product), "quantity": quantity, "created": time.time()}
                with session_lock:
                    session["pending"] = pending
                self.send_json(200, {
                    "pending": {"token": token, "product": pending["product"], "quantity": quantity, "available": available},
                    "text": "Проверьте товар и количество. Корзина изменится только после нажатия «Да, добавить»."
                })
                return

            if route == "/api/cart/confirm":
                if data.get("confirmed") is not True:
                    raise ValueError("Для изменения корзины требуется явное подтверждение.")
                token = plain(data.get("token"))
                pending = session.get("pending")
                if not pending or pending.get("token") != token or time.time() - pending.get("created", 0) > 300:
                    session["pending"] = None
                    raise ValueError("Подтверждение устарело. Подготовьте добавление ещё раз.")
                product_id = pending["product"]["id"]
                product = catalog.detail(product_id, refresh=True)
                key = str(product_id)
                old_quantity = as_int(session["cart"].get(key, {}).get("quantity"))
                quantity = pending["quantity"]
                if old_quantity + quantity > stock_total(product):
                    session["pending"] = None
                    raise ValueError("Остаток изменился, поэтому корзина не обновлена. Проверьте товар и повторите.")
                line = public_product(product)
                line["quantity"] = old_quantity + quantity
                session["cart"][key] = line
                session["pending"] = None
                self.send_json(200, {
                    "cart": cart_snapshot(session),
                    "added": {"product": line, "quantity": quantity},
                    "text": "Товар добавлен в демонстрационную корзину. Она отображает актуальное состояние этой сессии."
                })
                return

            if route == "/api/cart/cancel":
                token = plain(data.get("token"))
                pending = session.get("pending")
                if pending and pending.get("token") == token:
                    session["pending"] = None
                self.send_json(200, {"ok": True, "cart": cart_snapshot(session)})
                return

            self.send_json(404, {"error": "Не найдено."})
        except CatalogError as exc:
            self.send_json(503, {"error": str(exc)})
        except ValueError as exc:
            self.send_json(400, {"error": str(exc)})


def main() -> None:
    host = os.environ.get("HOST", "127.0.0.1")
    port = max(1, min(as_int(os.environ.get("PORT", "8000"), 8000), 65535))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"EKT assistant prototype: http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
