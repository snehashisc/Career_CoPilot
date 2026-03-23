const gpsComparisonContent = document.getElementById("gpsComparisonContent");
const gpsStatus = document.getElementById("gpsStatus");
const targetButtons = Array.from(document.querySelectorAll(".gps-target-btn"));
const simBackendShift = document.getElementById("simBackendShift");
const simLeadership = document.getElementById("simLeadership");
const simFaangPrep = document.getElementById("simFaangPrep");

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function confidenceClass(value) {
  if (value === "high") return "safe-text";
  if (value === "medium") return "warn-text";
  return "danger-text";
}

function metricDeltaClass(delta, inverse = false) {
  if (delta === 0) return "";
  if (inverse) return delta < 0 ? "safe-text" : "danger-text";
  return delta > 0 ? "safe-text" : "danger-text";
}

function renderGpsCard(payload, title) {
  const factorRows = Object.entries(payload.factors || {})
    .map(
      ([key, value]) => `<li><strong>${escapeHtml(key.replace(/_/g, " "))}:</strong> ${escapeHtml(value)}</li>`
    )
    .join("");
  const gapRows = (payload.gap_analysis || []).map((gap) => `<li>${escapeHtml(gap)}</li>`).join("");
  const explainRows = (payload.explainable_probability || [])
    .map((item) => {
      const impact = Number(item.impact_percent || 0);
      const cls = impact >= 0 ? "safe-text" : "danger-text";
      const sign = impact >= 0 ? "+" : "";
      return `<li><strong>${escapeHtml(item.label)}:</strong> <span class="${cls}">${sign}${escapeHtml(impact)}%</span></li>`;
    })
    .join("");
  const liftRows = (payload.probability_lift_to_40 || [])
    .map((item) => `<li>${escapeHtml(item.action)} <strong>(+${escapeHtml(item.expected_lift_percent)}%)</strong></li>`)
    .join("");
  const actionRows = (payload.next_30_day_action_engine || [])
    .map(
      (item) =>
        `<li>${escapeHtml(item.action)} <strong>(+${escapeHtml(item.expected_lift_percent)}%)</strong> in ${escapeHtml(item.window_days)} days</li>`
    )
    .join("");
  const probability = Number(payload.success_probability_percent || 0);
  const probabilityBar = Math.max(0, Math.min(100, probability));

  return `
    <h3 class="section-title">${escapeHtml(title)}</h3>
    <div class="metric-grid">
      <div class="metric-card">
        <p class="metric-label">Current Role</p>
        <p class="metric-value">${escapeHtml(payload.current_role)}</p>
      </div>
      <div class="metric-card">
        <p class="metric-label">Target Path</p>
        <p class="metric-value">${escapeHtml(payload.target_path)}</p>
      </div>
      <div class="metric-card">
        <p class="metric-label">Success Probability</p>
        <p class="metric-value">${escapeHtml(payload.success_probability_percent)}%</p>
        <div class="progress-wrap">
          <div class="progress-track"><div class="progress-bar" style="width:${probabilityBar}%"></div></div>
        </div>
      </div>
      <div class="metric-card">
        <p class="metric-label">Time to Achieve</p>
        <p class="metric-value">${escapeHtml(payload.time_to_achieve_months)} months</p>
      </div>
      <div class="metric-card">
        <p class="metric-label">Confidence</p>
        <p class="metric-value ${confidenceClass(payload.confidence)}">${escapeHtml(payload.confidence)}</p>
      </div>
    </div>

    <h3 class="section-title">Gap Analysis</h3>
    <div class="block"><ul>${gapRows}</ul></div>

    <h3 class="section-title">Why This Probability</h3>
    <div class="block"><ul>${explainRows}</ul></div>

    <h3 class="section-title">What Moves You Toward 40%</h3>
    <div class="block"><ul>${liftRows}</ul></div>

    <h3 class="section-title">Next 30 Days Action Engine</h3>
    <div class="block"><ul>${actionRows}</ul></div>

    <h3 class="section-title">System Factors</h3>
    <div class="block"><ul>${factorRows}</ul></div>

    <h3 class="section-title">Trajectory Summary</h3>
    <div class="block"><p>${escapeHtml(payload.summary)}</p></div>
  `;
}

function getSimulationParams(forceDisabled = false) {
  if (forceDisabled) {
    return {
      simulate_backend_shift: false,
      simulate_cross_team_leadership: false,
      simulate_faang_prep: false,
    };
  }
  return {
    simulate_backend_shift: Boolean(simBackendShift && simBackendShift.checked),
    simulate_cross_team_leadership: Boolean(simLeadership && simLeadership.checked),
    simulate_faang_prep: Boolean(simFaangPrep && simFaangPrep.checked),
  };
}

async function fetchGps(targetPath, simulation) {
  const params = new URLSearchParams({
    target: targetPath,
    simulate_backend_shift: String(simulation.simulate_backend_shift),
    simulate_cross_team_leadership: String(simulation.simulate_cross_team_leadership),
    simulate_faang_prep: String(simulation.simulate_faang_prep),
  });
  const response = await fetch(`/career-gps/data?${params.toString()}`);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || "Could not compute Career GPS.");
  }
  return response.json();
}

function renderComparison(currentPayload, simulatedPayload) {
  const probDelta = Number(simulatedPayload.success_probability_percent) - Number(currentPayload.success_probability_percent);
  const etaDelta = Number(simulatedPayload.time_to_achieve_months) - Number(currentPayload.time_to_achieve_months);
  const deltaSign = probDelta > 0 ? "+" : "";
  const etaSign = etaDelta > 0 ? "+" : "";

  const currentHtml = renderGpsCard(currentPayload, "Current Trajectory");
  const simulatedHtml = renderGpsCard(simulatedPayload, "Simulated Trajectory");

  gpsComparisonContent.innerHTML = `
    <div class="block">
      <p><strong>Scenario Delta</strong></p>
      <p>Probability change: <span class="${metricDeltaClass(probDelta)}">${deltaSign}${escapeHtml(probDelta)}%</span></p>
      <p>ETA change: <span class="${metricDeltaClass(etaDelta, true)}">${etaSign}${escapeHtml(etaDelta)} months</span></p>
    </div>

    <div class="gps-compare-grid">
      <section class="gps-compare-card">
        ${currentHtml}
      </section>
      <section class="gps-compare-card">
        ${simulatedHtml}
      </section>
    </div>
  `;
}

async function loadGpsComparison(targetPath) {
  gpsStatus.textContent = "Calculating trajectory...";
  try {
    const baseSimulation = getSimulationParams(true);
    const selectedSimulation = getSimulationParams(false);
    const [currentPayload, simulatedPayload] = await Promise.all([
      fetchGps(targetPath, baseSimulation),
      fetchGps(targetPath, selectedSimulation),
    ]);
    renderComparison(currentPayload, simulatedPayload);
    gpsStatus.textContent = "";
  } catch (error) {
    gpsStatus.textContent = `Error: ${error.message}`;
    gpsComparisonContent.innerHTML = "";
  }
}

targetButtons.forEach((button) => {
  button.addEventListener("click", () => {
    targetButtons.forEach((node) => node.classList.remove("is-active"));
    button.classList.add("is-active");
    loadGpsComparison(button.getAttribute("data-target") || "staff engineer");
  });
});

[simBackendShift, simLeadership, simFaangPrep].forEach((node) => {
  if (!node) return;
  node.addEventListener("change", () => {
    const active = document.querySelector(".gps-target-btn.is-active");
    const target = active ? active.getAttribute("data-target") : "staff engineer";
    loadGpsComparison(target || "staff engineer");
  });
});

loadGpsComparison("staff engineer");
