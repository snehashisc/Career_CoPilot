const content = document.getElementById("actionPlanPageContent");
const AUDIT_UNLOCK_KEY = "careerCopilotHasAudit";

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function renderEmpty() {
  content.innerHTML = `
    <div class="block">
      <p>No generated audit context found.</p>
      <p>Please go back and generate an audit first.</p>
    </div>
  `;
}

function renderPlan(report) {
  const plan = report.action_plan || [];
  if (!plan.length) {
    renderEmpty();
    return;
  }

  const planBlocks = plan
    .map((item) => {
      const details = (item.details || []).map((detail) => `<li>${escapeHtml(detail)}</li>`).join("");
      return `
        <div class="block">
          <h3>${escapeHtml(item.title)}</h3>
          <p><strong>Category:</strong> ${escapeHtml(item.category)}</p>
          <ul>${details}</ul>
          <p><strong>Expected Impact:</strong> ${escapeHtml(item.expected_impact)}</p>
        </div>
      `;
    })
    .join("");

  content.innerHTML = `
    <div class="block">
      <p><strong>Plan Track:</strong> ${escapeHtml(report.action_plan_track || "general")}</p>
      <p><strong>Rationale:</strong> ${escapeHtml(report.action_plan_rationale || "Customized based on profile signals.")}</p>
    </div>
    ${planBlocks}
  `;
}

async function bootstrap() {
  const hasUnlocked = localStorage.getItem(AUDIT_UNLOCK_KEY) === "true";
  if (!hasUnlocked) {
    renderEmpty();
    return;
  }

  try {
    const raw = sessionStorage.getItem("latestAuditReport");
    if (raw) {
      const report = JSON.parse(raw);
      renderPlan(report);
      return;
    }
  } catch (error) {
    // Ignore and fallback to API.
  }

  try {
    const response = await fetch("/audits/latest");
    if (!response.ok) {
      renderEmpty();
      return;
    }
    const payload = await response.json();
    if (!payload.audit) {
      renderEmpty();
      return;
    }
    sessionStorage.setItem("latestAuditReport", JSON.stringify(payload.audit));
    renderPlan(payload.audit);
  } catch (error) {
    renderEmpty();
  }
}

bootstrap();
