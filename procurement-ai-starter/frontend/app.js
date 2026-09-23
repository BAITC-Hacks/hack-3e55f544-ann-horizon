(() => {
  "use strict";
  const USER_ID = "demo-user";
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const state = { products: [], reminderFilter: "all", toastTimer: null, listRequests: {} };
  const rejectionLabels = { booked_on_date: "Заняты на дату", over_budget: "Выше бюджета", format_mismatch: "Не подходит формат", duration_exceeded: "Не подходит длительность", language_mismatch: "Не подходит язык" };
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[char]));
  const money = (value, currency = "KZT") => {
    if (value === null || value === undefined || value === "") return "—";
    const amount = Number(value);
    if (!Number.isFinite(amount)) return "—";
    try { return new Intl.NumberFormat("ru-KZ", { maximumFractionDigits: 2 }).format(amount) + (currency === "KZT" ? " ₸" : ` ${escapeHtml(currency)}`); }
    catch { return `${escapeHtml(value)} ${escapeHtml(currency)}`; }
  };
  const formatDate = (value) => {
    if (!value) return "Дата не задана";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? escapeHtml(value) : new Intl.DateTimeFormat("ru-KZ", { dateStyle: "medium", timeStyle: "short" }).format(date);
  };
  function toast(message, isError = false) {
    const element = $("#toast");
    element.textContent = message;
    element.classList.toggle("error", isError);
    element.classList.add("show");
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(() => element.classList.remove("show"), 3400);
  }
  async function api(path, options = {}) {
    let response;
    try {
      response = await fetch(path, { ...options, headers: { ...(options.body ? { "Content-Type": "application/json" } : {}), ...(options.headers || {}) } });
    } catch {
      setConnection(false);
      throw new Error("Не удалось связаться с API. Проверьте, что локальный сервер запущен, и повторите запрос.");
    }
    setConnection(true);
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      const detail = payload?.detail;
      const message = Array.isArray(detail) ? detail.map((item) => item.msg).join("; ") : (detail || `Ошибка запроса (${response.status})`);
      throw new Error(message);
    }
    return payload;
  }
  const send = (path, body, method = "POST") => api(path, { method, body: JSON.stringify(body) });
  function setBusy(button, busy, label = "Обработка…") {
    if (!button) return;
    if (busy) { if (!button.dataset.originalText) button.dataset.originalText = button.innerHTML; button.disabled = true; button.setAttribute("aria-busy", "true"); button.innerHTML = `<span>${label}</span>`; }
    else { button.disabled = false; button.removeAttribute("aria-busy"); if (button.dataset.originalText) { button.innerHTML = button.dataset.originalText; delete button.dataset.originalText; } }
  }
  function setConnection(online) {
    const el = $("#connection-status");
    el.classList.toggle("online", online);
    el.classList.toggle("offline", !online);
    el.setAttribute("aria-label", online ? "API доступен" : "API не подключён");
    el.innerHTML = `<span class="status-dot" aria-hidden="true"></span><span>${online ? "API доступен" : "API не подключён"}</span>`;
  }
  function showEmpty(target, message) { target.innerHTML = `<div class="empty-list">${escapeHtml(message)}</div>`; }
  function formError(form, message = "") {
    let element = $(".form-error", form);
    if (!element) { element = document.createElement("p"); element.className = "form-error"; element.setAttribute("role", "alert"); form.append(element); }
    element.textContent = message;
    element.hidden = !message;
  }
  function requiredText(input) {
    input.setCustomValidity(input.value.trim() ? "" : "Введите текст запроса");
    if (!input.reportValidity()) return false;
    return true;
  }
  ["#purchase-message", "#event-category"].forEach((selector) => $(selector).addEventListener("input", (event) => event.target.setCustomValidity("")));

  function setupNavigation() {
    const names = { procurement: "Закупки", contractors: "Подрядчики", personal: "Список желаний", reminders: "Напоминания" };
    $$(".nav-item").forEach((button) => button.addEventListener("click", () => {
      $$(".nav-item").forEach((item) => {
        item.classList.toggle("active", item === button);
        if (item === button) item.setAttribute("aria-current", "page"); else item.removeAttribute("aria-current");
      });
      $$(".view").forEach((view) => view.classList.toggle("active", view.id === `view-${button.dataset.view}`));
      $("#current-section").textContent = button.dataset.title || names[button.dataset.view] || "Рабочее пространство";
      $(".view.active h1").focus({ preventScroll: true });
      window.scrollTo({ top: 0, behavior: "instant" });
      if (["personal", "reminders"].includes(button.dataset.view) && !state.products.length) loadProducts();
      if (button.dataset.view === "personal") { loadWishlist(); loadWatches(); }
      if (button.dataset.view === "reminders") loadReminders();
      document.dispatchEvent(new CustomEvent("procureline:view", { detail: { view: button.dataset.view } }));
    }));
  }

  async function loadProducts() {
    try {
      state.products = await api("/api/products");
      setConnection(true);
      const options = state.products.map((product) => `<option value="${Number(product.id)}">${escapeHtml(product.name)}${product.brand ? ` · ${escapeHtml(product.brand)}` : ""}</option>`).join("");
      ["#wishlist-product", "#watch-product"].forEach((selector) => {
        $(selector).innerHTML = `<option value="">Выберите товар</option>${options}`;
      });
      $("#reminder-product").innerHTML = `<option value="">Не выбрано</option>${options}`;
    } catch (error) {
      ["#wishlist-product", "#watch-product", "#reminder-product"].forEach((selector) => { $(selector).innerHTML = "<option value=''>Каталог недоступен</option>"; });
      toast(error.message, true);
    }
  }

  function renderPlan(plan, existingOrder = null) {
    const target = $("#procurement-result");
    target.classList.remove("empty-state");
    target.dataset.planId = plan.plan_id || "";
    let currentOrder = existingOrder;
    const showOrderResult = (order) => { $("#order-draft-result", target).innerHTML = `Черновик ${escapeHtml(order.order_id)} · статус ${escapeHtml(order.status)} · внешний заказ не создан. <button class="tiny-button" type="button" data-open-order="${escapeHtml(order.order_id)}">Открыть заказ</button>`; };
    const lines = plan.lines || [];
    const findings = [...(plan.findings || []), ...(plan.compliance_findings || [])];
    const lineHtml = lines.length ? lines.map((line) => `
      <div class="purchase-line"><div><strong>${escapeHtml(line.product_name)} · ${Number(line.quantity)} шт.</strong><small>${escapeHtml(line.supplier_name)} · ${Number(line.delivery_days)} дн. · ${escapeHtml(line.match_type)}</small></div><div class="line-amount">${money(line.merchandise_subtotal, plan.currency)}<small>${money(line.unit_price, plan.currency)} / шт.</small></div></div>`).join("") : `<div class="empty-inline">Подходящих строк в каталоге не найдено.</div>`;
    const findingHtml = findings.length ? `<div class="findings">${findings.map((finding) => `<span>• ${escapeHtml(finding.message)}</span>`).join("")}</div>` : "";
    const explanationHtml = (plan.explanation || []).length ? `<details class="plan-details"><summary>Почему выбран этот план</summary><ul>${plan.explanation.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></details>` : "";
    const risksHtml = (plan.risks || []).length ? `<details class="plan-details"><summary>Риски и основания (${plan.risks.length})</summary><ul>${plan.risks.map((item) => `<li>${escapeHtml(item.reason)}${item.evidence?.length ? `<small>${item.evidence.map(escapeHtml).join("; ")}</small>` : ""}</li>`).join("")}</ul></details>` : "";
    const comparisons = (plan.price_summary?.history_comparisons || []).filter((item) => plan.selected_offer_ids?.includes(item.offer_id));
    const priceHistoryHtml = comparisons.length ? `<details class="plan-details"><summary>Сравнение с историей цен</summary><p>Синтетическая demo-история, не рыночные котировки.</p><ul>${comparisons.map((item) => { const line = lines.find((entry) => entry.offer_id === item.offer_id); return `<li>${escapeHtml(line?.product_name || `Предложение ${item.offer_id}`)} · ${escapeHtml(line?.supplier_name || "")}<small>Сейчас ${money(item.current_unit_price, plan.currency)} · медиана истории ${money(item.median_historical_unit_price, plan.currency)} · ${item.status === "unknown" ? "Недостаточно свежей истории" : `${escapeHtml(item.deviation_percent)}% к медиане`} · ${Number(item.sample_count)} наблюдений</small></li>`; }).join("")}</ul></details>` : "";
    const canCreateOrder = !existingOrder && plan.plan_id && plan.status === "READY_FOR_REVIEW" && lines.length && !["REJECTED", "BLOCKED"].includes(plan.approval_status);
    const approvalRole = plan.approval_role || "finance";
    const demoReviewer = { manager: "demo-manager", finance: "demo-finance" }[approvalRole] || "demo-finance";
    const approvalHtml = plan.approval_status === "PENDING" && plan.approval_id ? `
      <div class="approval-box"><div><strong>Нужно согласование: ${escapeHtml(approvalRole)}</strong><small>Демо-решение от ${escapeHtml(demoReviewer)} · без проверки личности</small></div><div class="approval-buttons"><button class="tiny-button" data-approval-decision="approved">Согласовать</button><button class="tiny-button danger" data-approval-decision="rejected">Отклонить</button></div></div><div id="approval-result" class="action-result" aria-live="polite"></div>` : "";
    target.innerHTML = `
      <div class="plan-overview"><div><span class="status-tag">${escapeHtml(plan.status)} · ${escapeHtml(plan.approval_status || "REVIEW")}</span><h3>${plan.status === "READY_FOR_REVIEW" ? "План подготовлен" : "План требует проверки"}</h3><p>${plan.plan_id ? `ID: ${escapeHtml(plan.plan_id)}` : "Не сохранён"}</p></div><div class="plan-total">${money(plan.merchandise_subtotal, plan.currency)}<small>товарная сумма · без доставки и налогов</small></div></div>
      <div class="metrics-row"><div class="metric"><strong>${Number(plan.quantity_planned)} / ${Number(plan.quantity_requested)}</strong><small>запланировано / запрошено</small></div><div class="metric"><strong>${lines.length}</strong><small>строк заказа</small></div><div class="metric"><strong>${(plan.supplier_assessments || []).length}</strong><small>поставщиков</small></div></div>
      <div class="line-list">${lineHtml}</div>${findingHtml}${explanationHtml}${risksHtml}${priceHistoryHtml}${approvalHtml}
      <div class="plan-actions"><p>Только локальный черновик · внешнего заказа нет</p>${canCreateOrder ? `<button id="create-order-draft" class="secondary-button" type="button">Создать черновик <span>↗</span></button>` : ""}</div><div id="order-draft-result" class="action-result" aria-live="polite"></div>`;
    if (currentOrder) showOrderResult(currentOrder);
    target.querySelectorAll("[data-approval-decision]").forEach((button) => button.addEventListener("click", async () => {
      const decisionButtons = [...target.querySelectorAll("[data-approval-decision]")];
      decisionButtons.forEach((item) => { item.disabled = true; });
      const draftButton = $("#create-order-draft", target);
      if (draftButton) draftButton.disabled = true;
      setBusy(button, true, "Отправляем…");
      try {
        const decision = button.dataset.approvalDecision;
        const result = await send(`/api/procurement/approvals/${encodeURIComponent(plan.approval_id)}/decision`, {
          decision, reviewer_id: demoReviewer, reviewer_role: approvalRole,
          comment: "Demo-решение из локального веб-интерфейса"
        });
        if (target.dataset.planId !== plan.plan_id) { toast("Решение по предыдущему плану сохранено"); return; }
        plan.approval_status = result.status;
        if (result.status === "REJECTED") $("#create-order-draft", target)?.remove();
        if (currentOrder) {
          currentOrder.status = result.status === "APPROVED" ? "APPROVED" : "CANCELLED";
          showOrderResult(currentOrder);
        }
        const statusTag = target.querySelector(".status-tag");
        if (statusTag) statusTag.textContent = `${plan.status} · ${result.status}`;
        $(".approval-box", target)?.remove();
        $("#approval-result", target).textContent = `Демо-согласование: ${result.status}. Идентификация reviewer не подключена.`;
        toast(result.status === "APPROVED" ? "План согласован в demo-режиме" : "План отклонён в demo-режиме");
      } catch (error) { toast(error.message, true); }
      finally { setBusy(button, false); decisionButtons.forEach((item) => { item.disabled = false; }); if (draftButton) draftButton.disabled = false; }
    }));
    const orderButton = $("#create-order-draft", target);
    orderButton?.addEventListener("click", async () => {
      setBusy(orderButton, true, "Создаём черновик…");
      const decisionButtons = [...target.querySelectorAll("[data-approval-decision]")];
      decisionButtons.forEach((item) => { item.disabled = true; });
      try {
        const order = await send(`/api/procurement/plans/${encodeURIComponent(plan.plan_id)}/order`, { buyer_note: "Создано из локального веб-интерфейса" });
        if (target.dataset.planId !== plan.plan_id) { toast(`Черновик ${order.order_id} сохранён для предыдущего плана`); return; }
        currentOrder = order;
        orderButton.remove();
        showOrderResult(order);
        toast("Локальный черновик заказа сохранён");
      } catch (error) { if (target.dataset.planId === plan.plan_id) $("#order-draft-result", target).textContent = error.message; toast(error.message, true); }
      finally { setBusy(orderButton, false); decisionButtons.forEach((item) => { item.disabled = false; }); }
    });
  }
  $("#procurement-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!requiredText($("#purchase-message"))) return;
    formError(event.currentTarget);
    const button = $("#procurement-form button[type=submit]");
    setBusy(button, true, "Формируем план…");
    try {
      const userType = $("#purchase-user-type").value;
      const plan = await send("/api/chat", { message: $("#purchase-message").value.trim(), user_context: { user_id: USER_ID, user_type: userType, organization_id: userType === "business" ? "demo-org" : null, currency: "KZT" } });
      setConnection(true); renderPlan(plan); toast(plan.status === "READY_FOR_REVIEW" ? "План закупки готов к проверке" : "План требует изменений: проверьте ограничения");
    } catch (error) { formError($("#procurement-form"), error.message); toast(error.message, true); }
    finally { setBusy(button, false); }
  });

  $("#contractor-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!requiredText($("#event-category"))) return;
    const button = $("#contractor-form button[type=submit]");
    const result = $("#contractor-result");
    result.classList.remove("empty-state", "compact-empty");
    setBusy(button, true, "Ищем совпадения…");
    result.innerHTML = `<div class="empty-state compact-empty"><div class="loading-line">Сверяем город, формат, дату и бюджет…</div></div>`;
    const duration = $("#event-duration").value;
    const language = $("#event-language").value.trim();
    const body = { city: $("#event-city").value, event_date: $("#event-date").value, event_type: $("#event-type").value, category: $("#event-category").value.trim(), budget_kzt: Number($("#event-budget").value), limit: 3 };
    if (duration) body.duration_hours = Number(duration);
    if (language) body.language = language;
    try {
      const data = await send("/api/contractors/search", body);
      setConnection(true);
      if (!data.cards.length) {
        result.innerHTML = `<div class="empty-state compact-empty"><div class="empty-illustration"><span class="empty-ring"></span><span class="empty-box">⌕</span></div><h3>${escapeHtml(data.outcome === "CATEGORY_NOT_FOUND" ? "Категория не найдена" : "Нет подходящих кандидатов")}</h3><p>${escapeHtml(data.message)}</p><span class="source-badge">${escapeHtml(data.source_label)}</span><div class="data-badges">${Object.entries(data.rejection_reasons || {}).map(([key, count]) => `<span class="data-badge">${escapeHtml(rejectionLabels[key] || key)}: ${Number(count)}</span>`).join("")}</div></div>`;
      } else {
        result.innerHTML = `<div class="contractor-results-header"><span><strong>${Number(data.matched_count)} ${data.matched_count === 1 ? "рекомендация" : "рекомендации"}</strong> · ${escapeHtml(data.message)}</span><span class="source-badge">${escapeHtml(data.source_label)}</span></div><div class="contractor-grid">${data.cards.map((card) => `<article class="contractor-card"><div class="contractor-card-top"><div><h3>${escapeHtml(card.name)}</h3><div class="contractor-category">${escapeHtml(card.category)} · ${escapeHtml(card.city)}</div></div><span class="source-badge">${escapeHtml(card.source_label)}</span></div><div class="contractor-price">${money(card.price_from_kzt)}<small>цена от</small></div><div class="match-explanation">${escapeHtml(card.explanation)}</div><div class="data-badges">${card.synthetic ? `<span class="data-badge">SYNTHETIC · синтетический профиль</span>` : ""}${card.city_imputed ? `<span class="data-badge">город восстановлен</span>` : ""}${card.price_imputed ? `<span class="data-badge">цена восстановлена</span>` : ""}</div></article>`).join("")}</div>`;
      }
    } catch (error) { result.innerHTML = `<div class="empty-state compact-empty"><h3>Не удалось выполнить подбор</h3><p>${escapeHtml(error.message)}</p></div>`; toast(error.message, true); }
    finally { setBusy(button, false); }
  });

  async function loadWishlist() {
    const requestId = (state.listRequests.loadWishlist || 0) + 1;
    state.listRequests.loadWishlist = requestId;
    const target = $("#wishlist-list");
    target.innerHTML = `<div class="loading-line">Обновляем список…</div>`;
    try {
      const entries = await api(`/api/personal/wishlist?user_id=${encodeURIComponent(USER_ID)}`);
      if (requestId !== state.listRequests.loadWishlist) return;
      if (!entries.length) return showEmpty(target, "Список пока пуст. Добавьте товар, который хотите отслеживать.");
      target.innerHTML = entries.map((item) => `<article class="item-row"><div class="item-row-main"><h3>${escapeHtml(item.product_name)}</h3><p class="price-emphasis">Сейчас: ${money(item.current_price, item.currency)}${item.target_price ? ` · цель: ${money(item.target_price, item.currency)}` : ""}</p><p>${item.supplier_name ? `Предложение: ${escapeHtml(item.supplier_name)} · ` : ""}${escapeHtml(item.note || "Добавлено в список желаний")}</p></div><div class="item-row-actions"><button class="tiny-button danger" data-remove-wishlist="${escapeHtml(item.wishlist_id)}">Удалить</button></div></article>`).join("");
    } catch (error) { if (requestId === state.listRequests.loadWishlist) showEmpty(target, error.message); }
  }
  $("#wishlist-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    formError(event.currentTarget);
    const button = $("#wishlist-form button[type=submit]");
    setBusy(button, true, "Сохраняем…");
    const body = { user_id: USER_ID, product_id: Number($("#wishlist-product").value), currency: "KZT" };
    const target = $("#wishlist-target").value;
    const note = $("#wishlist-note").value.trim();
    if (target) body.target_price = Number(target);
    if (note) body.note = note;
    try { await send("/api/personal/wishlist", body); $("#wishlist-form").reset(); toast("Товар добавлен в список желаний"); await loadWishlist(); }
    catch (error) { formError($("#wishlist-form"), error.message); toast(error.message, true); }
    finally { setBusy(button, false); }
  });
  $("#wishlist-list").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-remove-wishlist]");
    if (!button || button.disabled) return;
    setBusy(button, true, "Подождите…");
    try { await api(`/api/personal/wishlist/${encodeURIComponent(button.dataset.removeWishlist)}?user_id=${encodeURIComponent(USER_ID)}`, { method: "DELETE" }); toast("Товар удалён"); await loadWishlist(); }
    catch (error) { toast(error.message, true); }
    finally { setBusy(button, false); }
  });
  $("#refresh-wishlist").addEventListener("click", loadWishlist);

  async function loadWatches() {
    const requestId = (state.listRequests.loadWatches || 0) + 1;
    state.listRequests.loadWatches = requestId;
    const target = $("#watch-list");
    target.innerHTML = `<div class="loading-line">Обновляем наблюдения…</div>`;
    try {
      const entries = await api(`/api/personal/price-watches?user_id=${encodeURIComponent(USER_ID)}`);
      if (requestId !== state.listRequests.loadWatches) return;
      $("#watch-summary").textContent = `${entries.filter((item) => item.status === "ACTIVE").length} активных · ${entries.length} всего`;
      if (!entries.length) return showEmpty(target, "Наблюдений пока нет. Создайте мониторинг цены выше.");
      target.innerHTML = entries.map((item) => {
        const statusClass = item.status === "PAUSED" ? "paused" : (item.status === "TRIGGERED" ? "triggered" : "");
        const statusLabel = item.status === "ACTIVE" ? "АКТИВНО" : (item.status === "PAUSED" ? "ПАУЗА" : "ЦЕЛЬ ДОСТИГНУТА");
        const action = item.status === "ACTIVE" ? `<button class="tiny-button" data-watch-action="pause" data-watch-id="${escapeHtml(item.watch_id)}">Пауза</button>` : `<button class="tiny-button" data-watch-action="activate" data-watch-id="${escapeHtml(item.watch_id)}">Возобновить</button>`;
        return `<article class="item-row"><div class="item-row-main"><h3>${escapeHtml(item.product_name)} <span class="status-chip ${statusClass}">${statusLabel}</span></h3><p>Старт: ${money(item.baseline_price, item.currency)} · последняя цена: ${money(item.last_observed_price, item.currency)} · цель: ${money(item.target_price, item.currency)}</p></div><div class="item-row-actions">${action}<button class="tiny-button" data-watch-action="events" data-watch-id="${escapeHtml(item.watch_id)}">История</button></div></article>`;
      }).join("");
    } catch (error) { if (requestId === state.listRequests.loadWatches) showEmpty(target, error.message); }
  }
  $("#watch-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    formError(event.currentTarget);
    const button = $("#watch-form button[type=submit]");
    setBusy(button, true, "Создаём…");
    try {
      await send("/api/personal/price-watches", { user_id: USER_ID, product_id: Number($("#watch-product").value), target_price: Number($("#watch-target").value), currency: "KZT" });
      $("#watch-form").reset(); toast("Мониторинг цены создан"); await loadWatches();
    } catch (error) { formError($("#watch-form"), error.message); toast(error.message, true); }
    finally { setBusy(button, false); }
  });
  $("#watch-list").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-watch-action]");
    if (!button || button.disabled) return;
    setBusy(button, true, "Подождите…");
    const watchId = button.dataset.watchId;
    try {
      if (button.dataset.watchAction === "events") {
        const events = await api(`/api/personal/price-watches/${encodeURIComponent(watchId)}/events?user_id=${encodeURIComponent(USER_ID)}`);
        $("#watch-alerts").hidden = false;
        $("#watch-alerts").textContent = events.length ? events.map((item) => `${item.event_type === "TARGET_REACHED" ? "Цель достигнута" : "Цена снизилась"}: ${money(item.previous_price, item.currency)} → ${money(item.current_price, item.currency)} · ${formatDate(item.occurred_at)}`).join(" | ") : "Событий пока нет.";
      } else {
        const status = button.dataset.watchAction === "pause" ? "PAUSED" : "ACTIVE";
        await send(`/api/personal/price-watches/${encodeURIComponent(watchId)}/status?user_id=${encodeURIComponent(USER_ID)}`, { status });
        toast(status === "PAUSED" ? "Мониторинг приостановлен" : "Мониторинг возобновлён"); await loadWatches();
      }
    } catch (error) { toast(error.message, true); }
    finally { setBusy(button, false); }
  });
  $("#evaluate-watches").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    setBusy(button, true, "Проверяем…");
    try {
      const result = await send(`/api/personal/price-watches/evaluate?user_id=${encodeURIComponent(USER_ID)}`, {});
      const alertBox = $("#watch-alerts");
      alertBox.hidden = false;
      alertBox.innerHTML = result.alerts.length ? result.alerts.map((item) => `<div><strong>${item.event_type === "TARGET_REACHED" ? "Целевая цена достигнута" : "Зафиксировано снижение"}</strong> · ${escapeHtml(item.product_name)} · ${money(item.previous_price, item.currency)} → ${money(item.current_price, item.currency)}</div>`).join("") : `Проверено наблюдений: ${Number(result.evaluated_count)}. Изменений цены не обнаружено.`;
      await loadWatches();
      toast(result.alerts.length ? `Найдено событий: ${result.alert_count}` : "Проверка завершена, изменений нет");
    } catch (error) { toast(error.message, true); }
    finally { setBusy(button, false); }
  });

  async function loadReminders() {
    const requestId = (state.listRequests.loadReminders || 0) + 1;
    state.listRequests.loadReminders = requestId;
    const target = $("#reminder-list");
    target.innerHTML = `<div class="loading-line">Обновляем напоминания…</div>`;
    try {
      const path = `/api/personal/reminders?user_id=${encodeURIComponent(USER_ID)}${state.reminderFilter === "due" ? "&due_only=true" : ""}`;
      const entries = await api(path);
      if (requestId !== state.listRequests.loadReminders) return;
      $("#reminder-summary").textContent = `${entries.filter((item) => item.status === "DUE").length} наступили · ${entries.length} в списке`;
      if (!entries.length) return showEmpty(target, state.reminderFilter === "due" ? "Наступивших напоминаний нет." : "Напоминаний пока нет.");
      target.innerHTML = entries.map((item) => {
        const statusClass = item.status.toLowerCase();
        const label = { SCHEDULED: "ЗАПЛАНИРОВАНО", DUE: "НАСТУПИЛО", COMPLETED: "ВЫПОЛНЕНО", CANCELLED: "ОТМЕНЕНО" }[item.status] || item.status;
        const product = item.product_name || item.product_query || "Покупка";
        const actions = ["SCHEDULED", "DUE"].includes(item.status) ? `<button class="tiny-button" data-reminder-action="COMPLETED" data-reminder-id="${escapeHtml(item.reminder_id)}">Готово</button><button class="tiny-button danger" data-reminder-action="CANCELLED" data-reminder-id="${escapeHtml(item.reminder_id)}">Отменить</button>` : "";
        return `<article class="item-row"><div class="item-row-main"><h3>${escapeHtml(product)} <span class="status-chip ${statusClass}">${label}</span></h3><p>${Number(item.quantity)} шт. · ${formatDate(item.remind_at)}${item.note ? ` · ${escapeHtml(item.note)}` : ""}</p></div><div class="item-row-actions">${actions}</div></article>`;
      }).join("");
    } catch (error) { if (requestId === state.listRequests.loadReminders) showEmpty(target, error.message); }
  }
  $("#reminder-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    formError(event.currentTarget);
    const button = $("#reminder-form button[type=submit]");
    const productId = $("#reminder-product").value;
    const query = $("#reminder-query").value.trim();
    if ((!productId && !query) || (productId && query)) {
      formError($("#reminder-form"), productId && query ? "Укажите только товар из каталога или только поисковый запрос." : "Выберите товар или введите название.");
      $(productId ? "#reminder-query" : "#reminder-product").focus(); return;
    }
    const remindAt = new Date($("#reminder-at").value);
    if (Number.isNaN(remindAt.getTime())) { formError($("#reminder-form"), "Укажите корректную дату и время"); return; }
    const body = { user_id: USER_ID, quantity: Number($("#reminder-quantity").value), remind_at: remindAt.toISOString() };
    if (productId) body.product_id = Number(productId); else body.product_query = query;
    const note = $("#reminder-note").value.trim();
    if (note) body.note = note;
    setBusy(button, true, "Сохраняем…");
    try { await send("/api/personal/reminders", body); $("#reminder-form").reset(); toast("Напоминание сохранено"); await loadReminders(); }
    catch (error) { formError($("#reminder-form"), error.message); toast(error.message, true); }
    finally { setBusy(button, false); }
  });
  $("#reminder-list").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-reminder-action]");
    if (!button || button.disabled) return;
    setBusy(button, true, "Подождите…");
    try {
      await send(`/api/personal/reminders/${encodeURIComponent(button.dataset.reminderId)}/status?user_id=${encodeURIComponent(USER_ID)}`, { status: button.dataset.reminderAction });
      toast(button.dataset.reminderAction === "COMPLETED" ? "Напоминание выполнено" : "Напоминание отменено"); await loadReminders();
    } catch (error) { toast(error.message, true); }
    finally { setBusy(button, false); }
  });
  $("#refresh-reminders").addEventListener("click", loadReminders);
  $$("[data-reminder-filter]").forEach((button) => button.addEventListener("click", () => {
    state.reminderFilter = button.dataset.reminderFilter;
    $$("[data-reminder-filter]").forEach((item) => { item.classList.toggle("active", item === button); item.setAttribute("aria-pressed", String(item === button)); });
    loadReminders();
  }));

  window.Procureline = {
    api, send, money, escapeHtml, formatDate, toast, setBusy, renderPlan, userId: USER_ID,
    openView(view) { document.querySelector(`.nav-item[data-view="${view}"]`)?.click(); }
  };
  setupNavigation();
  loadProducts().then(() => { loadWishlist(); loadWatches(); loadReminders(); });
})();
