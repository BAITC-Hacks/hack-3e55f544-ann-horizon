(() => {
  "use strict";
  const { api, send, money, escapeHtml: esc, formatDate, toast, setBusy, userId, openView, renderPlan } = window.Procureline;
  const $ = (id) => document.getElementById(id);
  const scope = `user_id=${encodeURIComponent(userId)}`;
  const state = { loaded: false, products: [], purchases: [], preferenceRequest: 0, purchaseRequest: 0, preference: null };
  const value = (id) => $(id).value.trim();
  const list = (id) => value(id).split(",").map((entry) => entry.trim()).filter(Boolean);
  const optionalNumber = (id) => value(id) ? Number(value(id)) : null;
  const optionalDecimal = (id) => value(id) || null;
  const localDateTime = () => {
    const date = new Date();
    return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  };
  const localTimestamp = (input) => {
    const date = new Date(input);
    if (Number.isNaN(date.getTime())) throw new Error("Укажите дату и время покупки.");
    const offset = -date.getTimezoneOffset();
    const sign = offset >= 0 ? "+" : "-";
    const hours = String(Math.floor(Math.abs(offset) / 60)).padStart(2, "0");
    const minutes = String(Math.abs(offset) % 60).padStart(2, "0");
    return `${input.length === 16 ? `${input}:00` : input}${sign}${hours}:${minutes}`;
  };
  const verdicts = { COMPATIBLE: "Проверенные условия соблюдены", INCOMPATIBLE: "Обнаружена несовместимость", UNKNOWN: "Недостаточно данных", NOT_APPLICABLE: "Набор самостоятельных товаров", READY_FOR_REVIEW: "Комплект рассчитан", REVIEW_REQUIRED: "Нужна проверка", BLOCKED: "Комплект не проходит ограничения" };
  const empty = (id, text) => { $(id).innerHTML = `<p class="empty-list">${esc(text)}</p>`; };
  const record = (title, body) => `<article class="personal-record"><h3>${esc(title)}</h3>${body}</article>`;

  function formHandler(id, handler) {
    $(id).addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      if (form.dataset.busy) return;
      const button = form.querySelector('button[type="submit"]');
      const error = form.querySelector(".form-error");
      error.hidden = true;
      form.dataset.busy = "true";
      setBusy(button, true);
      try { await handler(); }
      catch (exception) { error.textContent = exception.message; error.hidden = false; toast(exception.message, true); }
      finally { delete form.dataset.busy; setBusy(button, false); }
    });
  }

  async function loadCatalog() {
    if (state.loaded) return;
    const [products, suppliers] = await Promise.all([api("/api/products"), api("/api/suppliers")]);
    state.products = products;
    for (const id of ["history-product", "bundle-product-1", "bundle-product-2", "bundle-product-3", "bundle-host", "compatibility-product", "compatibility-host"]) {
      const select = $(id);
      const first = select.options[0].outerHTML;
      select.innerHTML = first + products.map((product) => `<option value="${product.id}">${esc(product.name)}</option>`).join("");
    }
    $("preference-suppliers").innerHTML = suppliers.map((supplier) => `<option value="${supplier.id}">${esc(supplier.name)}</option>`).join("");
    state.loaded = true;
  }

  async function loadPreferences() {
    const generation = ++state.preferenceRequest;
    const preference = await api(`/api/personal/preferences?${scope}`);
    if (generation !== state.preferenceRequest) return;
    state.preference = preference;
    $("preference-brands").value = preference.preferred_brands.join(", ");
    $("preference-categories").value = preference.favorite_categories.join(", ");
    for (const option of $("preference-suppliers").options) option.selected = preference.preferred_supplier_ids.includes(Number(option.value));
    $("preference-min").value = preference.budget_min ?? "";
    $("preference-max").value = preference.budget_max ?? "";
    $("preference-note").value = preference.note;
  }

  async function loadPurchases() {
    const generation = ++state.purchaseRequest;
    const [purchases, reorders, returns] = await Promise.all([
      api(`/api/personal/purchases?${scope}`),
      api(`/api/personal/reorder-recommendations?${scope}`),
      api(`/api/personal/returns?${scope}`),
    ]);
    if (generation !== state.purchaseRequest) return;
    state.purchases = purchases;
    $("purchase-history-list").innerHTML = purchases.map((purchase) => record(purchase.product_name,
      `<p>${esc(formatDate(purchase.purchased_at))} · ${purchase.quantity} шт. × ${money(purchase.unit_price, purchase.currency)}</p><p><strong>${money(purchase.total_price, purchase.currency)}</strong>${purchase.repeat_after_days ? ` · повтор через ${purchase.repeat_after_days} дн.` : ""}</p>${purchase.note ? `<p>${esc(purchase.note)}</p>` : ""}<p>Записано вручную</p>`)).join("");
    if (!purchases.length) empty("purchase-history-list", "Покупок пока нет. Сохраните первую запись.");
    const previous = $("return-purchase").value;
    $("return-purchase").innerHTML = '<option value="">Выберите покупку</option>' + purchases.map((purchase) => `<option value="${esc(purchase.purchase_id)}">${esc(purchase.product_name)} · ${purchase.quantity} шт. · ${esc(formatDate(purchase.purchased_at))}</option>`).join("");
    if (purchases.some((purchase) => purchase.purchase_id === previous)) $("return-purchase").value = previous;
    $("personal-reorders").innerHTML = reorders.map((item) => record(item.product_name,
      `<p><strong>${item.status === "DUE" ? "Пора повторить" : "Запланировано"}</strong> · ${esc(formatDate(item.due_at))}</p><p>${esc(item.explanation)}</p><p>${item.quantity} шт. · ${item.estimated_subtotal === null ? "Нет доступного предложения" : money(item.estimated_subtotal, item.currency)}</p><button type="button" class="secondary-button" data-personal-plan="${item.product_id}" data-quantity="${item.quantity}">Подготовить план покупки</button>`)).join("");
    if (!reorders.length) empty("personal-reorders", "Укажите интервал повторения при записи покупки.");
    $("return-list").innerHTML = returns.map((item) => record(item.product_name,
      `<p>${item.quantity} шт. · ${item.status === "CANCELLED" ? "Отменён" : "Черновик"}</p><p>${esc(item.reason)}</p><p>${esc(item.explanation)}</p>${item.documents.length ? `<p>Документы: ${item.documents.map(esc).join(", ")}</p>` : ""}${item.status === "DRAFT" ? `<button type="button" class="secondary-button" data-cancel-return="${esc(item.return_id)}">Отменить черновик</button>` : ""}`)).join("");
    if (!returns.length) empty("return-list", "Черновиков возврата пока нет.");
  }

  formHandler("purchase-history-form", async () => {
    await send("/api/personal/purchases", { user_id: userId, product_id: Number(value("history-product")), quantity: Number(value("history-quantity")), unit_price: value("history-price"), currency: "KZT", purchased_at: localTimestamp(value("history-date")), repeat_after_days: optionalNumber("history-repeat"), note: value("history-note") });
    await loadPurchases();
    toast("Покупка добавлена в историю");
  });

  formHandler("preferences-form", async () => {
    state.preference = await send(`/api/personal/preferences?${scope}`, {
      preferred_brands: list("preference-brands"), favorite_categories: list("preference-categories"),
      preferred_supplier_ids: [...$("preference-suppliers").selectedOptions].map((option) => Number(option.value)),
      budget_min: optionalDecimal("preference-min"), budget_max: optionalDecimal("preference-max"), currency: "KZT", note: value("preference-note"),
    }, "PUT");
    toast("Предпочтения сохранены");
  });

  formHandler("return-form", async () => {
    if (!value("return-reason")) throw new Error("Укажите причину возврата.");
    await send("/api/personal/returns", { user_id: userId, purchase_id: value("return-purchase"), quantity: Number(value("return-quantity")), reason: value("return-reason"), return_deadline: value("return-deadline") || null, policy_source: value("return-policy") || null, documents: list("return-documents") });
    await loadPurchases();
    toast("Черновик возврата сохранён");
  });

  formHandler("bundle-form", async () => {
    const items = [1, 2, 3].map((index) => optionalNumber(`bundle-product-${index}`)).filter(Boolean).map((product_id) => ({ product_id, quantity: 1 }));
    const result = await send("/api/personal/bundles", { user_id: userId, items, budget_total: value("bundle-budget"), currency: "KZT", host_product_id: optionalNumber("bundle-host") });
    $("bundle-result").innerHTML = `<h3>${esc(verdicts[result.outcome])}</h3><p class="personal-total">${money(result.merchandise_subtotal, result.currency)}</p><p class="helper-text">Товарная сумма; доставка и налоги не включены.</p><p>${esc(verdicts[result.compatibility_verdict])}</p>${result.lines.map((line) => record(line.product_name, `<p>${esc(line.supplier_name)} · ${line.quantity} шт. · ${money(line.subtotal, result.currency)}</p>${line.compatibility ? `<p>${esc(verdicts[line.compatibility.verdict])}</p>` : ""}`)).join("")}<ul>${result.findings.map((finding) => `<li>${esc(finding)}</li>`).join("")}</ul>`;
    toast("Подбор комплекта завершён");
  });

  formHandler("compatibility-form", async () => {
    const result = await send("/api/personal/compatibility", {
      product_id: Number(value("compatibility-product")), host_product_id: optionalNumber("compatibility-host"),
      component_specs: { interface: value("component-interface") || null, form_factor: value("component-form") || null, length_mm: optionalDecimal("component-length"), required_power_w: optionalDecimal("component-power") },
      host_specs: { accepted_interfaces: list("host-interfaces").length ? list("host-interfaces") : null, accepted_form_factors: list("host-forms").length ? list("host-forms") : null, maximum_length_mm: optionalDecimal("host-length"), available_power_w: optionalDecimal("host-power") },
    });
    const checkNames = { interface: "Интерфейс", form_factor: "Форм-фактор", dimensions: "Размеры", power: "Мощность", socket: "Сокет" };
    const checkLabels = { PASS: "Совпадает", FAIL: "Конфликт", UNKNOWN: "Нет данных" };
    $("compatibility-result").innerHTML = `<h3>${esc(verdicts[result.verdict])}</h3>${result.findings.map((finding) => `<div class="check-result"><strong class="check-${finding.status.toLowerCase()}">${esc(checkLabels[finding.status])}</strong><span><b>${esc(checkNames[finding.check])}</b> · ${esc(finding.explanation)}</span></div>`).join("")}<p class="helper-text">${esc(result.scope_note)}</p>`;
    toast("Проверка характеристик завершена");
  });

  $("return-list").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-cancel-return]");
    if (!button || button.disabled) return;
    setBusy(button, true);
    try { await send(`/api/personal/returns/${encodeURIComponent(button.dataset.cancelReturn)}/cancel?${scope}`, {}); await loadPurchases(); toast("Черновик отменён"); }
    catch (error) { toast(error.message, true); }
    finally { if (button.isConnected) setBusy(button, false); }
  });
  $("personal-reorders").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-personal-plan]");
    if (!button || button.disabled) return;
    const product = state.products.find((item) => item.id === Number(button.dataset.personalPlan));
    if (!product) return;
    setBusy(button, true);
    try {
      const sourceText = `Нужно купить ${button.dataset.quantity} шт. ${product.name}`;
      const plan = await send("/api/procurement/requests", {
        product_query: product.name, quantity: Number(button.dataset.quantity), currency: "KZT",
        required_specs: product.sku ? { sku: product.sku } : { id: String(product.id) },
        user_context: { user_id: userId, user_type: "personal", organization_id: null, currency: "KZT" },
        source_text: sourceText,
      });
      $("purchase-user-type").value = "personal";
      $("purchase-message").value = sourceText;
      renderPlan(plan);
      openView("procurement");
      toast("План повторной покупки сохранён для выбранного товара");
    } catch (error) { toast(error.message, true); }
    finally { setBusy(button, false); }
  });
  $("refresh-purchases").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    setBusy(button, true);
    try { await loadPurchases(); } catch (error) { toast(error.message, true); } finally { setBusy(button, false); }
  });
  document.addEventListener("procureline:view", async (event) => {
    if (!["purchases", "bundles"].includes(event.detail.view)) return;
    try {
      await loadCatalog();
      if (event.detail.view === "purchases") {
        await Promise.all([loadPurchases(), loadPreferences()]);
      } else if (!$("bundle-budget").dataset.edited) {
        state.preference = await api(`/api/personal/preferences?${scope}`);
        if (state.preference.currency === "KZT" && state.preference.budget_max !== null) $("bundle-budget").value = state.preference.budget_max;
      }
    } catch (error) { toast(error.message, true); }
  });
  $("bundle-budget").addEventListener("input", () => { $("bundle-budget").dataset.edited = "true"; });
  $("history-date").value = localDateTime();
})();
