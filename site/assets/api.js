/* Точка привязки сайта к бэкенду CourtDraft AI.
 *
 * СЕЙЧАС: сайт полностью статичен и ни от чего не зависит.
 * Разметка не загружает данные с сервера — это сделано намеренно,
 * чтобы страница работала офлайн и на GitHub Pages без бэкенда.
 *
 * БЭКЕНД ПОДКЛЮЧАЕТСЯ ЗДЕСЬ. Ниже — готовый слой: когда появится
 * интерфейс (Фаза 10), достаточно раскомментировать блок
 * `bindBackend()` и указать адрес API в `CONFIG.apiBaseUrl`.
 *
 * Ожидаемые эндпоинты (уже реализованы в бэкенде):
 *   GET /api/health  -> { status, version, environment, components[] }
 *   GET /api/info    -> { name, version, environment, llm_provider, ... }
 *   GET /api/cases   -> { items: [], total }
 *   POST /api/cases  -> создание дела
 *   POST /api/cases/{id}/documents -> регистрация документа
 */

(function () {
  "use strict";

  var CONFIG = {
    // Пусто = сервер не опрашивается, индикатор скрыт.
    // Пример для локальной машины: "http://localhost:8000"
    // Пример для GitHub Pages: "https://<user>.github.io/courtdraft-ai-api"
    apiBaseUrl: "",

    timeoutMs: 2500,
    // Один лишний запрос на каждую загрузку страницы. Чаще нет смысла:
    // состояние сервера меняется медленно.
    showIndicator: false
  };

  var state = { online: null };

  /**
   * Запрос к бэкенду с таймаутом.
   * Ошибка не должна ломать страницу: сайт работает и без сервера.
   */
  function apiGet(path) {
    if (!CONFIG.apiBaseUrl) {
      return Promise.reject(new Error("apiBaseUrl не задан"));
    }
    var url = CONFIG.apiBaseUrl.replace(/\/$/, "") + path;
    var controller =
      typeof AbortController !== "undefined" ? new AbortController() : null;
    var timer = controller
      ? setTimeout(function () { controller.abort(); }, CONFIG.timeoutMs)
      : null;

    return fetch(url, controller ? { signal: controller.signal } : undefined)
      .then(function (response) {
        if (timer) { clearTimeout(timer); }
        if (!response.ok) {
          throw new Error("HTTP " + response.status);
        }
        return response.json();
      });
  }

  function setIndicator(online) {
    if (!CONFIG.showIndicator) { return; }
    var el = document.querySelector(".backend-status");
    if (!el) { return; }
    el.hidden = false;
    var dot = el.querySelector(".backend-dot");
    var label = el.querySelector(".backend-label");
    if (dot) { dot.classList.add(online ? "is-online" : "is-offline"); }
    if (label) { label.textContent = online ? "бэкенд доступен" : "бэкенд недоступен"; }
  }

  function renderHealth(health) {
    // Здесь появится вывод компонентов: backend, база данных, поиск,
    // модель. Разметка для этого подготовлена таблицей статуса выше,
    // а не отдельным блоком — чтобы не плодить два источника правды
    // о состоянии системы.
    if (window.console && console.info) {
      console.info("[CourtDraft] health:", health);
    }
  }

  function bindBackend() {
    if (!CONFIG.apiBaseUrl) { return; }

    apiGet("/api/health")
      .then(function (health) {
        state.online = true;
        setIndicator(true);
        renderHealth(health);
        document.dispatchEvent(
          new CustomEvent("courtdraft:health", { detail: health })
        );
      })
      .catch(function (error) {
        state.online = false;
        setIndicator(false);
        if (window.console && console.warn) {
          console.warn("[CourtDraft] бэкенд недоступен:", error.message);
        }
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bindBackend);
  } else {
    bindBackend();
  }

  // Публичный доступ для будущих модулей сайта.
  window.CourtDraftSite = {
    config: CONFIG,
    state: state,
    api: { get: apiGet },
    checkBackend: bindBackend
  };
})();
