(() => {
  const file = $('field-file');
  const search = $('field-search');
  const list = $('field-list');
  const key = $('field-key');
  const value = $('field-value');
  const save = $('field-save');
  const status = $('field-status');
  let slot = null;
  let revision = null;
  let fields = {};
  let request = 0;

  function showStatus(message, error = false) {
    status.textContent = message;
    status.classList.toggle('error', error);
  }

  function showFields() {
    const query = search.value.trim().toLowerCase();
    const matching = Object.keys(fields).sort().filter(name => name.toLowerCase().includes(query));
    list.replaceChildren(...matching.map(name => new Option(name, name)));
    list.selectedIndex = -1;
    if (matching.includes(key.value)) list.value = key.value;
  }

  function resetField() {
    revision = null;
    fields = {};
    key.value = '';
    value.value = '';
    showFields();
    save.dataset.permDisabled = 'true';
    value.dataset.permDisabled = 'true';
    updateControls();
  }

  async function readDocuments(targetSlot, name = '') {
    const params = new URLSearchParams({slot: targetSlot, name});
    const response = await fetch('/api/documents?' + params);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error);
    return data;
  }

  async function loadFile(selectedKey = '') {
    const id = ++request;
    resetField();
    if (slot === null || !file.value) return;
    showStatus('Loading fields…');
    try {
      const data = await readDocuments(slot, file.value);
      if (id !== request) return;
      fields = data.fields;
      revision = data.revision;
      key.value = selectedKey;
      value.value = Object.hasOwn(fields, selectedKey) ? fields[selectedKey] : '';
      showFields();
      delete save.dataset.permDisabled;
      delete value.dataset.permDisabled;
      updateControls();
      showStatus('Select a field or enter a new key and JSON value.');
    } catch (error) {
      if (id === request) showStatus(error.message, true);
    }
  }

  async function syncSlot() {
    const nextSlot = currentState?.slot ?? null;
    if (nextSlot === slot && revision) {
      const storedValue = Object.hasOwn(fields, key.value) ? fields[key.value] : '';
      if (value.value === storedValue) await loadFile(key.value);
      return;
    }
    slot = nextSlot;
    const id = ++request;
    resetField();
    file.replaceChildren();
    search.value = '';
    if (slot === null) {
      showStatus('Load a save slot to browse its fields.');
      return;
    }
    try {
      const {files} = await readDocuments(slot);
      if (id !== request) return;
      file.replaceChildren(...files.map(name => new Option(name, name)));
      if (files.length) {
        await loadFile();
      } else {
        showStatus('This slot has no supported save files.');
      }
    } catch (error) {
      if (id === request) showStatus(error.message, true);
    }
  }

  file.addEventListener('change', () => {
    search.value = '';
    loadFile();
  });
  $('field-reload').addEventListener('click', () => loadFile(key.value));
  search.addEventListener('input', showFields);
  list.addEventListener('change', () => {
    key.value = list.value;
    value.value = fields[list.value];
  });
  $('field-editor').addEventListener('submit', async event => {
    event.preventDefault();
    if (!revision || currentState?.slot !== slot) return;
    try {
      JSON.parse(value.value);
    } catch {
      showStatus('Enter valid JSON. Put double quotes around text values.', true);
      return;
    }
    const selectedKey = key.value;
    const saved = await doEdit({
      action: 'set_document_field', name: file.value, key: selectedKey,
      value: value.value, revision,
    });
    const message = $('notice-text').textContent;
    if (saved) await loadFile(selectedKey);
    showStatus(message, !saved);
  });
  document.addEventListener('studio-state', syncSlot);
  syncSlot();
})();
