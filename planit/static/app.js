// Extras only: every page works without this file.

// The Appearance choice on the Settings page. theme.js applies it on every page.
function setUpTheme() {
  const section = document.querySelector("[data-theme-settings]");
  if (!section) return;
  const root = document.documentElement;
  section.hidden = false;
  section.querySelectorAll('input[name="theme"]').forEach((choice) => {
    choice.checked = choice.value === (root.dataset.theme || "system");
    choice.addEventListener("change", () => {
      try {
        if (choice.value === "system") {
          delete root.dataset.theme;
          localStorage.removeItem("planit-theme");
        } else {
          root.dataset.theme = choice.value;
          localStorage.setItem("planit-theme", choice.value);
        }
      } catch (error) {
        // Storage can be blocked. The theme still changes for this page.
      }
    });
  });
}

// The ☰ button on phones.
function setUpMenu() {
  const button = document.querySelector("[data-menu-button]");
  const menu = document.getElementById(button && button.getAttribute("aria-controls"));
  if (!button || !menu) return;
  button.hidden = false;
  const setOpen = (open) => {
    button.setAttribute("aria-expanded", open);
    menu.classList.toggle("is-open", open);
  };
  button.addEventListener("click", () => setOpen(button.getAttribute("aria-expanded") !== "true"));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") setOpen(false);
  });
}

// <details> menus (the account menu, a card's Move menu) close on an outside click or Escape.
function setUpPopovers() {
  const menus = () => document.querySelectorAll("details[data-popover][open]");
  document.addEventListener("click", (event) => {
    menus().forEach((menu) => {
      if (!menu.contains(event.target)) menu.open = false;
    });
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    menus().forEach((menu) => {
      menu.open = false;
      menu.querySelector("summary").focus();
    });
  });
}

function setUpConfirm() {
  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!confirm(form.dataset.confirm)) event.preventDefault();
    });
  });
}

// A select that saves itself (the role of a person, a filter): no Save button needed.
function setUpAutoSubmit() {
  document.querySelectorAll("[data-auto-submit]").forEach((control) => {
    const button = control.form.querySelector("[data-auto-submit-button]");
    if (button) button.hidden = true;
    control.addEventListener("change", () => control.form.requestSubmit());
  });
}

// The Copy button beside an invite link.
function setUpCopy() {
  document.querySelectorAll("[data-copy]").forEach((button) => {
    const field = document.getElementById(button.dataset.copy);
    button.hidden = false;
    button.addEventListener("click", async () => {
      field.select();
      try {
        await navigator.clipboard.writeText(field.value);
      } catch (error) {
        document.execCommand("copy");
      }
      button.textContent = "Copied";
      setTimeout(() => (button.textContent = "Copy"), 1500);
    });
  });
}

// New Project: the people and Teams choice only shows for a Team project.
function setUpProjectKind() {
  const choices = document.querySelectorAll("[data-kind]");
  const teamOnly = document.querySelector("[data-team-only]");
  if (!choices.length || !teamOnly) return;
  const update = () => {
    teamOnly.hidden = !document.querySelector('[data-kind][value="team"]').checked;
  };
  choices.forEach((choice) => choice.addEventListener("change", update));
  update();
}

// The board: drag a card to another column. Each card says where it may go
// (data-moves, from workflow.allowed_moves); other columns fade while dragging.
// The server checks everything again, and the page reloads to show the truth.
function setUpBoard() {
  const board = document.querySelector("[data-board]");
  if (!board) return;
  const csrf = document.querySelector('input[name="csrf_token"]');
  const message = document.querySelector("[data-move-message]");
  const columns = [...board.querySelectorAll(".column")];
  let dragged = null;

  const show = (text) => {
    message.textContent = text;
    message.hidden = false;
    message.classList.add("flash");
  };
  const clear = () => columns.forEach((column) => column.classList.remove("drop-ok", "drop-no"));

  board.querySelectorAll(".task-card[draggable]").forEach((card) => {
    card.addEventListener("dragstart", (event) => {
      dragged = card;
      card.classList.add("is-dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", card.id);
      const allowed = card.dataset.moves.split(" ");
      columns.forEach((column) => {
        if (column.contains(card)) return;
        column.classList.add(allowed.includes(column.dataset.status) ? "drop-ok" : "drop-no");
      });
    });
    card.addEventListener("dragend", () => {
      card.classList.remove("is-dragging");
      dragged = null;
      clear();
    });
  });

  columns.forEach((column) => {
    column.addEventListener("dragover", (event) => {
      if (dragged && column.classList.contains("drop-ok")) event.preventDefault();
    });
    column.addEventListener("drop", async (event) => {
      event.preventDefault();
      if (!dragged || !column.classList.contains("drop-ok")) return;
      const card = dragged;
      column.querySelector("[data-column-list]").prepend(card);
      clear();
      const body = new FormData();
      body.append("to", column.dataset.status);
      try {
        const response = await fetch(card.dataset.moveUrl, {
          method: "POST",
          body,
          headers: { Accept: "application/json", "X-CSRF-Token": csrf ? csrf.value : "" },
        });
        const answer = await response.json();
        if (!answer.ok) {
          show(answer.message);
          setTimeout(() => window.location.reload(), 1600);
          return;
        }
        window.location.reload();
      } catch (error) {
        show("That didn't save. Please check your connection and try again.");
      }
    });
  });
}

// Keyboard shortcuts: "/" or Ctrl+K (Cmd+K on a Mac) opens Search, "c" makes a new task.
// Letters do nothing while you type in a box. The list is in Settings.
function setUpShortcuts() {
  document.querySelectorAll("[data-js-only]").forEach((part) => (part.hidden = false));
  const openSearch = () => {
    const box = document.querySelector("[data-search-box]");
    const link = document.querySelector("[data-search-link]");
    if (box) {
      box.focus();
      box.select();
    } else if (link) {
      window.location.href = link.href;
    }
  };
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      openSearch();
      return;
    }
    const typing = event.target.closest("input, textarea, select, [contenteditable]");
    if (typing || event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.key === "/") {
      event.preventDefault();
      openSearch();
    } else if (event.key === "c") {
      const link = document.querySelector('[data-shortcut="c"]');
      if (link) {
        event.preventDefault();
        link.click();
      }
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  setUpShortcuts();
  setUpProjectKind();
  setUpBoard();
  setUpTheme();
  setUpMenu();
  setUpPopovers();
  setUpConfirm();
  setUpAutoSubmit();
  setUpCopy();
});
