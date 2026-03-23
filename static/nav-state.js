(function () {
  const AUDIT_UNLOCK_KEY = "careerCopilotHasAudit";

  function setAuditNavAvailability(hasAudit) {
    const links = document.querySelectorAll("[data-requires-audit='true']");
    links.forEach((link) => {
      if (!(link instanceof HTMLAnchorElement)) return;
      const originalHref = link.dataset.hrefOriginal || link.getAttribute("href") || "/";
      link.dataset.hrefOriginal = originalHref;

      if (hasAudit) {
        link.classList.remove("is-disabled");
        link.removeAttribute("aria-disabled");
        link.removeAttribute("tabindex");
        link.setAttribute("href", originalHref);
      } else {
        link.classList.add("is-disabled");
        link.setAttribute("aria-disabled", "true");
        link.setAttribute("tabindex", "-1");
        link.setAttribute("href", "/");
      }
    });
  }

  function hasLocalAuditContext() {
    const hasSessionReport = Boolean(sessionStorage.getItem("latestAuditReport"));
    const unlocked = localStorage.getItem(AUDIT_UNLOCK_KEY) === "true";
    return hasSessionReport || unlocked;
  }

  function markAuditCompleted() {
    localStorage.setItem(AUDIT_UNLOCK_KEY, "true");
    setAuditNavAvailability(true);
  }

  function bootstrapNavState() {
    setAuditNavAvailability(hasLocalAuditContext());
  }

  window.markAuditCompleted = markAuditCompleted;
  window.setAuditNavAvailability = setAuditNavAvailability;
  bootstrapNavState();
})();
