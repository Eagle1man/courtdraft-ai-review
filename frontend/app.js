/* Логика интерфейса.
 *
 * Порядок работы повторяет путь судьи: выбрать дело → увидеть материалы →
 * сформировать проект → прочитать его по разделам → посмотреть, что
 * требует проверки → при необходимости внести правку.
 *
 * Формирование идёт в фоне и занимает минуты, поэтому здесь есть опрос
 * состояния задачи. Пока опрос идёт, кнопки блокируются: иначе пользователь
 * запустит вторую генерацию поверх первой и получит две расходящиеся версии.
 *
 * Обёртка api() всегда бросает исключение с текстом ответа сервера:
 * «дело не найдено» и «база недоступна» требуют разных действий, и
 * проглатывать это сообщение нельзя.
 */

const API = "";              // тот же origin: интерфейс раздаётся бэкендом
const POLL_INTERVAL = 3000;

const state = {
  cases: [],
  currentCase: null,
  documents: [],
  draft: null,
  jobTimer: null,
};

/* ── Работа с API ─────────────────────────────────────────────── */

async function api(path, options = {}) {
  const response = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // Ответ без JSON: оставляем код статуса, он информативнее,
      // чем выдуманная причина.
    }
    throw new Error(detail);
  }

  if (response.status === 204) return null;
  return response.json();
}

/* ── Мелкие помощники ─────────────────────────────────────────── */

const $ = (id) => document.getElementById(id);

function show(element, visible = true) {
  element.hidden = !visible;
}

function showAlert(message, ok = false) {
  const box = $("alert");
  box.textContent = message;
  box.className = ok ? "alert ok" : "alert";
  show(box, true);
  if (ok) {
    setTimeout(() => show(box, false), 4000);
  }
}

/**
 * Очистить текст, оставляя пометки о проверке видимыми.
 * Пометка «ТРЕБУЕТ ПРОВЕРКИ СПЕЦИАЛИСТОМ» не должна тонуть в тексте.
 */
function escapeHtml(text) {
  return (text || "").replace(/[&<>"]/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;",
  }[ch]));
}

const NEEDS_REVIEW = "ТРЕБУЕТ ПРОВЕРКИ СПЕЦИАЛИСТОМ";

/* ── Состояние сервиса ────────────────────────────────────────── */

async function loadHealth() {
  const badge = $("health");
  try {
    const info = await api("/api/info");
    badge.textContent = `версия ${info.version} · режим ${info.llm_provider}`;
  } catch {
    badge.textContent = "сервис недоступен";
  }
}

/* ── Дела ─────────────────────────────────────────────────────── */

async function loadCases() {
  const list = $("case-list");
  try {
    const data = await api("/api/cases?limit=50");
    state.cases = data.items || [];
  } catch (error) {
    list.innerHTML = `<li class="muted">${escapeHtml(error.message)}</li>`;
    return;
  }

  if (!state.cases.length) {
    list.innerHTML = '<li class="muted">Дел пока нет</li>';
    return;
  }

  list.innerHTML = "";
  state.cases.forEach((item) => {
    const li = document.createElement("li");
    li.className = item.id === state.currentCase ? "active" : "";
    li.textContent = `${item.case_number} · ${item.court_name}`;
    li.onclick = () => selectCase(item.id);
    list.appendChild(li);
  });
}

async function selectCase(caseId) {
  state.currentCase = caseId;
  await loadCases();
  await loadDocuments();
  await loadDraft();
  $("btn-generate").disabled = false;
}

async function createDemoCase() {
  const number = `DEMO-${Date.now().toString().slice(-5)}`;

  const created = await api("/api/cases", {
    method: "POST",
    body: JSON.stringify({
      case_number: number,
      court_name: "Демонстрационный районный суд",
      case_type: "civil",
      category: "договорные споры",
      is_synthetic: true,
    }),
  });

  const manifest = await api("/api/demo/manifest").catch(() => null);
  const files = manifest ? manifest.documents : [];

  for (const file of files) {
    const text = await fetch(`api/demo/${encodeURIComponent(file.filename)}`)
      .then((r) => (r.ok ? r.text() : ""));
    await api(`/api/cases/${created.id}/documents`, {
      method: "POST",
      body: JSON.stringify({
        filename: file.filename,
        document_type: file.document_type,
        mime_type: "text/plain",
        text,
      }),
    });
  }

  showAlert(
    files.length
      ? `Создано дело ${number} с ${files.length} материалами.`
      : `Создано дело ${number}. Материалы не загружены.`,
    true
  );

  await selectCase(created.id);
}

/* ── Материалы ────────────────────────────────────────────────── */

async function loadDocuments() {
  const list = $("doc-list");
  if (!state.currentCase) {
    list.innerHTML = '<li class="muted">Дело не выбрано</li>';
    return;
  }

  try {
    state.documents = await api(`/api/cases/${state.currentCase}/documents`);
  } catch (error) {
    list.innerHTML = `<li class="muted">${escapeHtml(error.message)}</li>`;
    return;
  }

  if (!state.documents.length) {
    list.innerHTML =
      '<li class="muted">Материалов нет. Без них проект не составить.</li>';
    return;
  }

  list.innerHTML = "";
  state.documents.forEach((doc) => {
    const li = document.createElement("li");
    li.innerHTML =
      `<span class="type">${escapeHtml(doc.document_type)}</span>` +
      escapeHtml(doc.filename);
    list.appendChild(li);
  });
}

/* ── Формирование проекта ─────────────────────────────────────── */

async function generate() {
  if (!state.currentCase) return;

  const button = $("btn-generate");
  button.disabled = true;
  show($("progress"), true);
  $("progress-fill").style.width = "8%";
  $("progress-fill").classList.add("busy");
  $("progress-text").textContent = "Формирование проекта…";

  try {
    const job = await api(`/api/cases/${state.currentCase}/draft`, {
      method: "POST",
      body: JSON.stringify({ actor: "judge" }),
    });
    pollJob(job.job_id);
  } catch (error) {
    stopProgress();
    showAlert(`Не удалось запустить формирование: ${error.message}`);
  }
}

function pollJob(jobId) {
  clearInterval(state.jobTimer);

  // Прогресс оценочный: бэкенд не сообщает процент готовности,
  // потому что модель не умеет его сообщать. Честнее показать движение,
  // чем выдумывать точные проценты.
  let ticks = 0;

  state.jobTimer = setInterval(async () => {
    ticks += 1;
    $("progress-fill").style.width = `${Math.min(92, 8 + ticks * 4)}%`;

    try {
      const job = await api(`/api/jobs/${jobId}`);
      $("progress-text").textContent = describeState(job.state, ticks);

      if (job.state === "DONE") {
        stopProgress();
        $("progress-fill").style.width = "100%";
        showAlert("Проект сформирован и проверен.", true);
        await loadDraft();
      } else if (job.state === "FAILED") {
        stopProgress();
        showAlert(`Формирование не удалось: ${job.error || "причина неизвестна"}`);
      }
    } catch (error) {
      stopProgress();
      showAlert(`Не удалось узнать состояние задачи: ${error.message}`);
    }
  }, POLL_INTERVAL);
}

function describeState(jobState, ticks) {
  const seconds = ticks * (POLL_INTERVAL / 1000);
  if (jobState === "PENDING") return "Задача в очереди…";
  if (jobState === "RUNNING") {
    return `Модель пишет проект… ${seconds} с. На процессоре это 2–3 минуты.`;
  }
  return jobState;
}

function stopProgress() {
  clearInterval(state.jobTimer);
  state.jobTimer = null;
  $("progress-fill").classList.remove("busy");
  show($("progress"), false);
  $("btn-generate").disabled = !state.currentCase;
}

/* ── Показ проекта ────────────────────────────────────────────── */

async function loadDraft() {
  if (!state.currentCase) return;

  let draft;
  try {
    draft = await api(`/api/cases/${state.currentCase}/draft`);
  } catch (error) {
    showAlert(`Не удалось получить проект: ${error.message}`);
    return;
  }

  state.draft = draft;

  if (!draft) {
    $("draft-title").textContent = "Проект не сформирован";
    $("draft-meta").textContent =
      "Нажмите «Сформировать проект». Это займёт две-три минуты.";
    show($("verification"), false);
    show($("sources"), false);
    show($("versions"), false);
    show($("editor"), false);
    $("sections").innerHTML =
      '<p class="muted">Разделы проекта появятся здесь.</p>';
    return;
  }

  $("draft-title").textContent = `Проект решения по делу`;
  $("draft-meta").textContent =
    `версия ${draft.current_version} · статус ${draft.status} · ` +
    `разделов ${draft.sections.length} · ` +
    `источников ${draft.sources.length}`;

  renderSections(draft);
  renderVerification(draft.verification);
  renderSources(draft.sources);
  await loadVersions();

  $("edit-text").value = draft.text;
  show($("editor"), true);
}

function renderSections(draft) {
  const box = $("sections");
  box.innerHTML = "";

  draft.sections.forEach((section) => {
    const div = document.createElement("article");
    div.className = "section" + (section.needs_review ? " flagged" : "");

    const badges = [];
    if (section.needs_review) {
      badges.push('<span class="badge review">требует проверки</span>');
    }
    if (section.is_mock) {
      badges.push('<span class="badge mock">заглушка</span>');
    }
    if (section.citations && section.citations.length) {
      badges.push(
        `<span class="badge source">${section.citations.length} источн.</span>`
      );
    }

    div.innerHTML =
      "<header>" +
      `<h4>${escapeHtml(section.name)}</h4>` +
      `<div>${badges.join(" ")}</div>` +
      "</header>" +
      `<div class="body">${escapeHtml(section.text)}</div>` +
      (section.citations && section.citations.length
        ? `<div class="citations">Источники: ${section.citations
            .map(escapeHtml)
            .join(", ")}</div>`
        : '<div class="citations">Источник не указан — раздел требует проверки.</div>');

    box.appendChild(div);
  });

  if (draft.sections.some((s) => s.text.includes(NEEDS_REVIEW))) {
    const note = document.createElement("p");
    note.className = "muted small";
    note.textContent =
      "Пометка «требует проверки» означает, что подтвердить утверждение " +
      "по материалам дела не удалось.";
    box.appendChild(note);
  }
}

function renderVerification(verification) {
  if (!verification) {
    show($("verification"), false);
    return;
  }

  const needsReview = verification.status !== "PASS";
  const box = $("verdict");
  box.className = "verdict " + (needsReview ? "review" : "pass");
  box.textContent = needsReview
    ? `${verification.status}: проект требует проверки специалистом`
    : "PASS: замечаний нет, все разделы опираются на материалы";

  const summary = document.createElement("p");
  summary.className = "muted small";
  summary.textContent =
    `проверено разделов: ${verification.sections_checked} · ` +
    `замечаний: ${verification.issues.length} · ` +
    `утверждений без источника: ${verification.unsupported_claims}`;

  const list = $("issues");
  list.innerHTML = "";

  verification.issues.forEach((issue) => {
    const li = document.createElement("li");
    li.className = issue.severity;

    let html = "";
    if (issue.section) {
      html += `<span class="where">${escapeHtml(issue.section)}</span>`;
    }
    html += `<span class="why">${escapeHtml(issue.reason)}</span>`;
    if (issue.text) {
      html += `<span class="quote">${escapeHtml(issue.text)}</span>`;
    }
    li.innerHTML = html;
    list.appendChild(li);
  });

  $("verification").insertBefore(summary, list);
  show($("verification"), true);
}

function renderSources(sources) {
  const list = $("source-list");
  list.innerHTML = "";
  sources.forEach((source) => {
    const li = document.createElement("li");
    li.textContent = source;
    list.appendChild(li);
  });
  show($("sources"), sources.length > 0);
}

async function loadVersions() {
  if (!state.draft) return;

  let data;
  try {
    data = await api(`/api/cases/${state.currentCase}/draft/versions`);
  } catch {
    show($("versions"), false);
    return;
  }

  const list = $("version-list");
  list.innerHTML = "";

  data.versions.forEach((version) => {
    const li = document.createElement("li");
    const current = version.version === data.current_version ? "v-current" : "";
    li.className = current;
    li.textContent =
      `версия ${version.version} · автор ${authorName(version.author)} · ` +
      `${version.text.length} симв. · ${formatTime(version.created_at)}` +
      (version.comment ? ` · ${version.comment}` : "");
    list.appendChild(li);
  });

  show($("versions"), data.versions.length > 0);
}

function authorName(author) {
  return { ai: "модель", secretary: "секретарь", judge: "судья" }[author] || author;
}

function formatTime(value) {
  if (!value) return "";
  const date = new Date(value);
  return date.toLocaleString("ru-RU", {
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

/* ── Правка ───────────────────────────────────────────────────── */

async function saveEdit() {
  if (!state.draft) return;

  const text = $("edit-text").value.trim();
  if (!text) {
    showAlert("Текст правки пустой.");
    return;
  }

  try {
    const version = await api(`/api/drafts/${state.draft.id}/versions`, {
      method: "POST",
      body: JSON.stringify({
        text,
        author: $("edit-author").value,
        comment: $("edit-comment").value,
      }),
    });

    showAlert(
      `Сохранена версия ${version.version} (автор: ${authorName(version.author)}).`,
      true
    );
    $("edit-comment").value = "";
    await loadDraft();
  } catch (error) {
    showAlert(`Не удалось сохранить правку: ${error.message}`);
  }
}

/* ── Запуск ───────────────────────────────────────────────────── */

$("btn-generate").onclick = generate;
$("btn-save-edit").onclick = saveEdit;
$("btn-new-case").onclick = async () => {
  try {
    await createDemoCase();
  } catch (error) {
    showAlert(`Не удалось создать дело: ${error.message}`);
  }
};

(async function start() {
  await loadHealth();
  await loadCases();

  // Дело выбирается автоматически, если оно уже есть: судье не нужно
  // разбираться в пустом списке при повторном открытии страницы.
  if (state.cases.length) {
    await selectCase(state.cases[0].id);
  }
})();