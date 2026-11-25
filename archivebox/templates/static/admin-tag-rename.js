(() => {
    "use strict";

    function setError(cell, message) {
        const input = cell.querySelector(".tag-inline-input");
        const error = cell.querySelector(".tag-inline-error");
        error.textContent = message;
        error.hidden = !message;
        if (message) input.setAttribute("aria-invalid", "true");
        else input.removeAttribute("aria-invalid");
    }

    function setEditing(cell, editing) {
        const field = cell.querySelector("[data-tag-rename-field]") || cell.querySelector(".tag-inline-input");
        const label = cell.querySelector(".tag-inline-name");
        const original = field.matches("[data-tag-rename-field]") ? label.closest(".library-link") : label;
        const pencil = cell.querySelector(".tag-inline-pencil");
        field.hidden = !editing;
        original.hidden = editing;
        if (pencil) pencil.hidden = editing;
    }

    function finish(cell) {
        setError(cell, "");
        setEditing(cell, false);
        cell.querySelector(".tag-inline-pencil, .folder-menu-toggle")?.focus();
    }

    function start(cell) {
        const name = cell.querySelector(".tag-inline-name");
        const input = cell.querySelector(".tag-inline-input");
        input.value = name.textContent;
        setError(cell, "");
        setEditing(cell, true);
        input.focus();
        input.select();
    }

    document.addEventListener("click", (event) => {
        const pencil = event.target.closest(".tag-inline-pencil");
        if (pencil) start(pencil.closest("[data-tag-rename-url]"));
    });
    document.addEventListener("archivebox:tag-rename", (event) => {
        const cell = event.target.closest("[data-tag-rename-url]");
        if (cell) start(cell);
    });

    document.addEventListener("keydown", async (event) => {
        const input = event.target.closest(".tag-inline-input");
        const cell = input?.closest("[data-tag-rename-url]");
        if (!cell || event.isComposing || !["Enter", "Escape"].includes(event.key)) return;
        event.preventDefault();
        event.stopPropagation();
        if (input.readOnly) return;
        if (event.key === "Escape") {
            finish(cell);
            return;
        }
        const name = input.value.trim();
        if (!name) {
            setError(cell, "Tag name is required.");
            return;
        }
        setError(cell, "");
        input.readOnly = true;
        input.setAttribute("aria-busy", "true");
        try {
            const csrfField = input.closest("form")?.querySelector('[name="csrfmiddlewaretoken"]')
                || document.querySelector('#changelist-form [name="csrfmiddlewaretoken"]');
            const csrf = csrfField?.value;
            const response = await fetch(cell.dataset.tagRenameUrl, {
                method: "POST",
                credentials: "same-origin",
                headers: { "X-CSRFToken": csrf || "", Accept: "application/json" },
                body: new URLSearchParams({ name }),
            });
            const result = await response.json().catch(() => null);
            if (!response.ok || typeof result?.name !== "string") {
                throw new Error(result?.error || "Could not rename tag.");
            }
            const label = cell.querySelector(".tag-inline-name");
            label.textContent = result.name;
            cell.querySelector(".tag-inline-pencil")?.setAttribute("aria-label", "Rename tag " + result.name);
            if (cell.matches(".library-entry")) {
                cell.dataset.name = result.name;
                const trigger = cell.querySelector(".folder-menu-toggle");
                trigger.setAttribute("aria-label", "Actions for " + result.name);
                trigger.title = "Actions for " + result.name;
                const link = label.closest(".library-link");
                window.applyArchiveBoxTagColor(link, result.name);
                window.applyArchiveBoxTagColor(cell.querySelector("[data-tag-rename-field]"), result.name);
            }
            finish(cell);
        } catch (error) {
            setError(cell, error.message || "Could not rename tag.");
            input.focus();
        } finally {
            input.readOnly = false;
            input.removeAttribute("aria-busy");
        }
    });
})();
