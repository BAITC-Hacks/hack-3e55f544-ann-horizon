(() => {
  "use strict";
  const { api, send, money, escapeHtml: h, formatDate, toast, setBusy, openView, renderPlan } = window.Procureline;
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const state = { products: [], offers: [], suppliers: [], orders: [], order: null, orderVersion: 0, ordersVersion: 0, invoices: [], currency: "", events: [], receipts: [] };
  const labels = { DRAFT: "Черновик", PENDING_APPROVAL: "Ожидает согласования", APPROVED: "Согласован", ORDERED: "Заказ подтверждён вручную", SHIPPED: "В пути", DELAYED: "Задержка", DELIVERED: "Доставлен", RECEIVED: "Принят", CANCELLED: "Отменён", READY_FOR_REVIEW: "Готов к проверке", BLOCKED: "Заблокирован", NOT_REQUIRED: "Согласование не требуется", PENDING: "Ожидает решения", REJECTED: "Отклонён", NOT_EVALUATED: "Не оценён", MATCHED: "Сверка пройдена", VARIANCE: "Есть расхождения", PENDING_RECEIVING: "Ожидает приёмки", NOT_PAID: "Не оплачен" };
  const status = (value) => `<span class="business-status">${h(labels[value] || value)}</span>`;
  const empty = (text) => `<div class="empty-list">${h(text)}</div>`;
  const loading = (id) => { $(id).innerHTML = '<div class="loading-line">Загружаем данные…</div>'; };
  const table = (headers, rows, message = "Записей пока нет.") => rows.length ? `<div class="table-scroll" tabindex="0" role="region" aria-label="Таблица данных"><table class="business-table"><thead><tr>${headers.map((name) => `<th scope="col">${h(name)}</th>`).join("")}</tr></thead><tbody>${rows.map((cells) => `<tr>${cells.map((cell) => `<td>${cell}</td>`).join("")}</tr>`).join("")}</tbody></table></div>` : empty(message);
  const shortId = (id) => h(String(id).slice(0, 8));
  const feedback = (id, message = "", error = false) => { const target = $(id); target.textContent = message; target.classList.toggle("business-error", error); target.classList.toggle("business-message", Boolean(message)); };
  async function act(button, task, errorTarget) {
    if (button?.disabled) return;
    setBusy(button, true, "Обработка…"); if (errorTarget) feedback(errorTarget);
    const form = button?.closest("form");
    let localError = form && $(".business-form-error", form);
    if (form && !localError) { localError = document.createElement("p"); localError.className = "business-form-error business-message business-error business-full"; localError.setAttribute("role", "alert"); form.append(localError); }
    if (localError) { localError.textContent = ""; localError.hidden = true; }
    try { await task(); } catch (error) { if (errorTarget) feedback(errorTarget, error.message, true); if (localError) { localError.textContent = error.message; localError.hidden = false; } toast(error.message, true); }
    finally { setBusy(button, false); }
  }
  const percent = (value) => value == null ? "—" : `${(Number(value) * 100).toFixed(1)}%`;
  const optionalText = (input) => input.value.trim() || undefined;
  const dateValue = (input) => input.value ? new Date(input.value).toISOString() : undefined;
  const today = () => { const now = new Date(); return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`; };
  async function loadCatalog() {
    loading("#business-catalog");
    try {
      [state.products, state.offers, state.suppliers] = await Promise.all([api("/api/products"), api("/api/offers"), api("/api/suppliers")]); renderCatalog();
      $("#business-suppliers").innerHTML = table(["Поставщик", "Успешные / поздние доставки", "Средняя задержка", "Брак", "Возвраты", "Рейтинг"], state.suppliers.map((item) => [h(item.name), `${item.successful_deliveries ?? "—"} / ${item.late_deliveries ?? "—"}`, item.average_delay_days == null ? "—" : `${item.average_delay_days} дн.`, percent(item.defect_rate), percent(item.return_rate), item.rating == null ? "—" : `${item.rating} / 5`]));
    } catch (error) { $("#business-catalog").innerHTML = empty(error.message); }
  }
  function renderCatalog() {
    const query = $("#catalog-search").value.trim().toLocaleLowerCase("ru"); const suppliers = new Map(state.suppliers.map((item) => [item.id, item]));
    const products = state.products.filter((item) => [item.name, item.category, item.brand, item.model, item.sku].join(" ").toLocaleLowerCase("ru").includes(query) || state.offers.some((offer) => offer.product_id === item.id && suppliers.get(offer.supplier_id)?.name.toLocaleLowerCase("ru").includes(query)));
    $("#business-catalog").innerHTML = products.length ? products.map((item) => {
      const specs = [item.brand, item.model, item.ram_gb ? `RAM ${item.ram_gb} GB` : "", item.ssd_gb ? `SSD ${item.ssd_gb} GB` : "", item.capacity_gb ? `${item.capacity_gb} GB` : "", item.interface].filter(Boolean).map(h).join(" · ");
      const offers = state.offers.filter((offer) => offer.product_id === item.id);
      return `<article class="catalog-product"><div class="business-toolbar"><div><h3>${h(item.name)}</h3><p class="business-note">${h(item.category)}${specs ? ` · ${specs}` : ""}</p></div><span class="source-badge">${h(item.data_source)}</span></div>${table(["Поставщик", "За единицу", "В наличии", "Минимум", "Доставка", "Гарантия"], offers.map((offer) => [h(suppliers.get(offer.supplier_id)?.name || `Поставщик ${offer.supplier_id}`), money(offer.unit_price, offer.currency), Number(offer.quantity_available), Number(offer.minimum_order_quantity), `${offer.delivery_days} дн.${offer.shipping_cost == null ? " · стоимость не указана" : ` · ${money(offer.shipping_cost, offer.currency)}`}`, `${offer.warranty_months} мес.`]), "Предложений по товару нет.")}</article>`;
    }).join("") : empty("По этому запросу товары не найдены.");
  }
  $("#catalog-search").addEventListener("input", renderCatalog);
  $("#refresh-catalog").addEventListener("click", (event) => act(event.currentTarget, loadCatalog));
  async function loadInventory() {
    loading("#business-inventory");
    try { const entries = await api("/api/inventory"); $("#business-inventory").innerHTML = table(["Товар", "На складе", "Резерв", "Свободно", "Точка пополнения", "Прогноз"], entries.map((item) => [h(item.product_name), Number(item.on_hand), Number(item.reserved), `<strong class="${item.available <= item.reorder_point ? "low-stock" : ""}">${Number(item.available)}</strong>`, Number(item.reorder_point), `<button class="tiny-button" data-forecast="${Number(item.product_id)}" type="button">Показать спрос</button>`])); }
    catch (error) { $("#business-inventory").innerHTML = empty(error.message); }
  }
  $("#refresh-inventory").addEventListener("click", (event) => act(event.currentTarget, loadInventory));
  $("#business-inventory").addEventListener("click", (event) => {
    const button = event.target.closest("[data-forecast]"); if (!button) return;
    act(button, async () => { const data = await api(`/api/forecast/${button.dataset.forecast}`); $("#business-forecast").textContent = data.status === "available" ? `${data.product_name}: средний спрос ${Number(data.average_monthly_demand).toFixed(1)} шт. в месяц (${data.periods_used} периодов), ${Number(data.average_daily_demand).toFixed(2)} шт. в день. Источник: demo-история потребления.` : `${data.product_name}: недостаточно истории для прогноза.`; });
  });
  $("#run-reorders").addEventListener("click", (event) => act(event.currentTarget, async () => {
    const data = await send("/api/reorders", {});
    $("#business-reorders").innerHTML = data.length ? data.map(({recommendation: rec, purchase_plan: plan}) => `<article class="business-card"><div class="business-toolbar"><h3>${h(rec.product_name)} · ${rec.recommended_quantity} шт.</h3>${status(plan.status)}</div><p>${h(rec.reason)}</p><p class="business-note">Свободно ${rec.available} шт. · спрос за срок поставки ${rec.expected_lead_time_demand} шт. · ${money(plan.merchandise_subtotal, plan.currency)}</p><button class="tiny-button" type="button" data-view-plan="${h(plan.plan_id)}">Открыть сохранённый план</button></article>`).join("") : empty("Пополнение сейчас не требуется."); toast(data.length ? `Сохранено планов пополнения: ${data.length}` : "Дефицита не найдено");
  }));
  async function loadPlans() {
    loading("#business-plans"); loading("#business-approvals");
    try {
      const [plans, approvals, orders] = await Promise.all([api("/api/procurement/plans?limit=200"), api("/api/procurement/approvals"), api("/api/procurement/orders")]);
      const ordersByPlan = new Map(orders.map((order) => [order.plan_id, order]));
      $("#business-plans").innerHTML = table(["Заявка", "Количество", "Сумма товаров", "Статус", "Действия"], plans.map((plan) => {
        const order = ordersByPlan.get(plan.plan_id);
        const draftAction = order ? `<button class="tiny-button" data-open-order="${h(order.order_id)}" type="button">Открыть заказ</button>` : plan.status === "READY_FOR_REVIEW" && !["BLOCKED", "REJECTED"].includes(plan.approval_status) ? `<button class="tiny-button" data-plan-draft="${h(plan.plan_id)}" type="button">Создать черновик</button>` : "";
        return [`<strong>${h(plan.product_query)}</strong><small>${formatDate(plan.created_at)} · ${shortId(plan.plan_id)}</small>`, `${plan.quantity_planned} / ${plan.quantity_requested}`, money(plan.merchandise_subtotal, plan.currency), `${status(plan.status)} ${status(plan.approval_status)}`, `<div class="business-actions"><button class="tiny-button" data-view-plan="${h(plan.plan_id)}" type="button">Посмотреть</button>${draftAction}</div>`];
      }), "Планов ещё нет. Создайте заявку в разделе «Закупки».");
      $("#business-approvals").innerHTML = approvals.length ? approvals.map((item) => `<article class="business-card"><div class="business-toolbar"><div><h3>План ${shortId(item.plan_id)} · ${money(item.amount, item.currency)}</h3><p class="business-note">Роль: ${h(item.required_role)} · запрошено ${formatDate(item.created_at)}</p></div>${status(item.status)}</div>${item.status === "PENDING" ? `<div class="business-actions"><button class="tiny-button" type="button" data-approval-id="${h(item.approval_id)}" data-role="${h(item.required_role)}" data-decision="approved">Согласовать в demo</button><button class="tiny-button danger" type="button" data-approval-id="${h(item.approval_id)}" data-role="${h(item.required_role)}" data-decision="rejected">Отклонить</button></div>` : `<p class="business-note">${h(item.decided_by || "")} · ${formatDate(item.decided_at)}${item.decision_comment ? ` · ${h(item.decision_comment)}` : ""}</p>`}</article>`).join("") : empty("Согласований пока нет.");
    } catch (error) { $("#business-plans").innerHTML = empty(error.message); $("#business-approvals").innerHTML = empty("Не удалось загрузить согласования."); }
  }
  $("#refresh-plans").addEventListener("click", (event) => act(event.currentTarget, loadPlans));
  $("#business-approvals").addEventListener("click", (event) => {
    const button = event.target.closest("[data-approval-id]"); if (!button) return;
    act(button, async () => {
      const sibling = button.parentElement.querySelector(`button:not([data-decision="${button.dataset.decision}"])`); if (sibling) sibling.disabled = true;
      try { await send(`/api/procurement/approvals/${encodeURIComponent(button.dataset.approvalId)}/decision`, { decision: button.dataset.decision, reviewer_id: button.dataset.role === "manager" ? "demo-manager" : "demo-finance", reviewer_role: button.dataset.role, comment: "Демо-решение из истории согласований" }); toast("Решение сохранено"); await loadPlans(); }
      finally { if (sibling) sibling.disabled = false; }
    });
  });
  document.addEventListener("click", (event) => {
    const viewButton = event.target.closest("[data-view-plan]"); if (viewButton) act(viewButton, async () => { const [plan, orders] = await Promise.all([api(`/api/procurement/plans/${encodeURIComponent(viewButton.dataset.viewPlan)}`), api("/api/procurement/orders?limit=500")]); renderPlan(plan, orders.find((order) => order.plan_id === plan.plan_id) || null); openView("procurement"); });
    const draftButton = event.target.closest("[data-plan-draft]"); if (draftButton) act(draftButton, async () => { const order = await send(`/api/procurement/plans/${encodeURIComponent(draftButton.dataset.planDraft)}/order`, { buyer_note: "Локальный черновик из истории планов" }); toast("Черновик сохранён"); openOrder(order.order_id); });
    const orderButton = event.target.closest("[data-open-order]"); if (orderButton) openOrder(orderButton.dataset.openOrder);
  });
  async function loadOrders(preferredId) {
    const version = ++state.ordersVersion;
    try {
      const select = $("#business-order-select"); const selected = preferredId || select.value;
      const orders = await api("/api/procurement/orders?limit=500");
      if (version !== state.ordersVersion) return;
      state.orders = orders;
      select.innerHTML = `<option value="">Выберите заказ</option>${state.orders.map((order) => `<option value="${h(order.order_id)}">${shortId(order.order_id)} · ${h(labels[order.status] || order.status)} · ${order.item_count} строк · ${formatDate(order.created_at)}</option>`).join("")}`;
      if (state.orders.some((order) => order.order_id === selected)) { select.value = selected; await loadOrder(selected); }
      else if (!state.orders.length) $("#business-order-detail").innerHTML = empty("Заказов пока нет. Создайте черновик из плана закупки.");
    } catch (error) { feedback("#business-order-feedback", error.message, true); }
  }
  function openOrder(id) { state.preferredOrder = id; openView("orders"); }
  window.Procureline.openOrder = openOrder;
  $("#refresh-orders").addEventListener("click", (event) => act(event.currentTarget, () => loadOrders(), "#business-order-feedback"));
  $("#business-order-select").addEventListener("change", (event) => {
    if (event.target.value) loadOrder(event.target.value);
    else { state.orderVersion += 1; state.order = null; $("#business-order-detail").innerHTML = empty("Выберите заказ для просмотра."); }
  });
  async function loadOrder(id) {
    const version = ++state.orderVersion; loading("#business-order-detail"); feedback("#business-order-feedback");
    try {
      const base = `/api/procurement/orders/${encodeURIComponent(id)}`;
      const [order, events, receipts, invoices] = await Promise.all([api(base), api(`${base}/delivery-events`), api(`${base}/receipts`), api(`${base}/invoices`)]);
      const plan = await api(`/api/procurement/plans/${encodeURIComponent(order.plan_id)}`);
      if (version !== state.orderVersion) return;
      Object.assign(state, { order, events, receipts, invoices, currency: plan.currency }); renderOrder();
    } catch (error) { if (version === state.orderVersion) { $("#business-order-detail").innerHTML = empty(error.message); feedback("#business-order-feedback", error.message, true); } }
  }
  const supplierOptions = () => [...new Map(state.order.items.map((item) => [item.supplier_id, item.supplier_name || `Поставщик ${item.supplier_id}`]))].map(([id, name]) => `<option value="${id}">${h(name)}</option>`).join("");
  const latestEvents = () => new Map(state.events.map((event) => [event.supplier_id, event]));
  const remaining = (item) => item.quantity - state.receipts.filter((rec) => rec.order_item_id === item.id).reduce((sum, rec) => sum + rec.received_quantity, 0);
  function renderOrder() {
    const order = state.order; const latest = latestEvents();
    const canDeliver = !["PENDING_APPROVAL", "CANCELLED", "RECEIVED"].includes(order.status);
    const eligibleItems = order.items.filter((item) => latest.get(item.supplier_id)?.status === "DELIVERED" && remaining(item) > 0 && ["ORDERED", "SHIPPED", "DELAYED", "DELIVERED", "RECEIVED"].includes(order.status));
    const failedSuppliers = [...latest.values()].filter((event) => ["DELAYED", "CANCELLED"].includes(event.status));
    $("#business-order-detail").innerHTML = `
      <section class="panel business-panel"><div class="business-toolbar"><div><h2>Заказ ${shortId(order.order_id)}</h2><p class="business-note">${formatDate(order.created_at)} · ${h(order.order_id)}</p></div>${status(order.status)}</div>${order.buyer_note ? `<p>${h(order.buyer_note)}</p>` : ""}${table(["Товар", "Поставщик", "Количество", "Цена", "Товарная сумма", "Осталось принять"], order.items.map((item) => [h(item.product_name), h(item.supplier_name), item.quantity, money(item.unit_price, state.currency), money(item.merchandise_subtotal, state.currency), remaining(item)]))}<p class="business-note">LOCAL DRAFT · внешний заказ не создан · валюта ${h(state.currency)}</p></section>
      <section class="panel business-panel"><h2>Поставка</h2><p class="business-note">Запишите известный факт. Первое событие — «Заказ подтверждён вручную»; оно не отправляет заказ поставщику.</p>${canDeliver ? `<form id="business-delivery-form" class="business-form"><label class="field"><span>Поставщик</span><select id="delivery-supplier">${supplierOptions()}</select></label><label class="field"><span>Событие</span><select id="delivery-status"></select></label><label class="field"><span>Ожидаемая дата · местное время</span><input id="delivery-expected" type="datetime-local"></label><label class="field"><span>Фактическая дата · местное время</span><input id="delivery-actual" type="datetime-local"></label><label class="field"><span>Трек-номер</span><input id="delivery-tracking" maxlength="200"></label><label class="field"><span>Причина / примечание</span><input id="delivery-note" maxlength="1000"></label><button class="primary-button" type="submit">Сохранить факт поставки</button></form>` : `<p class="business-note">Для статуса «${h(labels[order.status])}» изменение поставки недоступно.</p>`}${failedSuppliers.length ? `<div class="business-callout"><p>Есть задержка или отмена. Можно сохранить альтернативный план для количества этих поставщиков.</p><button id="business-replan" class="secondary-button" type="button">Найти замену поставщику</button></div>` : ""}<details class="business-details"><summary>История поставки (${state.events.length})</summary>${table(["Когда", "Поставщик", "Статус", "Ожидание / факт", "Примечание"], state.events.map((event) => [formatDate(event.created_at), h(order.items.find((item) => item.supplier_id === event.supplier_id)?.supplier_name || event.supplier_id), status(event.status), `${event.expected_at ? formatDate(event.expected_at) : "—"} / ${event.actual_at ? formatDate(event.actual_at) : "—"}`, h([event.tracking_number, event.note].filter(Boolean).join(" · "))]))}</details></section>
      <section class="panel business-panel"><h2>Приёмка</h2><p class="business-note">Принятый товар пополнит склад. Повреждённое количество учитывается отдельно. Поля с нулём пропускаются.</p>${eligibleItems.length ? `<form id="business-receipt-form"><div class="receipt-grid">${eligibleItems.map((item) => `<div class="business-card receipt-line" data-receipt-item="${item.id}"><h3>${h(item.product_name)} · ${h(item.supplier_name)}</h3><p class="business-note">Осталось ${remaining(item)} шт.</p><div class="field-row"><label class="field"><span>Получено всего</span><input data-received type="number" min="0" max="${remaining(item)}" step="1" value="0" required></label><label class="field"><span>Из них повреждено</span><input data-damaged type="number" min="0" max="${remaining(item)}" step="1" value="0" required></label></div></div>`).join("")}</div><label class="field business-full"><span>Примечание к приёмке</span><input id="receipt-note" maxlength="1000"></label><button class="primary-button" type="submit">Сохранить приёмку</button></form>` : empty("Для приёмки нужны неполученные строки поставщика со статусом «Доставлен».")}<details class="business-details"><summary>История приёмки (${state.receipts.length})</summary>${table(["Товар", "Дата", "Получено", "Повреждено", "Принято"], state.receipts.map((rec) => [h(order.items.find((item) => item.id === rec.order_item_id)?.product_name || rec.product_id), formatDate(rec.received_at), rec.received_quantity, rec.damaged_quantity, rec.accepted_quantity]))}</details></section>
      <section class="panel business-panel"><h2>Внести данные счёта</h2><p class="business-note">Ручной ввод из документа для сверки с заказом и приёмкой. Оплата не выполняется.</p><form id="business-invoice-form"><div class="business-form"><label class="field"><span>Поставщик</span><select id="invoice-supplier">${supplierOptions()}</select></label><label class="field"><span>Номер счёта</span><input id="invoice-number" maxlength="100" required></label><label class="field"><span>Дата счёта</span><input id="invoice-date" type="date" value="${today()}" required></label><label class="field"><span>Валюта</span><input id="invoice-currency" minlength="3" maxlength="3" value="${h(state.currency)}" required></label></div><div id="invoice-items"></div><p class="business-note">Количество 0 исключит строку из счёта. Введите суммы из документа.</p><div class="business-form"><label class="field"><span>Товарная сумма</span><input id="invoice-subtotal" type="number" min="0" step="0.01" required></label><label class="field"><span>Налоги</span><input id="invoice-tax" type="number" min="0" step="0.01" value="0" required></label><label class="field"><span>Доставка</span><input id="invoice-shipping" type="number" min="0" step="0.01" value="0" required></label><label class="field"><span>Итого в документе</span><input id="invoice-total" type="number" min="0" step="0.01" required></label><label class="field business-full"><span>Примечание</span><input id="invoice-note" maxlength="1000"></label></div><div class="business-actions"><button id="invoice-calculate" class="secondary-button" type="button">Заполнить суммы по строкам</button><button class="primary-button" type="submit">Сохранить и сверить счёт</button></div></form></section>
      <section class="panel business-panel"><h2>Счета и результаты сверки</h2><div id="business-invoices">${renderInvoices()}</div></section>`;
    if (canDeliver) { updateDeliveryStatuses(); $("#delivery-supplier").addEventListener("change", updateDeliveryStatuses); $("#delivery-status").addEventListener("change", updateDeliveryNote); $("#business-delivery-form").addEventListener("submit", submitDelivery); }
    $("#business-receipt-form")?.addEventListener("submit", submitReceipt);
    $("#invoice-supplier").addEventListener("change", renderInvoiceLines); $("#invoice-calculate").addEventListener("click", calculateInvoice); $("#business-invoice-form").addEventListener("submit", submitInvoice); renderInvoiceLines();
    $("#business-replan")?.addEventListener("click", (event) => act(event.currentTarget, async () => { const result = await send(`/api/procurement/orders/${encodeURIComponent(order.order_id)}/replan`, {}); renderPlan(result.replacement_plan); openView("procurement"); toast(`План замены сохранён для ${result.replaced_quantity} шт.`); }, "#business-order-feedback"));
  }
  function updateDeliveryStatuses() {
    const current = latestEvents().get(Number($("#delivery-supplier").value))?.status;
    const allowed = { ORDERED: ["SHIPPED", "DELAYED", "DELIVERED", "CANCELLED", "ORDERED"], SHIPPED: ["DELIVERED", "DELAYED", "CANCELLED", "SHIPPED"], DELAYED: ["SHIPPED", "DELIVERED", "CANCELLED", "DELAYED"], DELIVERED: ["DELIVERED"], CANCELLED: ["CANCELLED"] }[current] || ["ORDERED"];
    $("#delivery-status").innerHTML = allowed.map((value) => `<option value="${value}">${h(labels[value])}</option>`).join(""); updateDeliveryNote();
  }
  function updateDeliveryNote() { $("#delivery-note").required = ["DELAYED", "CANCELLED"].includes($("#delivery-status").value); }
  function submitDelivery(event) {
    event.preventDefault(); const form = event.currentTarget; const orderId = state.order.order_id;
    act($("button[type=submit]", form), async () => {
      const note = optionalText($("#delivery-note"));
      if (["DELAYED", "CANCELLED"].includes($("#delivery-status").value) && !note) throw new Error("Укажите причину задержки или отмены.");
      const body = { supplier_id: Number($("#delivery-supplier").value), status: $("#delivery-status").value, expected_at: dateValue($("#delivery-expected")), actual_at: dateValue($("#delivery-actual")), tracking_number: optionalText($("#delivery-tracking")), note };
      await send(`/api/procurement/orders/${encodeURIComponent(orderId)}/delivery-events`, body); toast("Ручное событие поставки сохранено"); if ($("#business-order-select").value === orderId) await loadOrders(orderId);
    }, "#business-order-feedback");
  }
  function submitReceipt(event) {
    event.preventDefault(); const form = event.currentTarget; const orderId = state.order.order_id;
    act($("button[type=submit]", form), async () => {
      const items = $$("[data-receipt-item]", form).map((row) => ({ order_item_id: Number(row.dataset.receiptItem), quantity_received: Number($("[data-received]", row).value), damaged_quantity: Number($("[data-damaged]", row).value) }));
      if (items.some((item) => item.damaged_quantity > item.quantity_received)) throw new Error("Повреждённое количество не может превышать полученное.");
      const selected = items.filter((item) => item.quantity_received > 0); if (!selected.length) throw new Error("Укажите полученное количество хотя бы в одной строке.");
      await send(`/api/procurement/orders/${encodeURIComponent(orderId)}/receipts`, { items: selected, note: optionalText($("#receipt-note")) }); toast("Приёмка сохранена, склад обновлён"); if ($("#business-order-select").value === orderId) await loadOrders(orderId);
    }, "#business-order-feedback");
  }
  function renderInvoiceLines() {
    const supplierId = Number($("#invoice-supplier").value); const items = state.order.items.filter((item) => item.supplier_id === supplierId);
    $("#invoice-items").innerHTML = items.map((item) => `<div class="business-card invoice-line" data-invoice-item="${item.id}"><h3>${h(item.product_name)}</h3><div class="field-row"><label class="field"><span>Количество в счёте</span><input data-invoice-quantity type="number" min="0" step="1" value="${item.quantity}" required></label><label class="field"><span>Цена за единицу</span><input data-invoice-price type="number" min="0.01" step="0.01" value="${h(item.unit_price)}" required></label></div></div>`).join(""); calculateInvoice();
  }
  function invoiceItems() { return $$("[data-invoice-item]").map((row) => ({ order_item_id: Number(row.dataset.invoiceItem), quantity: Number($("[data-invoice-quantity]", row).value), unit_price: $("[data-invoice-price]", row).value })).filter((item) => item.quantity > 0); }
  function calculateInvoice() { const subtotal = invoiceItems().reduce((sum, item) => sum + item.quantity * Number(item.unit_price), 0); $("#invoice-subtotal").value = subtotal.toFixed(2); $("#invoice-total").value = (subtotal + Number($("#invoice-tax").value) + Number($("#invoice-shipping").value)).toFixed(2); }
  function submitInvoice(event) {
    event.preventDefault(); const form = event.currentTarget; const orderId = state.order.order_id;
    act($("button[type=submit]", form), async () => {
      const items = invoiceItems(); if (!items.length) throw new Error("Укажите хотя бы одну строку счёта с ненулевым количеством.");
      const number = $("#invoice-number").value.trim(); if (!number) throw new Error("Укажите номер счёта.");
      await send(`/api/procurement/orders/${encodeURIComponent(orderId)}/invoices`, { supplier_id: Number($("#invoice-supplier").value), invoice_number: number, invoice_date: $("#invoice-date").value, currency: $("#invoice-currency").value.trim().toUpperCase(), subtotal: $("#invoice-subtotal").value, tax_amount: $("#invoice-tax").value, shipping_amount: $("#invoice-shipping").value, total_amount: $("#invoice-total").value, items, note: optionalText($("#invoice-note")) });
      toast("Счёт сохранён и сверен, оплата не выполнялась"); if ($("#business-order-select").value === orderId) await loadOrders(orderId);
    }, "#business-order-feedback");
  }
  function renderInvoices() {
    return state.invoices.length ? state.invoices.map((invoice) => `<article class="business-card"><div class="business-toolbar"><div><h3>Счёт ${h(invoice.invoice_number)} · ${h(invoice.supplier_name)}</h3><p class="business-note">${h(invoice.invoice_date)} · ${money(invoice.total_amount, invoice.currency)} · Не оплачен</p></div>${status(invoice.status)}</div><p class="business-note">Товары ${money(invoice.subtotal, invoice.currency)} · налог ${money(invoice.tax_amount, invoice.currency)} · доставка ${money(invoice.shipping_amount, invoice.currency)}</p>${invoice.findings.length ? `<ul class="business-findings">${invoice.findings.map((finding) => `<li>${h(finding.message)}</li>`).join("")}</ul>` : '<p>Расхождений не найдено.</p>'}<button class="tiny-button" data-review-invoice="${h(invoice.invoice_id)}" type="button">Повторить сверку с приёмкой</button></article>`).join("") : empty("Счетов по заказу ещё нет.");
  }
  $("#business-order-detail").addEventListener("click", (event) => {
    const button = event.target.closest("[data-review-invoice]"); if (!button) return; const orderId = state.order.order_id;
    act(button, async () => { await send(`/api/procurement/invoices/${encodeURIComponent(button.dataset.reviewInvoice)}/review`, {}); toast("Сверка обновлена"); if ($("#business-order-select").value === orderId) await loadOrders(orderId); }, "#business-order-feedback");
  });
  const auditLabels = { procurement_plan_created: "Создан план закупки", local_order_draft_created: "Создан локальный заказ", approval_requested: "Запрошено согласование", approval_approved: "План согласован", approval_rejected: "План отклонён", delivery_status_recorded: "Записан статус поставки", goods_received: "Записана приёмка", purchase_invoice_recorded: "Внесён счёт", purchase_invoice_reconciled: "Повторно сверен счёт", reorder_analysis_completed: "Завершён анализ пополнения", reorder_recommendation_created: "Создана рекомендация пополнения", reorder_analysis_no_action: "Пополнение не потребовалось", wishlist_item_added: "Товар добавлен в список желаний", wishlist_item_removed: "Товар удалён из списка желаний", price_watch_created: "Создан мониторинг цены", price_watch_status_changed: "Изменён статус мониторинга", price_watch_alert_created: "Зафиксировано событие цены", purchase_reminder_created: "Создано напоминание", purchase_reminder_completed: "Выполнено напоминание", purchase_reminder_cancelled: "Отменено напоминание", personal_preferences_saved: "Сохранены предпочтения", personal_purchase_recorded: "Записана личная покупка", personal_return_drafted: "Создан черновик возврата", personal_return_cancelled: "Отменён черновик возврата", demo_catalog_additions_imported: "Обновлён demo-каталог" };
  const entityLabels = { procurement_plan: "План", purchase_order: "Заказ", approval: "Согласование", purchase_invoice: "Счёт", reorder_analysis: "Анализ пополнения", reorder_recommendation: "Рекомендация", wishlist_item: "Список желаний", price_watch: "Мониторинг цены", price_watch_event: "Событие цены", purchase_reminder: "Напоминание", personal_preferences: "Предпочтения", personal_purchase: "Личная покупка", personal_return: "Возврат", catalog: "Каталог" };
  function renderOverview(data) {
    if (data.error) return empty(`Операционный обзор недоступен: ${data.error}`);
    const metrics = [[data.active_order_count, "активных заказов"], [data.pending_approval_count, "ожидают согласования"], [data.low_stock_count, "товаров с низким остатком"], [data.stockout_count, "товаров без остатка"], [data.delayed_shipment_count, "задержанных поставок"], [data.delayed_supplier_count, "поставщиков с задержкой"], [data.reorder_analysis_count, "расчётов пополнения"], [percent(data.damage_fraction), "повреждений при приёмке"]];
    return `<h3>Состояние закупок</h3><div class="business-metrics">${metrics.map(([value, label]) => `<div><strong>${h(value)}</strong><span>${h(label)}</span></div>`).join("")}</div><h3>Средняя товарная сумма заказа</h3>${table(["Валюта", "Заказов без отменённых", "Товарная сумма", "Средний заказ"], data.currency_merchandise_totals.map((row) => [h(row.currency), row.order_count, money(row.order_merchandise_total, row.currency), money(row.average_order_merchandise_value, row.currency)]))}<details class="business-details"><summary>Метод расчёта и недостающие данные</summary><p class="business-note">Обновлено ${formatDate(data.generated_at)} · ${h(data.source_label)}</p><ul class="business-findings"><li>Экономия: неизвестна. ${h(data.savings.reason)}</li><li>Фактический срок доставки: неизвестен. ${h(data.average_actual_delivery_days.reason)}</li><li>Надёжность поставщиков: неизвестна. ${h(data.supplier_reliability.reason)}</li>${data.calculation_notes.map((note) => `<li>${h(note)}</li>`).join("")}</ul></details><hr class="business-divider">`;
  }
  async function loadAnalytics() {
    loading("#business-finance"); loading("#business-audit");
    try {
      const [data, audit, overview] = await Promise.all([api("/api/procurement/analytics/finance"), api("/api/audit-log?limit=100"), api("/api/procurement/analytics/overview").catch((error) => ({ error: error.message }))]);
      $("#business-finance").innerHTML = `${renderOverview(overview)}<h3>Счета и приёмка</h3><div class="business-metrics"><div><strong>${data.order_count}</strong><span>локальных заказов</span></div><div><strong>${data.invoice_count}</strong><span>ручных счетов</span></div><div><strong>${data.received_unit_count}</strong><span>единиц получено</span></div><div><strong>${data.accepted_unit_count}</strong><span>единиц принято</span></div></div><h3>Суммы по валютам</h3>${table(["Валюта", "Товарная сумма заказов", "Счета, всего", "Сверены", "Расхождения", "Ожидают приёмку"], data.currency_totals.map((row) => [h(row.currency), money(row.ordered_subtotal, row.currency), money(row.invoiced_total, row.currency), money(row.matched_invoice_total, row.currency), money(row.variance_invoice_total, row.currency), money(row.pending_invoice_total, row.currency)]))}<h3>По поставщикам</h3>${table(["Поставщик", "Валюта", "Товарная сумма заказов", "Счета"], data.supplier_totals.map((row) => [h(row.supplier_name), h(row.currency), money(row.ordered_subtotal, row.currency), money(row.invoiced_total, row.currency)]))}<p class="business-note">Разные валюты не складываются. Суммы заказов не включают неизвестные налоги и доставку; суммы счетов отражают ручной ввод.</p>`;
      $("#business-audit").innerHTML = table(["Время", "Действие", "Участник", "Объект"], audit.map((item) => [formatDate(item.occurred_at), h(auditLabels[item.action] || item.action), h(item.actor), `${h(entityLabels[item.entity_type] || item.entity_type)} · ${shortId(item.entity_id)}`]));
    } catch (error) { $("#business-finance").innerHTML = empty(error.message); $("#business-audit").innerHTML = empty("Журнал не загружен."); }
  }
  $("#refresh-analytics").addEventListener("click", (event) => act(event.currentTarget, loadAnalytics));
  document.addEventListener("procureline:view", (event) => {
    const loaders = { catalog: loadCatalog, inventory: loadInventory, plans: loadPlans, analytics: loadAnalytics, orders: () => { const id = state.preferredOrder; state.preferredOrder = undefined; return loadOrders(id); } }; loaders[event.detail.view]?.();
  });
})();
