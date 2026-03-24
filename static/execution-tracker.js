const trackerSummary = document.getElementById("trackerSummary");
const trackerContent = document.getElementById("trackerContent");
const checklistSummary = document.getElementById("checklistSummary");
const checklistContent = document.getElementById("checklistContent");
const AUDIT_UNLOCK_KEY = "careerCopilotHasAudit";

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function trackerStatusLabel(status) {
  if (status === "todo") return "To Do";
  if (status === "in_progress") return "In Progress";
  if (status === "done") return "Done";
  return status;
}

function renderTracker(payload) {
  const completion = Number(payload.completion_percent || 0);
  if (!payload.items || payload.items.length === 0) {
    trackerSummary.innerHTML = "<strong>0% complete</strong> of current execution checklist";
    trackerContent.innerHTML = "<p class='tracker-empty'>Generate an audit to create your execution checklist.</p>";
    return;
  }

  const createdTimes = payload.items
    .map((item) => new Date(item.created_at).getTime())
    .filter((value) => !Number.isNaN(value));
  const startTime = createdTimes.length ? Math.min(...createdTimes) : Date.now();
  const elapsedDays = Math.max(0, (Date.now() - startTime) / (1000 * 60 * 60 * 24));
  const currentWeek = Math.max(1, Math.min(4, Math.floor(elapsedDays / 7) + 1));
  const overdueCount = payload.items.filter((item) => item.status !== "done" && Number(item.week) < currentWeek).length;
  trackerSummary.innerHTML = `<strong>${completion}% complete</strong> • Current sprint week: <strong>${currentWeek}</strong> • Overdue: <strong>${overdueCount}</strong>`;

  const weekBuckets = { 1: [], 2: [], 3: [], 4: [] };
  payload.items.forEach((item) => {
    const week = Math.max(1, Math.min(4, Number(item.week) || 1));
    weekBuckets[week].push(item);
  });

  trackerContent.innerHTML = Object.entries(weekBuckets)
    .map(([weekLabel, items]) => {
      if (!items.length) return "";
      const weekNumber = Number(weekLabel);
      const weekState = weekNumber < currentWeek ? "past" : weekNumber === currentWeek ? "current" : "upcoming";
      const itemsHtml = items
        .map((item) => {
          const id = escapeHtml(item.id);
          const status = escapeHtml(item.status);
          const category = escapeHtml(item.category);
          const isOverdue = item.status !== "done" && Number(item.week) < currentWeek;
          return `
            <div class="block tracker-item ${isOverdue ? "tracker-overdue" : ""}">
              <div>
                <p class="tracker-title">${escapeHtml(item.title)}</p>
                <p class="tracker-meta">${category} • ${trackerStatusLabel(status)} ${isOverdue ? "<span class='tracker-overdue-tag'>Overdue</span>" : ""}</p>
              </div>
              <div class="tracker-controls">
                <button class="tracker-status-btn ${status === "todo" ? "is-active" : ""}" data-id="${id}" data-status="todo">Todo</button>
                <button class="tracker-status-btn ${status === "in_progress" ? "is-active" : ""}" data-id="${id}" data-status="in_progress">Doing</button>
                <button class="tracker-status-btn ${status === "done" ? "is-active" : ""}" data-id="${id}" data-status="done">Done</button>
              </div>
            </div>
          `;
        })
        .join("");
      return `<section class="tracker-week-group ${weekState}"><h3 class="tracker-week-title">Week ${weekNumber}</h3>${itemsHtml}</section>`;
    })
    .join("");
}

function renderChecklist(payload) {
  const completion = Number(payload.completion_percent || 0);
  checklistSummary.innerHTML = `<strong>${completion}% complete</strong> of your 30-day plan`;

  if (!payload.items || payload.items.length === 0) {
    checklistContent.innerHTML = "<p class='tracker-empty'>No checklist yet. Generate an audit first.</p>";
    return;
  }

  checklistContent.innerHTML = payload.items
    .map((item) => {
      const id = escapeHtml(item.id);
      const status = escapeHtml(item.status);
      return `
        <div class="block checklist-item">
          <div>
            <p class="tracker-title">${escapeHtml(item.title)}</p>
            <p class="checklist-day">Day ${escapeHtml(item.day)} • ${escapeHtml(item.category)} • ${trackerStatusLabel(status)}</p>
          </div>
          <div class="tracker-controls">
            <button class="tracker-status-btn ${status === "todo" ? "is-active" : ""}" data-checklist-id="${id}" data-checklist-status="todo">Todo</button>
            <button class="tracker-status-btn ${status === "in_progress" ? "is-active" : ""}" data-checklist-id="${id}" data-checklist-status="in_progress">Doing</button>
            <button class="tracker-status-btn ${status === "done" ? "is-active" : ""}" data-checklist-id="${id}" data-checklist-status="done">Done</button>
          </div>
        </div>
      `;
    })
    .join("");
}

async function loadTracker() {
  try {
    const response = await fetch("/tracker/items");
    if (!response.ok) throw new Error("Unable to fetch tracker items.");
    renderTracker(await response.json());
  } catch (error) {
    trackerSummary.innerHTML = "";
    trackerContent.innerHTML = `<p class='tracker-empty'>Error loading tracker: ${escapeHtml(error.message)}</p>`;
  }
}

async function loadChecklist() {
  try {
    const response = await fetch("/checklist/30days");
    if (!response.ok) throw new Error("Unable to fetch 30-day checklist.");
    renderChecklist(await response.json());
  } catch (error) {
    checklistSummary.innerHTML = "";
    checklistContent.innerHTML = `<p class='tracker-empty'>Error loading checklist: ${escapeHtml(error.message)}</p>`;
  }
}

function hasLocalAuditContext() {
  const hasSessionReport = Boolean(sessionStorage.getItem("latestAuditReport"));
  const unlocked = localStorage.getItem(AUDIT_UNLOCK_KEY) === "true";
  return hasSessionReport || unlocked;
}

async function updateTrackerItem(itemId, status) {
  const button = document.querySelector(`button[data-id="${itemId}"][data-status="${status}"]`);
  const allButtonsForItem = document.querySelectorAll(`button[data-id="${itemId}"]`);
  
  // Optimistically update UI
  allButtonsForItem.forEach(btn => btn.classList.remove('is-active'));
  if (button) button.classList.add('is-active');
  
  const response = await fetch(`/tracker/items/${itemId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || "Failed to update tracker item.");
  }
  
  // Only update the summary, not the entire tracker
  const data = await response.json();
  const completion = Number(data.completion_percent || 0);
  const createdTimes = data.items
    .map((item) => new Date(item.created_at).getTime())
    .filter((value) => !Number.isNaN(value));
  const startTime = createdTimes.length ? Math.min(...createdTimes) : Date.now();
  const elapsedDays = Math.max(0, (Date.now() - startTime) / (1000 * 60 * 60 * 24));
  const currentWeek = Math.max(1, Math.min(4, Math.floor(elapsedDays / 7) + 1));
  const overdueCount = data.items.filter((item) => item.status !== "done" && Number(item.week) < currentWeek).length;
  trackerSummary.innerHTML = `<strong>${completion}% complete</strong> • Current sprint week: <strong>${currentWeek}</strong> • Overdue: <strong>${overdueCount}</strong>`;
}

async function updateChecklistItem(itemId, status) {
  const button = document.querySelector(`button[data-checklist-id="${itemId}"][data-checklist-status="${status}"]`);
  const allButtonsForItem = document.querySelectorAll(`button[data-checklist-id="${itemId}"]`);
  
  // Optimistically update UI
  allButtonsForItem.forEach(btn => btn.classList.remove('is-active'));
  if (button) button.classList.add('is-active');
  
  const response = await fetch(`/checklist/30days/${itemId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || "Failed to update checklist item.");
  }
  
  // Only update the summary, not the entire checklist
  const data = await response.json();
  const completion = Number(data.completion_percent || 0);
  checklistSummary.innerHTML = `<strong>${completion}% complete</strong> of your 30-day plan`;
}

trackerContent.addEventListener("click", async (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement) || !target.classList.contains("tracker-status-btn")) return;
  const itemId = target.getAttribute("data-id");
  const nextStatus = target.getAttribute("data-status");
  if (!itemId || !nextStatus) return;
  try {
    await updateTrackerItem(itemId, nextStatus);
  } catch (_) {
    // no-op for now
  }
});

checklistContent.addEventListener("click", async (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement) || !target.classList.contains("tracker-status-btn")) return;
  const itemId = target.getAttribute("data-checklist-id");
  const nextStatus = target.getAttribute("data-checklist-status");
  if (!itemId || !nextStatus) return;
  try {
    await updateChecklistItem(itemId, nextStatus);
  } catch (_) {
    // no-op for now
  }
});

async function bootstrap() {
  const hasAudit = hasLocalAuditContext();
  if (!hasAudit) {
    trackerSummary.innerHTML = "<strong>No audit found</strong>";
    trackerContent.innerHTML = "<p class='tracker-empty'>Generate an audit first to unlock execution tracking.</p>";
    checklistSummary.innerHTML = "<strong>No audit found</strong>";
    checklistContent.innerHTML = "<p class='tracker-empty'>Generate an audit first to unlock your 30-day checklist.</p>";
    return;
  }

  loadTracker();
  loadChecklist();
}

bootstrap();
