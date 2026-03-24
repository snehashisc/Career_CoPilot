const form = document.getElementById("auditForm");
const reportSection = document.getElementById("reportSection");
const reportContent = document.getElementById("reportContent");
const statusMessage = document.getElementById("statusMessage");
const submitBtn = document.getElementById("submitBtn");
const submitBtnText = document.getElementById("submitBtnText");
const submitBtnSpinner = document.getElementById("submitBtnSpinner");
const recentAuditsContent = document.getElementById("recentAuditsContent");
const emptyState = document.getElementById("emptyState");
const resumeInput = document.getElementById("resume");
const targetRoleInput = document.getElementById("target_role");
const fileNameDisplay = document.getElementById("fileNameDisplay");
const currentSalaryInput = document.getElementById("current_salary_lpa");
const snackbar = document.getElementById("snackbar");
let statusTimeoutId = null;
let snackbarTimeoutId = null;

function formatCurrencyLpa(value) {
  return `${Number(value).toFixed(1)} LPA`;
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function formatDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return escapeHtml(value);
  }
  return date.toLocaleString();
}

function readinessClass(score) {
  if (score >= 70) return "safe-text";
  if (score >= 45) return "warn-text";
  return "danger-text";
}

function salaryStatusClass(status) {
  if (status === "underpaid") return "danger-text";
  if (status === "fairly_paid") return "safe-text";
  return "warn-text";
}

function salaryStatusLabel(status) {
  if (status === "underpaid") return "Below market range";
  if (status === "fairly_paid") return "Within market range";
  if (status === "overpaid") return "Above market range";
  return "Market status unavailable";
}

function setStatusMessage(message) {
  if (statusTimeoutId) {
    clearTimeout(statusTimeoutId);
    statusTimeoutId = null;
  }
  statusMessage.textContent = message;
}

function showSnackbar(message, type = "info", durationMs = 3200) {
  if (!snackbar) return;
  if (snackbarTimeoutId) {
    clearTimeout(snackbarTimeoutId);
    snackbarTimeoutId = null;
  }

  snackbar.classList.remove("success", "error", "info", "show");
  snackbar.textContent = message;
  snackbar.classList.add(type);
  snackbar.classList.add("show");

  snackbarTimeoutId = setTimeout(() => {
    snackbar.classList.remove("show");
  }, durationMs);
}

function setSuccessMessage(message) {
  setStatusMessage(message);
  showSnackbar(message, "success", 2400);
  statusTimeoutId = setTimeout(() => {
    statusMessage.textContent = "";
  }, 2800);
}

function renderAudit(report) {
  const salary = report.salary_reality_check;
  const risks = report.career_risk_signals;
  const plan = report.action_plan;
  const timeline = report.timeline_prediction;

  const riskBlocks = risks
    .map((risk) => {
      const badgeClass = `badge-${risk.severity}`;
      return `
      <div class="block">
        <p>
          <span class="badge ${badgeClass}">${escapeHtml(risk.severity)}</span>
          <strong>${escapeHtml(risk.signal)}</strong>
        </p>
        <p><strong>Reason:</strong> ${escapeHtml(risk.reason)}</p>
        <p><strong>Mitigation:</strong> ${escapeHtml(risk.mitigation)}</p>
      </div>
    `;
    })
    .join("");

  const assumptionItems = timeline.assumptions.map((assumption) => `<li>${escapeHtml(assumption)}</li>`).join("");
  const readiness = Number(report.readiness_score);
  const readinessProgress = Math.max(0, Math.min(100, readiness));

  reportContent.innerHTML = `
    <div class="metric-grid">
      <div class="metric-card">
        <p class="metric-label">Role Context</p>
        <p class="metric-value">${escapeHtml(report.requested_target_role || report.inferred_current_role)}</p>
        <p class="recent-meta">${report.requested_target_role ? "Target role accepted" : "Using inferred current role"}</p>
      </div>
      <div class="metric-card">
        <p class="metric-label">Readiness Score</p>
        <p class="metric-value ${readinessClass(readiness)}">${escapeHtml(report.readiness_score)} / 100</p>
        <div class="progress-wrap">
          <div class="progress-track">
            <div class="progress-bar" style="width:${readinessProgress}%"></div>
          </div>
        </div>
      </div>
      <div class="metric-card">
        <p class="metric-label">Timeline</p>
        <p class="metric-value">${escapeHtml(timeline.timeline_months)} months</p>
      </div>
      <div class="metric-card">
        <p class="metric-label">Experience (inferred)</p>
        <p class="metric-value">${escapeHtml(report.inferred_years_experience)} years</p>
      </div>
      <div class="metric-card">
        <p class="metric-label">Target Comp</p>
        <p class="metric-value">${formatCurrencyLpa(timeline.target_comp_lpa)}</p>
      </div>
    </div>

    <h3 class="section-title">Detected Skill Signals</h3>
    <div class="pill-row">
      ${Object.entries(report.inferred_skills)
        .flatMap(([bucket, skills]) => skills.map((skill) => `<span class="chip">${escapeHtml(bucket)}: ${escapeHtml(skill)}</span>`))
        .join("") || '<span class="chip">No strong skill signals from resume text</span>'}
    </div>

    <h3 class="section-title">Top Priority Gaps</h3>
    <div class="block">
      <ul>${report.priority_gaps.map((gap) => `<li>${escapeHtml(gap)}</li>`).join("")}</ul>
    </div>

    <h3 class="section-title">Salary Reality Check</h3>
    <div class="block">
      <p><strong>Status:</strong> <span class="${salaryStatusClass(salary.status)}">${escapeHtml(salaryStatusLabel(salary.status))}</span></p>
      <p><strong>Current Salary:</strong> ${formatCurrencyLpa(salary.current_lpa)}</p>
      <p><strong>Market Band:</strong> ${formatCurrencyLpa(salary.market_band_lpa.min)} - ${formatCurrencyLpa(salary.market_band_lpa.max)}</p>
      ${salary.status === "overpaid" 
        ? `<p><strong>Above Market By:</strong> ${formatCurrencyLpa(Math.abs(salary.estimated_gap_lpa.min))} to ${formatCurrencyLpa(Math.abs(salary.estimated_gap_lpa.max))}</p>`
        : salary.status === "underpaid"
        ? `<p><strong>Potential Upside:</strong> ${formatCurrencyLpa(Math.abs(salary.estimated_gap_lpa.min))} to ${formatCurrencyLpa(Math.abs(salary.estimated_gap_lpa.max))}</p>`
        : `<p><strong>Market Position:</strong> Well-positioned within band</p>`
      }
      <p><strong>Insight:</strong> ${escapeHtml(salary.benchmark_message)}</p>
    </div>

    <h3 class="section-title">Career Risk Signals</h3>
    ${riskBlocks}

    <h3 class="section-title">Action Plan</h3>
    <div class="block">
      <p><strong>Plan Track:</strong> ${escapeHtml(report.action_plan_track || "general")}</p>
      <p><strong>Why this plan:</strong> ${escapeHtml(report.action_plan_rationale || "Customized based on your profile signals.")}</p>
      <p><strong>Plan items:</strong> ${escapeHtml(plan.length)} detailed steps available</p>
      <div class="action-plan-actions">
        <button id="openCareerGpsBtn" class="action-plan-btn" type="button">Open Career GPS</button>
        <button id="openActionPlanBtn" class="action-plan-btn" type="button">View Full Action Plan</button>
        <button id="openExecutionTrackerBtn" class="action-plan-btn" type="button">Open Execution Tracker</button>
      </div>
    </div>

    <h3 class="section-title">Timeline Prediction</h3>
    <div class="block">
      <p><strong>Target Compensation:</strong> ${formatCurrencyLpa(timeline.target_comp_lpa)}</p>
      <p><strong>Timeline:</strong> ${escapeHtml(timeline.timeline_months)} months</p>
      <p><strong>Confidence:</strong> ${escapeHtml(timeline.confidence)}</p>
      <p><strong>Summary:</strong> ${escapeHtml(timeline.summary)}</p>
      <ul>${assumptionItems}</ul>
    </div>
  `;

  reportSection.classList.remove("hidden");
  reportSection.classList.remove("report-enter");
  void reportSection.offsetWidth;
  reportSection.classList.add("report-enter");
  emptyState.classList.add("hidden");
}

function renderLoadingSkeleton() {
  reportContent.innerHTML = `
    <div class="skeleton-wrap">
      <div class="skeleton"></div>
      <div class="skeleton"></div>
      <div class="skeleton"></div>
      <div class="skeleton"></div>
    </div>
  `;
  reportSection.classList.remove("hidden");
  emptyState.classList.add("hidden");
}

function setSubmittingState(isSubmitting) {
  submitBtn.disabled = isSubmitting;
  submitBtnSpinner.classList.toggle("hidden", !isSubmitting);
  submitBtnText.textContent = isSubmitting ? "Generating..." : "Generate Audit";
}

function setupPanelDepth() {
  const panels = document.querySelectorAll(".panel");
  panels.forEach((panel) => {
    panel.addEventListener("mousemove", (event) => {
      const rect = panel.getBoundingClientRect();
      const offsetX = event.clientX - rect.left;
      const offsetY = event.clientY - rect.top;
      const rotateY = ((offsetX / rect.width) * 2 - 1) * 2.4;
      const rotateX = ((offsetY / rect.height) * -2 + 1) * 2;
      panel.style.transform = `perspective(1000px) rotateX(${rotateX}deg) rotateY(${rotateY}deg)`;
      panel.style.borderColor = "rgba(148, 208, 255, 0.42)";
    });
    panel.addEventListener("mouseleave", () => {
      panel.style.transform = "perspective(1000px) rotateX(0deg) rotateY(0deg)";
      panel.style.borderColor = "";
    });
  });
}

async function loadRecentAudits() {
  try {
    const response = await fetch("/audits/recent?limit=5");
    if (!response.ok) {
      throw new Error("Could not fetch recent audits.");
    }
    const payload = await response.json();
    if (!payload.audits || payload.audits.length === 0) {
      recentAuditsContent.innerHTML = "<p>No audits yet. Your first audit will appear here.</p>";
      return;
    }
    recentAuditsContent.innerHTML = payload.audits
      .map((audit) => {
        const target = audit.target_role ? escapeHtml(audit.target_role) : "Not specified";
        return `
          <div class="block">
            <p class="recent-title"><strong>${escapeHtml(audit.inferred_role)}</strong></p>
            <p class="recent-meta"><strong>Created:</strong> ${formatDate(audit.created_at)}</p>
            <p class="recent-meta"><strong>Target:</strong> ${target}</p>
            <p class="recent-meta"><strong>Readiness:</strong> ${escapeHtml(audit.readiness_score)} / 100</p>
            <p class="recent-meta"><strong>Timeline:</strong> ${escapeHtml(audit.timeline_months)} months</p>
          </div>
        `;
      })
      .join("");
  } catch (error) {
    recentAuditsContent.innerHTML = `<p>Error loading recent audits: ${escapeHtml(error.message)}</p>`;
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const resumeSelected = resumeInput.files && resumeInput.files.length > 0;
  if (!resumeSelected) {
    showSnackbar("Please upload your resume before generating an audit.", "error");
    resumeInput.focus();
    return;
  }

  const salary = Number(currentSalaryInput.value);
  const salaryRaw = currentSalaryInput.value.trim();
  if (salaryRaw === "") {
    currentSalaryInput.classList.add("input-error");
    currentSalaryInput.setCustomValidity("Current salary is required.");
    currentSalaryInput.reportValidity();
    showSnackbar("Current salary is required.", "error");
    return;
  }

  if (Number.isNaN(salary) || salary < 2 || salary > 500) {
    currentSalaryInput.classList.add("input-error");
    currentSalaryInput.setCustomValidity("Enter salary in LPA between 2 and 500.");
    currentSalaryInput.reportValidity();
    showSnackbar("Please enter current salary between 2 and 500 LPA.", "error");
    return;
  }
  currentSalaryInput.classList.remove("input-error");
  currentSalaryInput.setCustomValidity("");

  setStatusMessage("");
  setSubmittingState(true);

  try {
    const formData = new FormData(form);
    const response = await fetch("/audit", { method: "POST", body: formData });
    if (!response.ok) {
      const errorPayload = await response.json().catch(() => ({}));
      throw new Error(errorPayload.detail || "Failed to generate audit.");
    }
    const report = await response.json();
    sessionStorage.setItem("latestAuditReport", JSON.stringify(report));
    if (typeof window.markAuditCompleted === "function") {
      window.markAuditCompleted();
    } else if (typeof window.setAuditNavAvailability === "function") {
      window.setAuditNavAvailability(true);
    }
    renderAudit(report);
    setSuccessMessage("Audit generated successfully.");
    await loadRecentAudits();
  } catch (error) {
    setStatusMessage(`Error: ${error.message}`);
    showSnackbar(error.message, "error", 3600);
  } finally {
    setSubmittingState(false);
  }
});

resumeInput.addEventListener("change", () => {
  const selectedName = resumeInput.files && resumeInput.files[0] ? resumeInput.files[0].name : "No file selected";
  fileNameDisplay.textContent = selectedName;
  setStatusMessage("");
});

targetRoleInput.addEventListener("input", () => {
  setStatusMessage("");
});

currentSalaryInput.addEventListener("input", () => {
  currentSalaryInput.classList.remove("input-error");
  currentSalaryInput.setCustomValidity("");
  setStatusMessage("");
});

reportContent.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }
  if (target.id === "openActionPlanBtn") {
    window.location.href = "/action-plan";
  } else if (target.id === "openCareerGpsBtn") {
    window.location.href = "/career-gps";
  } else if (target.id === "openExecutionTrackerBtn") {
    window.location.href = "/execution-tracker";
  }
});

loadRecentAudits();
setupPanelDepth();
