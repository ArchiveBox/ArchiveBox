// Carry the original File objects across navigation so /add/ owns all reading,
// preview, validation, and submission. Each tab consumes its handoff once.
window.archiveboxAddInput = {
    async transfer(input) {
        const key = 'archivebox.add.pending-input';
        const previousId = sessionStorage.getItem(key);
        // getRandomValues also works on self-hosted HTTP origins.
        const id = input ? Array.from(crypto.getRandomValues(new Uint32Array(4))).join('-') : previousId;
        if (!id) return null;
        const db = await new Promise((resolve, reject) => {
            const request = indexedDB.open('archivebox-add-input', 1);
            request.onupgradeneeded = () => request.result.createObjectStore('inputs');
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
        });
        try {
            const result = await new Promise((resolve, reject) => {
                const transaction = db.transaction('inputs', 'readwrite');
                const store = transaction.objectStore('inputs');
                if (input && previousId) store.delete(previousId);
                const request = input ? store.put(input, id) : store.get(id);
                if (!input) store.delete(id);
                transaction.oncomplete = () => resolve(request.result);
                transaction.onabort = () => reject(transaction.error);
                transaction.onerror = () => reject(transaction.error);
            });
            if (input) sessionStorage.setItem(key, id);
            else sessionStorage.removeItem(key);
            return result;
        } finally {
            db.close();
        }
    },
};
