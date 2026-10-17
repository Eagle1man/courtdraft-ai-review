/* Отрисовка демонстрации на сайте.
 *
 * Страница не ходит в API: она читает demo-data.json, собранный
 * скриптом scripts/build_demo_site.py из прогона демо-стенда. Данных
 * в браузере не возникает — всё, что показано, было получено системой
 * ранее и записано в файл.
 *
 * Оформление разделов, пометок и панелей взято из интерфейса продукта
 * (app.css — копия frontend/styles.css). Демо должно выглядеть как
 * продукт: макет на сайте показывает не то, что заказчик увидит
 * после установки.
 */

(function () {
  "use strict";

  var DATA_URL = "demo-data.json";

  var VERDICT_TEXT = {
    PASS: "PASS: замечаний нет",
    REVIEW_REQUIRED:
      "REVIEW_REQUIRED: проект требует проверки специалистом",
    FAILED: "FAILED: проект не может быть показан как готовый"
  };

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

  function amount(value) {
    if (typeof value !== "number" || !isFinite(value)) return "";
    return value.toLocaleString("ru-RU").replace(/,/g, " ") + " руб.";
  }

  function show(node, visible) {
    if (node) node.hidden = !visible;
  }

  function renderCase(data) {
    $("case-number").textContent = "Дело № " + data.case_number;
    $("case-court").textContent = data.court_name || "";

    var parties = [];
    if (data.plaintiff) {
      parties.push({ role: "истец", name: data.plaintiff });
    }
    if (data.defendant) {
      parties.push({ role: "ответчик", name: data.defendant });
    }
    if (!parties.length) {
      parties = (data.participants || []).map(function (line) {
        var match = /^(.*?)\s*\((.*?)\)\s*$/.exec(line);
        return match
          ? { role: match[2], name: match[1] }
          : { role: "", name: line };
      });
    }

    $("party-list").innerHTML = parties
      .map(function (party) {
        return (
          '<li><span class="type">' +
          escapeHtml(party.role) +
          "</span>" +
          escapeHtml(party.name) +
          "</li>"
        );
      })
      .join("");
  }

  function renderDocuments(documents) {
    var list = $("doc-list");
    if (!documents.length) {
      list.innerHTML = '<li class="muted">Материалов нет</li>';
      return;
    }
    list.innerHTML = documents
      .map(function (doc) {
        var facts = doc.facts === "0" ? "" : " · фактов: " + doc.facts;
        return (
          "<li>" +
          '<span class="type">' +
          escapeHtml(doc.document_type || "ДОК") +
          "</span>" +
          escapeHtml(doc.name) +
          escapeHtml(facts) +
          (doc.title ? '<div class="muted small">' + escapeHtml(doc.title) + "</div>" : "") +
          "</li>"
        );
      })
      .join("");
  }

  function renderMeta(data) {
    var sections = data.sections.length;
    var mock = data.sections.filter(function (s) {
      return s.is_mock;
    }).length;
    $("draft-title").textContent = "Проект решения по делу";
    $("draft-meta").textContent =
      "разделов: " +
      sections +
      (mock ? " (заглушек: " + mock + ")" : "") +
      " · источников: " +
      data.sources.length +
      " · проверка: " +
      data.verification.status;
  }

  function renderVerification(verification) {
    var box = $("verification");
    show(box, true);

    var verdict = $("verdict");
    verdict.textContent =
      VERDICT_TEXT[verification.status] || verification.status;
    verdict.className = "verdict " + (verification.status === "PASS" ? "pass" : "review");

    var counts = [];
    counts.push("проверено разделов: " + verification.sections_checked);
    counts.push("замечаний: " + (verification.issues || []).length);
    counts.push("утверждений без источника: " + verification.unsupported_claims);

    var severity = verification.by_severity || {};
    Object.keys(severity).forEach(function (level) {
      counts.push(level + ": " + severity[level]);
    });

    var summary = document.createElement("p");
    summary.className = "muted";
    summary.textContent = counts.join(" · ");
    box.insertBefore(summary, $("issues"));

    $("issues").innerHTML = (verification.issues || [])
      .map(function (issue) {
        return (
          '<li class="' +
          escapeHtml(issue.severity) +
          '"><span class="where">' +
          escapeHtml(issue.severity) +
          (issue.section ? " · " + escapeHtml(issue.section) : "") +
          '</span><span class="why">' +
          escapeHtml(issue.reason) +
          "</span></li>"
        );
      })
      .join("");
  }

  function renderSections(data) {
    var box = $("sections");
    box.innerHTML = data.sections
      .map(function (section) {
        var badges = [];
        if (section.needs_review) {
          badges.push('<span class="badge review">требует проверки</span>');
        }
        if (section.is_mock) {
          badges.push('<span class="badge mock">заглушка</span>');
        }
        if (section.citations && section.citations.length) {
          badges.push(
            '<span class="badge source">' +
              section.citations.length +
              " источн.</span>"
          );
        }

        var citations =
          section.citations && section.citations.length
            ? "Источники: " + section.citations.map(escapeHtml).join(", ")
            : "Источник не указан — раздел требует проверки.";

        return (
          '<article class="section' +
          (section.needs_review ? " flagged" : "") +
          '"><header><h4>' +
          escapeHtml(section.name) +
          "</h4><div>" +
          badges.join(" ") +
          '</div></header><div class="body">' +
          escapeHtml(section.text) +
          '</div><div class="citations">' +
          citations +
          "</div></article>"
        );
      })
      .join("");

    var note = document.createElement("p");
    note.className = "muted small";
    note.textContent =
      "Пометка «требует проверки» означает, что подтвердить утверждение " +
      "по материалам дела не удалось.";
    box.appendChild(note);
  }

  function renderSources(sources) {
    if (!sources.length) return;
    show($("sources"), true);
    $("source-list").innerHTML = sources
      .map(function (source) {
        return "<li>" + escapeHtml(source) + "</li>";
      })
      .join("");
  }

  function fail(message) {
    $("mode").textContent = "демо недоступно";
    $("sections").innerHTML =
      '<p class="muted">Не удалось загрузить данные демонстрации: ' +
      escapeHtml(message) +
      "</p>";
  }

  function start(data) {
    // Модель показывается только когда она отличается от режима: при
    // заглушке это «режим: mock · mock», что выглядит как опечатка.
    var model = data.model && data.model !== data.mode
      ? " · " + data.model
      : "";
    $("mode").textContent = "режим: " + data.mode + model;
    renderCase(data);
    renderDocuments(data.documents || []);
    renderMeta(data);
    renderVerification(data.verification);
    renderSections(data);
    renderSources(data.sources || []);
    show($("how-to-read"), true);

    var claim = amount(data.claim_amount);
    if (claim) {
      var summary = document.createElement("p");
      summary.className = "muted small";
      summary.textContent =
        "Предмет спора: " +
        claim +
        (data.category ? " · " + data.category : "") +
        (data.hearing_date ? " · заседание: " + data.hearing_date : "");
      $("draft-meta").parentNode.appendChild(summary);
    }
  }

  fetch(DATA_URL)
    .then(function (response) {
      if (!response.ok) throw new Error("HTTP " + response.status);
      return response.json();
    })
    .then(start)
    .catch(function (error) {
      fail(error.message);
    });
})();
