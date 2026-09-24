/* ==========================================================================
   PORTAL INTRANET MQ PROFESSIONAL - INTERACTION & UI ENGINE
   ========================================================================== */

document.addEventListener("DOMContentLoaded", function () {
  // 1. Notifications Popover Toggle
  const notifBtn = document.getElementById("header-notif-btn");
  const notifFlyout = document.getElementById("notifications-popover");
  if (notifBtn && notifFlyout) {
    notifBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      closeAllPopovers(notifFlyout);
      notifFlyout.classList.toggle("open");
    });
  }

  // 2. Profile Menu Popover Toggle
  const profileTrigger = document.getElementById("header-user-trigger");
  const profileFlyout = document.getElementById("profile-menu-popover");
  if (profileTrigger && profileFlyout) {
    profileTrigger.addEventListener("click", function (e) {
      e.stopPropagation();
      closeAllPopovers(profileFlyout);
      profileFlyout.classList.toggle("open");
      profileTrigger.classList.toggle("open");
    });
  }

  // 3. Close popovers on click outside
  document.addEventListener("click", function () {
    closeAllPopovers();
  });

  function closeAllPopovers(except = null) {
    if (notifFlyout && except !== notifFlyout) notifFlyout.classList.remove("open");
    if (profileFlyout && except !== profileFlyout) profileFlyout.classList.remove("open");
    if (profileTrigger && except !== profileFlyout) profileTrigger.classList.remove("open");
  }

  // 4. Sidebar Collapse Toggle
  const sidebarToggle = document.getElementById("sidebar-toggle-btn");
  const sidebar = document.querySelector(".app-sidebar");
  if (sidebarToggle && sidebar) {
    sidebarToggle.addEventListener("click", function () {
      if (window.innerWidth <= 768) {
        sidebar.classList.toggle("mobile-open");
      } else {
        sidebar.classList.toggle("collapsed");
      }
    });
  }

  // 5. Expandable Sidebar Categories (e.g. Marketing, Regionais)
  document.querySelectorAll(".nav-category-header").forEach(function (header) {
    header.addEventListener("click", function () {
      const parent = header.closest(".nav-category-group");
      if (parent) {
        parent.classList.toggle("expanded");
      }
    });
  });

  // 6. Mini Calendar Engine (Home Page)
  initMiniCalendar();

  // 7. Global Search Filter on Home
  const homeSearch = document.getElementById("home-global-search");
  if (homeSearch) {
    homeSearch.addEventListener("input", function (e) {
      const q = e.target.value.toLowerCase().trim();
      document.querySelectorAll(".report-card, .ferramenta-card").forEach(function (card) {
        const text = card.textContent.toLowerCase();
        card.style.display = text.includes(q) ? "" : "none";
      });
    });
  }
});

function initMiniCalendar() {
  const container = document.getElementById("calendar-days-grid");
  if (!container) return;

  const monthNames = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"];
  const now = new Date();
  let currentYear = now.getFullYear();
  let currentMonth = now.getMonth();

  function renderCalendar(year, month) {
    const titleEl = document.getElementById("calendar-month-title");
    if (titleEl) {
      titleEl.textContent = `${monthNames[month]} ${year}`;
    }

    container.innerHTML = "";

    const daysOfWeek = ["DOM", "SEG", "TER", "QUA", "QUI", "SEX", "SAB"];
    daysOfWeek.forEach(d => {
      const th = document.createElement("div");
      th.className = "calendar-day-header";
      th.textContent = d;
      container.appendChild(th);
    });

    const firstDay = new Date(year, month, 1).getDay();
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const prevMonthDays = new Date(year, month, 0).getDate();

    for (let i = firstDay - 1; i >= 0; i--) {
      const cell = document.createElement("div");
      cell.className = "calendar-day-cell pad-day";
      cell.textContent = prevMonthDays - i;
      container.appendChild(cell);
    }

    const today = new Date();
    for (let d = 1; d <= daysInMonth; d++) {
      const cell = document.createElement("div");
      cell.className = "calendar-day-cell";
      cell.textContent = d;

      if (d === today.getDate() && month === today.getMonth() && year === today.getFullYear()) {
        cell.classList.add("today");
      }

      if (d === 12 || d === 14 || d === 16 || d === 25) {
        cell.classList.add("has-event");
      }

      container.appendChild(cell);
    }
  }

  const prevBtn = document.getElementById("btn-cal-prev");
  const nextBtn = document.getElementById("btn-cal-next");

  if (prevBtn) {
    prevBtn.addEventListener("click", () => {
      currentMonth--;
      if (currentMonth < 0) {
        currentMonth = 11;
        currentYear--;
      }
      renderCalendar(currentYear, currentMonth);
    });
  }

  if (nextBtn) {
    nextBtn.addEventListener("click", () => {
      currentMonth++;
      if (currentMonth > 11) {
        currentMonth = 0;
        currentYear++;
      }
      renderCalendar(currentYear, currentMonth);
    });
  }

  renderCalendar(currentYear, currentMonth);
}

function showToast(message) {
  let toast = document.getElementById("app-toast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "app-toast";
    toast.className = "toast-notification";
    document.body.appendChild(toast);
  }
  toast.textContent = message;
  toast.classList.add("visible");
  setTimeout(() => {
    toast.classList.remove("visible");
  }, 4000);
}
