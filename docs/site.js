(() => {
  const root = document.documentElement;
  const themeToggle = document.querySelector("[data-theme-toggle]");
  const menuToggle = document.querySelector("[data-menu-toggle]");
  const sidebar = document.querySelector("[data-sidebar]");
  const viewButtons = [...document.querySelectorAll("[data-view]")];
  const viewPanels = [...document.querySelectorAll("[data-view-panel]")];
  const sectionLinks = [...document.querySelectorAll('.sidebar a[href^="#"]')];
  const sections = sectionLinks
    .map((link) => document.querySelector(link.getAttribute("href")))
    .filter(Boolean);

  const storedTheme = localStorage.getItem("design-docs-theme");
  const preferredTheme = window.matchMedia("(prefers-color-scheme: light)").matches
    ? "light"
    : "dark";
  root.dataset.theme = storedTheme || preferredTheme;

  themeToggle?.addEventListener("click", () => {
    const next = root.dataset.theme === "dark" ? "light" : "dark";
    root.dataset.theme = next;
    localStorage.setItem("design-docs-theme", next);
    themeToggle.setAttribute("aria-label", `Switch to ${next === "dark" ? "light" : "dark"} theme`);
  });

  const showView = (name) => {
    viewButtons.forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.view === name));
    });
    viewPanels.forEach((panel) => {
      const active = panel.dataset.viewPanel === name;
      panel.hidden = !active;
      panel.classList.toggle("is-active", active);
    });
  };

  viewButtons.forEach((button) => {
    button.addEventListener("click", () => showView(button.dataset.view));
  });

  menuToggle?.addEventListener("click", () => {
    const open = sidebar?.classList.toggle("is-open") ?? false;
    menuToggle.setAttribute("aria-expanded", String(open));
    menuToggle.setAttribute("aria-label", open ? "Close navigation" : "Open navigation");
  });

  sectionLinks.forEach((link) => {
    link.addEventListener("click", () => {
      sidebar?.classList.remove("is-open");
      menuToggle?.setAttribute("aria-expanded", "false");
    });
  });

  const markActive = (id) => {
    sectionLinks.forEach((link) => {
      link.classList.toggle("is-active", link.getAttribute("href") === `#${id}`);
    });
  };

  const observer = new IntersectionObserver(
    (entries) => {
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio);
      if (visible[0]) markActive(visible[0].target.id);
    },
    { rootMargin: "-18% 0px -68% 0px", threshold: [0, 0.15, 0.35] },
  );

  sections.forEach((section) => observer.observe(section));
  markActive(window.location.hash.slice(1) || "overview");
})();
