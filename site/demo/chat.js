/* Диалоговое окно демонстрации по десяти реальным обезличенным делам.
 *
 * Ответы собираются из cases.json — результата прогона правил системы
 * по этим делам (scripts/build_real_site.py). Ни одна цифра в ответе не
 * набирается руками: всё берётся из требований, итога, источников и
 * замечаний проверки, которые система вывела сама.
 *
 * Правило, важное для этого продукта: на вопрос, ответа на который в
 * материалах нет, окно говорит, что не знает. Молчаливый
 * правдоподобный ответ хуже отказа: судья принял бы его за
 * установленный факт.
 */

(function () {
  "use strict";

  var DATA_URL = "cases.json";
  var state = { cases: [], current: null };

  /* Коды из данных показываются словами (п. 10 разбора). */
  var SEVERITY_TEXT = {
    CRITICAL: "критично",
    HIGH: "существенно",
    MEDIUM: "требует внимания",
    LOW: "незначительно"
  };

  var STATUS_TEXT = {
    PASS: "замечаний нет",
    REVIEW_REQUIRED: "требует проверки",
    BLOCKED: "заблокировано"
  };

  function label(map, key) {
    return map[key] || key;
  }

  function $(id) {
    return document.getElementById(id);
  }

  function escapeHtml(text) {
    return String(text == null ? "" : text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function money(value) {
    if (typeof value !== "number" || !isFinite(value) || value === 0) return "";
    return value.toLocaleString("ru-RU").replace(/ /g, " ");
  }

  function rubles(value) {
    var text = money(value);
    return text ? text + " руб." : "";
  }

  /* Сумма с копейками: «20 921,53 руб.». Копейки в требованиях есть,
     и итог без них расходится с перечнем на копейки. */
  function rublesWith(value, kopecks) {
    var text = money(value);
    if (!text) {
      return "";
    }
    if (kopecks) {
      var tail = kopecks < 10 ? "0" + kopecks : String(kopecks);
      return text + "," + tail + " руб.";
    }
    return text + " руб.";
  }

  function case_() {
    return state.current || {};
  }

  function rules() {
    return case_().rules || {};
  }

  function addBubble(role, html) {
    var bubble = document.createElement("div");
    bubble.className = "bubble bubble-" + role;
    var body = document.createElement("div");
    body.className = "bubble-body";
    body.innerHTML = html;
    bubble.appendChild(body);
    $("log").appendChild(bubble);
    $("log").scrollTop = $("log").scrollHeight;
  }

  function say(html) {
    addBubble("system", html);
  }

  function cite(source) {
    return '<span class="cite">' + escapeHtml(source) + "</span>";
  }

  function list(items) {
    return (
      "<ul>" +
      items
        .map(function (item) {
          return "<li>" + item + "</li>";
        })
        .join("") +
      "</ul>"
    );
  }

  /* ── Ответы ───────────────────────────────────────────────────── */

  var answers = {
    /* «Сформируй проект решения» */
    draft: function () {
      var text = case_().operative_text || "";
      var sources = case_().sources || [];
      var issues = (case_().verification || {}).issues || [];
      return (
        "<p>Резолютивная часть собрана по правилам и от модели не " +
        "зависит: в ней суд постановляет, кому и сколько платить.</p>" +
        "<blockquote>" +
        escapeHtml(text) +
        "</blockquote>" +
        "<p>Источники сумм: " +
        (sources.length
          ? sources.map(escapeHtml).join(", ")
          : "не установлены") +
        ". Замечаний проверки: " +
        issues.length +
        ".</p>"
      );
    },

    /* «Какие требования заявлены?» */
    claims: function () {
      var data = rules();
      var claims = data.claims || [];
      var others = data.other_claims || [];
      if (!claims.length && !others.length) {
        return (
          "<p>По этим материалам требований с суммой не нашлось.</p>" +
          "<p>Это тоже ответ: система говорит, что не разобрала дело, " +
          "а не сочиняет требования. Судья видит, что документов " +
          "недостаточно или что их надо дочитать.</p>"
        );
      }
      var items = claims.map(function (claim) {
        return (
          "<strong>" +
          escapeHtml(rubles(claim.amount)) +
          "</strong> — " +
          escapeHtml(claim.basis || "основание не определено") +
          " " +
          cite(claim.source || "источник не указан")
        );
      });
      others.forEach(function (claim) {
        // Требование без суммы не начинается с «— сумма»: строка с
        // висящим тире ничего не говорит читателю.
        var title = claim.description || claim.basis || "";
        if (!title) {
          return;
        }
        items.push(
          (claim.description ? "" : "<strong>без суммы</strong> — ") +
            escapeHtml(title) +
            " " +
            cite(claim.basis && claim.description ? claim.basis : "")
        );
      });
      (data.counter_claims || []).forEach(function (counter) {
        items.push(
          "<em>встречное требование ответчика</em>: " +
            escapeHtml(counter.basis || "") +
            ", исход: " +
            escapeHtml(counter.outcome) +
            " " +
            cite(counter.source || "")
        );
      });
      return (
        "<p>Из материалов извлечено требований: <strong>" +
        items.length +
        "</strong>.</p>" +
        list(items)
      );
    },

    /* «Откуда сумма?» */
    total: function () {
      var data = rules();
      var claims = data.claims || [];
      var fee = data.fee_paid;
      var costs = data.costs;
      /* Итог в резолюции «всего подлежит взысканию» включает иные
         расходы (ст. 100 ГПК РФ), поэтому и здесь сумма должна быть
         та же, а не только требования с пошлиной. */
      var total = (data.total_with_fee || 0) + (costs || 0);
      if (!total) {
        return (
          "<p>Итог по делу не посчитан: суммы требований в материалах " +
          "не установлены.</p>"
        );
      }
      var parts = claims.map(function (claim) {
        return (
          escapeHtml(rublesWith(claim.amount, claim.kopecks)) +
          " — " +
          escapeHtml(claim.basis || "") +
          " " +
          cite(claim.source || "")
        );
      });
      if (fee) {
        parts.push(
          escapeHtml(rubles(fee)) + " — государственная пошлина " + cite("ст. 98 ГПК РФ")
        );
      }
      if (costs) {
        parts.push(
          escapeHtml(rubles(costs)) + " — иные расходы " + cite("ст. 100 ГПК РФ")
        );
      }
      return (
        "<p>Итог <strong>" +
        escapeHtml(rublesWith(total, data.total_kopecks)) +
        "</strong> сложен из сумм, которые есть в материалах дела:</p>" +
        "<p>" +
        parts.join("<br>＋<br>") +
        "</p>" +
        "<p>Сам итог в материалах не встречается — его считает система. " +
        "Поэтому проверка его и не помечает как выдуманный: это " +
        "арифметика, а не новая сумма.</p>"
      );
    },

    /* «Что требует проверки?» */
    review: function () {
      var verification = case_().verification || {};
      var issues = verification.issues || [];
      var gaps = case_().gaps || [];
      if (!issues.length && !gaps.length) {
        return (
          "<p>Замечаний нет. Статус: <strong>" +
          escapeHtml(label(STATUS_TEXT, verification.status) || verification.status || "—") +
          "</strong>.</p>"
        );
      }
      var items = issues.map(function (issue) {
        return (
          '<strong class="sev sev-' +
          escapeHtml(issue.severity) +
          '">' +
          escapeHtml(label(SEVERITY_TEXT, issue.severity) || issue.severity) +
          "</strong> " +
          escapeHtml(issue.reason) +
          (issue.section ? " <em>(" + escapeHtml(issue.section) + ")</em>" : "")
        );
      });
      gaps.forEach(function (gap) {
        items.push("<em>Пропуск:</em> " + escapeHtml(gap));
      });
      return (
        "<p>Проверка проекта: <strong>" +
        escapeHtml(label(STATUS_TEXT, verification.status) || verification.status || "—") +
        "</strong>, замечаний: " +
        (issues.length + gaps.length) +
        ", утверждений без источника: " +
        (verification.unsupported_claims || 0) +
        ".</p>" +
        list(items)
      );
    },

    /* «Кто стороны?» */
    parties: function () {
      var parties = rules().parties || {};
      var items = [];
      if (parties.plaintiff) {
        items.push("<strong>истец</strong>: " + escapeHtml(parties.plaintiff));
      }
      if (parties.defendant) {
        items.push("<strong>ответчик</strong>: " + escapeHtml(parties.defendant));
      }
      if (!items.length) {
        return (
          "<p>Стороны в материалах не определены: в обезличенном тексте " +
          "имена заменены, и правила не нашли обозначений ролей.</p>"
        );
      }
      return (
        "<p>Стороны по материалам дела:</p>" +
        list(items) +
        '<p class="cite">Названия взяты как есть, в том падеже, в ' +
        "котором они стоят в материалах.</p>"
      );
    },

    /* «Какие документы в деле?» */
    documents: function () {
      var docs = case_().documents_list || [];
      if (!docs.length) {
        return "<p>Материалы дела не загружены.</p>";
      }
      var items = docs.map(function (doc) {
        return (
          "<strong>" +
          escapeHtml(doc.name || doc.filename || "") +
          "</strong>" +
          escapeHtml(doc.facts === "0" ? " — фактов не извлечено" : "")
        );
      });
      return (
        "<p>В деле документов: <strong>" +
        docs.length +
        "</strong>.</p>" +
        list(items)
      );
    },

    /* «Как решил суд?» */
    court: function () {
      var text = case_().court_decision_reference || "";
      if (!text) {
        return "<p>Решение суда по этому делу не найдено.</p>";
      }
      return (
        "<p>Вот что суд постановил по этому делу. Система его не " +
        "читала: резолютивная часть суда не подаётся в материалы, " +
        "иначе демо показывало бы пересказ чужого решения.</p>" +
        "<blockquote>" +
        escapeHtml(text) +
        "</blockquote>" +
        '<p class="cite">Сравните с проектом системы: разница в суммах ' +
        "и том, что суд счёл нужным, — это и есть работа судьи.</p>"
      );
    }
  };

  /* ── Распознавание вопроса ────────────────────────────────────── */

  /*
   * Признаки подбираются по смыслу вопроса, а не по точному совпадению.
   * Задача окна — отвечать человеку, а не повторять ему эталонную
   * фразу, которой нет в коде.
   */
  function intent(question) {
    var q = question.toLowerCase();
    if (/суд|как решил|реальн|оригинал/.test(q)) {
      return answers.court;
    }
    if (/итог|всего|назад|сумм|откуда|почему/.test(q) && !/требован/.test(q)) {
      return answers.total;
    }
    if (/требован|что заяв|претенз|иск про|взыскива/.test(q)) {
      return answers.claims;
    }
    if (/провер|замечани|ошиб|сомнени|надёж|уверен|упущено/.test(q)) {
      return answers.review;
    }
    if (/сторон|истец|ответчик|кто участник/.test(q)) {
      return answers.parties;
    }
    if (/документ|материал|приложен|что в деле|файл/.test(q)) {
      return answers.documents;
    }
    if (/резолютив|решил|предмет|постановил|проект/.test(q)) {
      return answers.draft;
    }
    return null;
  }

  function fallback() {
    return (
      "<p>На этот вопрос в материалах дела ответа нет.</p>" +
      "<p>Я не буду догадываться: в этом продукте выдуманное " +
      "утверждение опаснее отсутствующего. В материалах есть " +
      "требования, стороны, документы, замечания проверки и решение " +
      "суда — спросите о них.</p>"
    );
  }

  /* ── Отрисовка дела ───────────────────────────────────────────── */

  function suggestions() {
    var total = rubles(rules().total_with_fee);
    var out = ["Сформируй проект решения", "Какие требования заявлены?"];
    if (total) {
      out.push("Откуда взялась сумма " + total + "?");
    }
    out.push("Что требует проверки специалистом?");
    out.push("Кто стороны по делу?");
    out.push("Какие документы в деле?");
    out.push("Как решил суд это дело?");
    out.push("Сколько стоит квартира в центре Самары?");
    return out;
  }

  function renderCase() {
    var data = case_();
    var parties = rules().parties || {};
    $("case-line").textContent =
      "Дело № " + (data.case_number || "") +
      (data.category ? " · " + data.category : "");
    $("court-line").textContent = data.court || "";
    $("case-party").textContent = [
      parties.plaintiff ? "истец: " + parties.plaintiff : "",
      parties.defendant ? "ответчик: " + parties.defendant : ""
    ]
      .filter(Boolean)
      .join(" · ");
    $("doc-list").innerHTML = (data.documents_list || [])
      .map(function (doc) {
        return "<li>" + escapeHtml(doc.filename || "") + "</li>";
      })
      .join("") || '<li class="muted">нет</li>';

    $("suggest").innerHTML = suggestions()
      .map(function (text) {
        return (
          '<li><button type="button" class="chat-chip">' +
          escapeHtml(text) +
          "</button></li>"
        );
      })
      .join("");

    Array.prototype.forEach.call(
      document.querySelectorAll(".chat-chip"),
      function (button) {
        button.addEventListener("click", function () {
          $("ask").value = button.textContent;
          $("form").dispatchEvent(new Event("submit", { cancelable: true }));
        });
      }
    );
  }

  function greeting() {
    var data = case_();
    return (
      "<p>Дело <strong>" +
      escapeHtml(data.case_number || "") +
      "</strong>" +
      (data.category ? ", " + escapeHtml(data.category) : "") +
      ". Спросите о требованиях, суммах, сторонах или о том, как это " +
      "дело решил суд.</p>" +
      "<p>Отвечаю по материалам дела. Где данных нет, говорю об этом " +
      "прямо: придумывать нельзя.</p>"
    );
  }

  function selectCase(slug) {
    state.current = state.cases.filter(function (item) {
      return item.slug === slug;
    })[0] || state.cases[0];
    $("case-select").value = state.current.slug;
    renderCase();
    $("log").innerHTML = "";
    say(greeting());
    $("ask").focus();
  }

  function start(payload) {
    state.cases = payload.cases || [];
    if (!state.cases.length) {
      say("<p>Дела не загрузились.</p>");
      return;
    }

    $("mode").textContent = "дел: " + state.cases.length;
    $("case-select").innerHTML = state.cases
      .map(function (item, index) {
        return (
          '<option value="' +
          escapeHtml(item.slug) +
          '">Дело ' +
          (index + 1) +
          " · " +
          escapeHtml(item.category || item.case_number) +
          "</option>"
        );
      })
      .join("");

    $("case-select").addEventListener("change", function () {
      selectCase($("case-select").value);
    });

    selectCase(state.cases[0].slug);
  }

  function attachForm() {
    $("form").addEventListener("submit", function (event) {
      event.preventDefault();
      var input = $("ask");
      var question = input.value.trim();
      if (!question) return;

      if (!state.current) {
        say("<p>Дело ещё загружается. Подождите секунду.</p>");
        return;
      }
      input.value = "";

      addBubble("user", escapeHtml(question));
      var handler = intent(question);
      say(handler ? handler() : fallback());
    });
  }

  fetch(DATA_URL)
    .then(function (response) {
      if (!response.ok) throw new Error("HTTP " + response.status);
      return response.json();
    })
    .then(start)
    .catch(function (error) {
      $("mode").textContent = "демо недоступно";
      say(
        "<p>Не удалось загрузить данные демонстрации: " +
          escapeHtml(error.message) +
          "</p>"
      );
    });

  attachForm();
})();