"use strict";

document.addEventListener("DOMContentLoaded", () => {
  const sidebar = document.getElementById("sidebar");
  const overlay = document.getElementById("sidebar-overlay");
  const toggle = document.getElementById("sidebar-toggle");

  const closeSidebar = () => {
    if (!sidebar || !overlay || !toggle) return;
    sidebar.classList.add("-translate-x-full");
    overlay.classList.add("hidden");
    toggle.setAttribute("aria-expanded", "false");
  };

  if (sidebar && overlay && toggle) {
    toggle.addEventListener("click", () => {
      const opening = sidebar.classList.contains("-translate-x-full");
      sidebar.classList.toggle("-translate-x-full", !opening);
      overlay.classList.toggle("hidden", !opening);
      toggle.setAttribute("aria-expanded", String(opening));
    });
    overlay.addEventListener("click", closeSidebar);
  }

  document.querySelectorAll(".toast-close").forEach((button) => {
    button.addEventListener("click", () => button.closest(".toast")?.remove());
  });

  document.querySelectorAll(".confirm-action").forEach((button) => {
    button.addEventListener("click", (event) => {
      const message = button.dataset.confirm || "Continue with this action?";
      if (!window.confirm(message)) event.preventDefault();
    });
  });

  document.getElementById("print-receipt")?.addEventListener("click", () => window.print());
});
