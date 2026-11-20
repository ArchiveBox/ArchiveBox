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

    function finish(cell) {
        const pencil = cell.querySelector(".tag-inline-pencil");
        setError(cell, "");
        cell.querySelector(".tag-inline-input").hidden = true;
        cell.querySelector(".tag-inline-name").hidden = false;
        pencil.hidden = false;
        pencil.focus();
    }

    document.addEventListener("click", (event) => {
        const pencil = event.target.closest(".tag-inline-pencil");
        if (!pencil) return;
        const cell = pencil.closest("[data-tag-rename-url]");
        const name = cell.querySelector(".tag-inline-name");
        const input = cell.querySelector(".tag-inline-input");
        input.value = name.textContent;
        setError(cell, "");
        pencil.hidden = true;
        name.hidden = true;
        input.hidden = false;
        input.focus();
        input.select();
    });

    document.addEventListener("keydown", async (event) => {
        const input = event.target.closest(".tag-inline-input");
        if (!input || event.isComposing || !["Enter", "Escape"].includes(event.key)) return;
        event.preventDefault();
        event.stopPropagation();
        const cell = input.closest("[data-tag-rename-url]");
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
            const csrf = input.closest("form")?.querySelector('[name="csrfmiddlewaretoken"]')?.value;
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
            cell.querySelector(".tag-inline-name").textContent = result.name;
            cell.querySelector(".tag-inline-pencil").setAttribute("aria-label", "Rename tag " + result.name);
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
