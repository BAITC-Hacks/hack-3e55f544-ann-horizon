(() => {
  const conversation = document.getElementById("conversation");
  const form = document.getElementById("chat-form");
  const input = document.getElementById("message-input");
  const sendButton = document.getElementById("send-button");
  const suggestions = document.getElementById("suggestions");
  const cartPanel = document.getElementById("cart-panel");
  const cartItems = document.getElementById("cart-items");
  const cartSummary = document.getElementById("cart-summary");
  const sessionKey = "ekt-assistant-session";

  function makeSessionId() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") return window.crypto.randomUUID();
    return `session-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }
  let sessionId;
  try {
    sessionId = localStorage.getItem(sessionKey);
    if (!sessionId) {
      sessionId = makeSessionId();
      localStorage.setItem(sessionKey, sessionId);
    }
  } catch (_error) {
    sessionId = makeSessionId();
  }

  const money = (value) => {
    if (value === null || value === undefined || value < 0) return "Цена не указана";
    return `${new Intl.NumberFormat("ru-KZ", { maximumFractionDigits: 0 }).format(value)} ₸`;
  };
  const timeNow = () => new Intl.DateTimeFormat("ru-KZ", { hour: "2-digit", minute: "2-digit" }).format(new Date());

  async function api(path, data) {
    const response = await fetch(path, {
      method: data ? "POST" : "GET",
      headers: data ? { "Content-Type": "application/json" } : {},
      body: data ? JSON.stringify(data) : undefined,
      credentials: "same-origin",
    });
    let payload;
    try { payload = await response.json(); } catch (_error) { payload = {}; }
    if (!response.ok) throw new Error(payload.error || "Не удалось выполнить запрос. Попробуйте ещё раз.");
    return payload;
  }

  function setConnection(state, label) {
    const connection = document.querySelector(".connection");
    connection.classList.remove("online", "offline");
    if (state) connection.classList.add(state);
    document.getElementById("connection-label").textContent = label;
  }

  function appendMessage(role, text, products = []) {
    const article = document.createElement("article");
    article.className = `message ${role === "user" ? "message-user" : "message-assistant"}`;
    const avatar = document.createElement("div");
    avatar.className = "message-avatar";
    avatar.setAttribute("aria-hidden", "true");
    avatar.textContent = role === "user" ? "Вы" : "Э";
    const body = document.createElement("div");
    body.className = "message-body";
    const meta = document.createElement("div");
    meta.className = "message-meta";
    const label = document.createElement("strong");
    label.textContent = role === "user" ? "Вы" : "Ассистент";
    const time = document.createElement("time");
    time.textContent = timeNow();
    meta.append(label, time);
    body.append(meta);
    if (text) {
      const paragraph = document.createElement("p");
      paragraph.textContent = text;
      body.append(paragraph);
    }
    article.append(avatar, body);
    conversation.append(article);
    if (role !== "user" && products.length) renderProducts(products);
    scrollToBottom();
    return body;
  }

  function addLink(parent, text, href, className) {
    if (!href || !href.startsWith("https://ekt.kz/")) return;
    const link = document.createElement("a");
    link.className = className;
    link.href = href;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = text;
    parent.append(link);
  }

  function renderProducts(products) {
    const list = document.createElement("div");
    list.className = "product-list";
    for (const product of products) list.append(renderProduct(product));
    conversation.append(list);
    scrollToBottom();
  }

  function renderProduct(product) {
    const card = document.createElement("article");
    card.className = "product-card";
    const top = document.createElement("div");
    top.className = "product-card-top";

    const image = document.createElement("div");
    image.className = "product-image";
    if (product.image && product.image.startsWith("https://")) {
      const img = document.createElement("img");
      img.src = product.image;
      img.alt = "";
      img.loading = "lazy";
      img.addEventListener("error", () => { img.remove(); image.textContent = "ЭК"; }, { once: true });
      image.append(img);
    } else image.textContent = "ЭК";

    const identity = document.createElement("div");
    const tag = document.createElement("span");
    tag.className = `product-tag ${product.stockKnown && product.available ? "available" : "unavailable"}`;
    if (product.role === "alternative") tag.textContent = "Рекомендация каталога";
    else if (!product.stockKnown) tag.textContent = "Остаток уточняется";
    else tag.textContent = product.available ? `В наличии · ${product.quantity} шт.` : "Нет в наличии";
    const name = document.createElement("h3");
    name.className = "product-name";
    name.textContent = product.name || "Товар из каталога";
    const article = document.createElement("div");
    article.className = "product-article";
    article.textContent = `Артикул ${product.article || "не указан"}`;
    identity.append(tag, name, article);
    top.append(image, identity);

    const details = document.createElement("div");
    details.className = "product-details";
    const price = document.createElement("div");
    price.className = "product-price";
    price.textContent = money(product.price);
    details.append(price);

    if (product.description) {
      const description = document.createElement("p");
      description.className = "product-description";
      description.textContent = product.description;
      details.append(description);
    }

    if (Array.isArray(product.specifications) && product.specifications.length) {
      const specs = document.createElement("ul");
      specs.className = "spec-list";
      for (const spec of product.specifications.slice(0, 5)) {
        const row = document.createElement("li");
        const label = document.createElement("span");
        const value = document.createElement("strong");
        label.textContent = spec.name;
        value.textContent = spec.value;
        row.append(label, value);
        specs.append(row);
      }
      details.append(specs);
    }

    if (Array.isArray(product.stores) && product.stores.length) {
      const stores = document.createElement("p");
      stores.className = "store-list";
      stores.textContent = `Склады: ${product.stores.slice(0, 3).map((store) => `${store.name} — ${store.quantity} шт.`).join(" · ")}`;
      details.append(stores);
    }

    if (Array.isArray(product.certificates) && product.certificates.length) {
      for (const certificate of product.certificates.slice(0, 3)) addLink(details, certificate.label || "Сертификат", certificate.url, "certificate-link");
    } else {
      const certificateNote = document.createElement("div");
      certificateNote.className = "store-list";
      certificateNote.textContent = "Сертификат в API не найден";
      details.append(certificateNote);
    }
    addLink(details, "Карточка ekt.kz ↗", product.url, "catalog-link");

    if (product.stockKnown && product.available) {
      const actions = document.createElement("div");
      actions.className = "product-actions";
      const quantity = document.createElement("input");
      quantity.className = "quantity-input";
      quantity.type = "number";
      quantity.min = "1";
      quantity.max = String(product.quantity);
      quantity.value = "1";
      quantity.setAttribute("aria-label", `Количество: ${product.name}`);
      const prepare = document.createElement("button");
      prepare.className = "prepare-button";
      prepare.type = "button";
      prepare.textContent = "Подготовить добавление";
      prepare.addEventListener("click", async () => {
        const qty = Number.parseInt(quantity.value, 10);
        if (!Number.isInteger(qty) || qty < 1 || qty > product.quantity) {
          appendMessage("assistant", `Для этой позиции доступно от 1 до ${product.quantity} шт. Укажите количество в этих пределах.`);
          return;
        }
        prepare.disabled = true;
        try {
          const result = await api("/api/cart/prepare", { sessionId, productId: product.id, quantity: qty });
          appendMessage("assistant", result.text);
          renderConfirmation(result.pending);
        } catch (error) {
          appendMessage("assistant", error.message);
        } finally {
          prepare.disabled = false;
        }
      });
      actions.append(quantity, prepare);
      details.append(actions);
    } else {
      const unavailable = document.createElement("div");
      unavailable.className = "product-unavailable";
      unavailable.textContent = product.stockKnown ? "Добавление недоступно: остаток 0" : "Количество нужно уточнить у менеджера";
      details.append(unavailable);
    }

    card.append(top, details);
    return card;
  }

  function renderConfirmation(pending) {
    const card = document.createElement("section");
    card.className = "confirm-card";
    const title = document.createElement("p");
    title.className = "confirm-title";
    title.textContent = "Подтвердите добавление";
    const copy = document.createElement("p");
    copy.className = "confirm-copy";
    copy.textContent = `${pending.quantity} шт. · ${pending.product.name}. Доступно на момент проверки: ${pending.available} шт. Корзина ещё не менялась.`;
    const actions = document.createElement("div");
    actions.className = "confirm-actions";
    const confirm = document.createElement("button");
    confirm.type = "button";
    confirm.className = "confirm-button";
    confirm.textContent = "Да, добавить";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "cancel-button";
    cancel.textContent = "Отмена";
    confirm.addEventListener("click", async () => {
      confirm.disabled = true;
      cancel.disabled = true;
      try {
        const result = await api("/api/cart/confirm", { sessionId, token: pending.token, confirmed: true });
        card.remove();
        appendMessage("assistant", result.text);
        renderCart(result.cart);
      } catch (error) {
        appendMessage("assistant", error.message);
        card.remove();
      }
    });
    cancel.addEventListener("click", async () => {
      confirm.disabled = true;
      cancel.disabled = true;
      try { await api("/api/cart/cancel", { sessionId, token: pending.token }); }
      catch (_error) { /* The cart was not changed; ignore a failed cleanup request. */ }
      card.remove();
      appendMessage("assistant", "Добавление отменено. Корзина не изменилась.");
    });
    actions.append(confirm, cancel);
    card.append(title, copy, actions);
    conversation.append(card);
    scrollToBottom();
  }

  function renderCart(cart) {
    const items = Array.isArray(cart.items) ? cart.items : [];
    document.getElementById("header-cart-count").textContent = String(cart.itemCount || 0);
    document.getElementById("panel-cart-count").textContent = String(cart.itemCount || 0);
    cartItems.replaceChildren();
    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "empty-cart";
      const icon = document.createElement("div");
      icon.className = "empty-cart-icon";
      icon.setAttribute("aria-hidden", "true");
      icon.textContent = "＋";
      const title = document.createElement("strong");
      title.textContent = "Пока здесь пусто";
      const copy = document.createElement("p");
      copy.textContent = "Найдите товар в чате. Перед добавлением вы увидите карточку подтверждения.";
      empty.append(icon, title, copy);
      cartItems.append(empty);
      cartSummary.hidden = true;
      return;
    }
    for (const product of items) {
      const line = document.createElement("article");
      line.className = "cart-line";
      const thumbnail = document.createElement("div");
      thumbnail.className = "cart-line-image";
      if (product.image && product.image.startsWith("https://")) {
        const img = document.createElement("img");
        img.src = product.image;
        img.alt = "";
        img.loading = "lazy";
        img.addEventListener("error", () => { img.remove(); thumbnail.textContent = "ЭК"; }, { once: true });
        thumbnail.append(img);
      } else thumbnail.textContent = "ЭК";
      const details = document.createElement("div");
      const name = document.createElement("strong");
      name.className = "cart-line-name";
      name.textContent = product.name;
      const meta = document.createElement("div");
      meta.className = "cart-line-meta";
      meta.textContent = `${product.quantity} шт. · ${money(product.price)} за шт.`;
      details.append(name, meta);
      line.append(thumbnail, details);
      cartItems.append(line);
    }
    document.getElementById("summary-count").textContent = String(cart.itemCount || 0);
    document.getElementById("summary-total").textContent = money(cart.total);
    cartSummary.hidden = false;
  }

  async function submitMessage(message) {
    const trimmed = message.trim();
    if (!trimmed) return;
    suggestions.hidden = true;
    appendMessage("user", trimmed);
    input.value = "";
    input.style.height = "auto";
    sendButton.disabled = true;
    const waiting = appendMessage("assistant", "");
    const dots = document.createElement("span");
    dots.className = "typing-indicator";
    dots.setAttribute("aria-label", "Идёт поиск по каталогу");
    for (let index = 0; index < 3; index += 1) dots.append(document.createElement("i"));
    waiting.append(dots);
    try {
      const result = await api("/api/chat", { sessionId, message: trimmed });
      waiting.parentElement.remove();
      appendMessage("assistant", result.text, result.products || []);
    } catch (error) {
      waiting.parentElement.remove();
      appendMessage("assistant", error.message);
      setConnection("offline", "Каталог недоступен");
    } finally {
      sendButton.disabled = false;
      input.focus();
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    submitMessage(input.value);
  });
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 115)}px`;
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  for (const button of document.querySelectorAll(".suggestion")) {
    button.addEventListener("click", () => submitMessage(button.dataset.prompt || ""));
  }
  document.getElementById("cart-toggle").addEventListener("click", () => {
    const open = cartPanel.classList.toggle("open");
    document.getElementById("cart-toggle").setAttribute("aria-expanded", String(open));
  });
  document.getElementById("close-cart").addEventListener("click", () => {
    cartPanel.classList.remove("open");
    document.getElementById("cart-toggle").setAttribute("aria-expanded", "false");
  });
  document.getElementById("checkout-link").addEventListener("click", () => {
    cartPanel.classList.add("open");
    document.getElementById("cart-toggle").setAttribute("aria-expanded", "true");
  });

  api("/api/health").then((health) => {
    setConnection(health.catalogConfigured ? "online" : "offline", health.catalogConfigured ? "Каталог подключён" : "Нужен доступ к каталогу");
  }).catch(() => setConnection("offline", "Сервер недоступен"));
  api(`/api/cart?session=${encodeURIComponent(sessionId)}`).then((result) => renderCart(result.cart)).catch(() => {});
})();
