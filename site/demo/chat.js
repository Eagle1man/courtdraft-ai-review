/* Диалоговое окно демонстрации.
 *
 * Ответы собираются из demo-data.json — того же прогона, из которого
 * сделан проект решения. Ни одна цифра в ответе не набирается вручную:
 * всё берётся из требований, итога, замечаний проверки и списка
 * источников, которые система вывела сама.
 *
 * Правило, важное для этого продукта: на вопрос, ответа на который в
 * материалах нет, окно говорит, что не знает. Молчаливый правдоподобный
 * ответ хуже отказа, потому что судья принял бы его за установленный
 * факт.
 */

(function () {
  "use strict";

  var DATA_URL = "demo-data.json";
  var state = { data: null };

  function $(id) {
    return document.getElementById("log").ownerDocument.getElementById(id);
  }

  function escapeHtml(text) {
    return String(text == null ? "" : text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function money(value) {
    if (typeof value !== "number" || !isFinite(value)) return "—";
    return value.toLocaleString("ru-RU").replace(/ /g, " ");
  }

  function rubles(value) {
    return money(value) + " руб.";
  }

  /* ── Отрисовка реплик ─────────────────────────────────────────── */

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
    return "<ul>" + items.map(function (item) { return "<li>" + item + "</li>"; }).join("") + "</ul>";
  }

  /* ── Ответы ───────────────────────────────────────────────────── */

  var answers = {
    /* «Сформируй проект решения» */
    draft: function () {
      var sections = state.data.sections;
      var mock = sections.filter(function (s) { return s.is_mock; }).length;
      return (
        "<p>Проект решения собран. Всего разделов: <strong>" + sections.length +
        "</strong>, источников: <strong>" + state.data.sources.length + "</strong>.</p>" +
        (mock
          ? "<p>Часть разделов не сформирована: языковая модель на этой машине " +
            "не подключена, вместо текста показана служебная заглушка. " +
            "Я не буду изображать готовый текст.</p>"
          : "") +
        "<p>Резолютивная часть собирается правилами и от модели не зависит:</p>" +
        "<blockquote>" + escapeHtml(sectionText("operative")) + "</blockquote>" +
        '<p class="cite">Проект целиком — на странице ' +
        '<a href="index.html">демонстрации</a>.</p>'
      );
    },

    /* «Какие требования заявлены?» */
    claims: function () {
      var rules = state.data.rules || {};
      var claims = rules.claims || [];
      if (!claims.length) {
        return "<p>Требований с суммой в материалах не нашлось. " +
          "Судья должен проверить, все ли документы загружены.</p>";
      }
      var items = claims.map(function (claim) {
        return "<strong>" + escapeHtml(rubles(claim.amount)) + "</strong> — " +
          escapeHtml(claim.basis || "основание не определено") + " " +
          cite(claim.source || "источник не указан");
      });
      var other = rules.other_claims || [];
      if (other.length) {
        other.forEach(function (claim) {
          items.push(escapeHtml(claim.description || "") + " " +
            cite(claim.source || "источник не указан"));
        });
      }
      var counters = rules.counter_claims || [];
      if (counters.length) {
        counters.forEach(function (counter) {
          items.push("<em>встречное требование ответчика</em>: " +
            escapeHtml(counter.basis || "") + ", исход: " +
            escapeHtml(counter.outcome) + " " + cite(counter.source || ""));
        });
      }
      return "<p>Из материалов извлечено требований: <strong>" + items.length +
        "</strong>.</p>" + list(items);
    },

    /* «Откуда сумма?» */
    total: function () {
      var rules = state.data.rules || {};
      var claims = rules.claims || [];
      var fee = rules.fee_paid;
      var total = rules.total_with_fee;

      var parts = claims.map(function (claim) {
        return escapeHtml(rubles(claim.amount)) + " — " +
          escapeHtml(claim.basis || "") + " " + cite(claim.source || "");
      });
      if (fee) {
        parts.push(escapeHtml(rubles(fee)) + " — государственная пошлина " +
          cite("ст. 98 ГПК РФ"));
      }
      var formula = parts.join("<br>＋<br>");

      return "<p>Итог <strong>" + escapeHtml(rubles(total)) +
        "</strong> сложен из сумм, которые есть в материалах дела:</p>" +
        "<p>" + formula + "</p>" +
        "<p>Итог сам по себе в материалах не встречается — его считает " +
        "система, и он равен сумме перечисленного. Поэтому проверка его " +
        "и не помечает как выдуманный: это арифметика, а не новая сумма.</p>";
    },

    /* «Что требует проверки?» */
    review: function () {
      var verification = state.data.verification || {};
      var issues = verification.issues || [];
      if (!issues.length) {
        return "<p>Замечаний проверки нет. Статус: <strong>" +
          escapeHtml(verification.status) + "</strong>.</p>";
      }
      var items = issues.map(function (issue) {
        return '<strong class="sev sev-' + escapeHtml(issue.severity) + '">' +
          escapeHtml(issue.severity) + "</strong> " +
          escapeHtml(issue.reason) +
          (issue.section ? " <em>(" + escapeHtml(issue.section) + ")</em>" : "");
      });
      return "<p>Проверка проекта: <strong>" +
        escapeHtml(verification.status) + "</strong>, замечаний: " +
        issues.length + ", утверждений без источника: " +
        (verification.unsupported_claims || 0) + ".</p>" + list(items);
    },

    /* «Кто стороны?» */
    parties: function () {
      var rules = state.data.rules || {};
      var parties = rules.parties || {};
      var items = [];
      if (parties.plaintiff) {
        items.push("<strong>истец</strong>: " + escapeHtml(parties.plaintiff));
      }
      if (parties.defendant) {
        items.push("<strong>ответчик</strong>: " + escapeHtml(parties.defendant));
      }
      if (!items.length) {
        (state.data.participants || []).forEach(function (line) {
          items.push(escapeHtml(line));
        });
      }
      if (!items.length) {
        return "<p>Стороны в материалах не определены.</p>";
      }
      return "<p>Стороны по материалам дела:</p>" + list(items) +
        '<p class="cite">Названия взяты как есть, в том падеже, в ' +
        "котором они стоят рядом со словом «Ответчик:».</p>";
    },

    /* «Какие документы в деле?» */
    documents: function () {
      var docs = state.data.documents || [];
      if (!docs.length) return "<p>Материалы дела не загружены.</p>";
      var items = docs.map(function (doc) {
        var facts = doc.facts === "0"
          ? " — фактов не извлечено"
          : " — фактов: " + doc.facts;
        return "<strong>" + escapeHtml(doc.name) + "</strong>" + escapeHtml(facts) +
          (doc.title ? '<br><span class="cite">' +
            escapeHtml(doc.title) + "</span>" : "");
      });
      var empty = docs.filter(function (doc) { return doc.facts === "0"; }).length;
      var tail = empty
        ? "<p>Из " + empty + " документов фактов не извлечено. Это видно " +
          "намеренно: молча пропущенный документ выглядит так, будто его " +
          "не было в деле.</p>"
        : "";
      return "<p>В деле документов: <strong>" + docs.length + "</strong>.</p>" +
        list(items) + tail;
    },

    /* «Какое решение?» */
    operative: function () {
      return "<p>Резолютивная часть решения:</p><blockquote>" +
        escapeHtml(sectionText("operative")) + "</blockquote>";
    }
  };

  function sectionText(key) {
    var sections = state.data.sections || [];
    for (var i = 0; i < sections.length; i++) {
      if (sections[i].key === key) return sections[i].text;
    }
    return "";
  }

  /* ── Распознавание вопроса ────────────────────────────────────── */

  /*
   * Признаки подбираются по смыслу вопроса, а не по точному совпадению.
   * Задача окна — отвечать на вопросы человека, а не повторять ему
   * эталонную фразу, которой нет в коде.
   */
  function intent(question) {
    var q = question.toLowerCase();

    if (/итог|всего|назад|сумм|откуда|почему.*(\d|руб)/.test(q) &&
        !/требован/.test(q)) {
      return answers.total;
    }
    if (/требован|что заяв|претенз|иск про|взыскива/.test(q)) {
      return answers.claims;
    }
    if (/провер|замечани|ошиб|сомнени|надёж|уверен/.test(q)) {
      return answers.review;
    }
    if (/сторон|истец|ответчик|кто участник/.test(q)) {
      return answers.parties;
    }
    if (/документ|материал|приложен|что в деле|файл/.test(q)) {
      return answers.documents;
    }
    if (/резолютив|решил|предмет|постановил|взыскать в/.test(q)) {
      return answers.operative;
    }
    if (/проект|сформируй|сделай|подготовь|решение|акт/.test(q)) {
      return answers.draft;
    }
    return null;
  }

  function fallback(question) {
    return "<p>На этот вопрос в материалах дела ответа нет.</p>" +
      "<p>Я не буду догадываться: в этом продукте выдуманное " +
      "утверждение опаснее отсутствующего. В материалах есть " +
      "требования, стороны, документы и замечания проверки — " +
      "спросите о них.</p>";
  }

  /* ── Запуск ───────────────────────────────────────────────────── */

  var SUGGESTIONS = [
    "Сформируй проект решения",
    "Какие требования заявлены?",
    "Откуда взялась сумма 155 100 рублей?",
    "Что требует проверки специалистом?",
    "Кто стороны по делу?",
    "Какие документы в деле?",
    "Сколько стоит квартира в центре Самары?"
  ];

  function start(data) {
    state.data = data;

    $("mode").textContent = "режим: " + data.mode;
    $("case-line").textContent =
      "Дело № " + data.case_number + (data.court_name ? " · " + data.court_name : "");

    var parties = data.rules && data.rules.parties
      ? data.rules.parties
      : {};
    $("parties-line").textContent = [
      parties.plaintiff ? "истец: " + parties.plaintiff : "",
      parties.defendant ? "ответчик: " + parties.defendant : ""
    ].filter(Boolean).join(" · ");

    $("doc-list").innerHTML = (data.documents || []).map(function (doc) {
      return "<li>" + escapeHtml(doc.name) + "</li>";
    }).join("") || '<li class="muted">нет</li>';

    $("suggest").innerHTML = SUGGESTIONS.map(function (text) {
      return '<li><button type="button" class="chat-chip">' +
        escapeHtml(text) + "</button></li>";
    }).join("");

    Array.prototype.forEach.call(
      document.querySelectorAll(".chat-chip"),
      function (button) {
        button.addEventListener("click", function () {
          $("ask").value = button.textContent;
          $("form").dispatchEvent(new Event("submit", { cancelable: true }));
        });
      }
    );

    say(
      "<p>Спросите меня о деле — например, какие требования заявлены, " +
      "откуда взялась сумма или что требует проверки.</p>" +
      "<p>Отвечаю по материалам дела. Где данных нет, говорю об этом " +
      "прямо: придумывать нельзя.</p>"
    );

    $("ask").focus();
  }

  /*
   * Обработчик вопроса подключается сразу, а не после загрузки данных.
   * Иначе вопрос, заданный в первую секунду после открытия страницы,
   * исчезал бы молча: форма была ещё не готова, и реплика не
   * отправлялась.
   */
  function attachForm() {
    $("form").addEventListener("submit", function (event) {
      event.preventDefault();
      if (!state.data) {
        say("<p>Данные дела ещё загружаются. Подождите секунду и спросите " +
          "снова.</p>");
        return;
      }
      var input = $("ask");
      var question = input.value.trim();
      if (!question) return;
      input.value = "";

      addBubble("user", escapeHtml(question));
      var handler = intent(question);
      say(handler ? handler() : fallback(question));
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
      say("<p>Не удалось загрузить данные демонстрации: " +
        escapeHtml(error.message) + "</p>");
    });

  attachForm();
})();
