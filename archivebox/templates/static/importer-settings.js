const personaPicker = document.querySelector('.importers select[name="persona"]');
const importerSettingsLinks = document.querySelectorAll('.importers [data-persona-fragment]');
if (personaPicker && importerSettingsLinks.length) {
    function updateImporterSettingsLinks() {
        const personaUrl = personaPicker.selectedOptions[0]?.dataset.settingsUrl;
        importerSettingsLinks.forEach(link => {
            link.href = personaUrl ? personaUrl + link.dataset.personaFragment : link.dataset.machineUrl;
        });
    }
    personaPicker.addEventListener('change', updateImporterSettingsLinks);
    updateImporterSettingsLinks();
}
