(function () {
  var wizard = document.getElementById('archivebox-setup-wizard');
  if (!wizard) return;

  var baseUrlInput = document.getElementById('archivebox-setup-base-url');
  var securityModeInput = document.getElementById('archivebox-setup-security-mode');
  var publicIndexInput = document.getElementById('archivebox-setup-public-index');
  var publicAddInput = document.getElementById('archivebox-setup-public-add');
  var permissionsInput = document.getElementById('archivebox-setup-permissions');
  var hostingInputs = document.querySelectorAll('input[name="archivebox-hosting-location"]');
  var dnsInputs = document.querySelectorAll('input[name="archivebox-dns-mode"]');
  var tlsInputs = document.querySelectorAll('input[name="archivebox-tls-mode"]');
  var reviewButton = document.getElementById('archivebox-setup-review');
  var validationStatus = document.getElementById('archivebox-setup-validation');
  var probeTimer = null;
  var probeGeneration = 0;
  var currentPreview = null;
  var machineAdminUrl = new URL(wizard.dataset.machineAdminUrl, window.location.origin);
  if (window.location.pathname === machineAdminUrl.pathname && new URLSearchParams(window.location.search).has('BASE_URL')) {
    wizard.remove();
    return;
  }
  publicIndexInput.checked = wizard.dataset.publicIndex === 'true';
  publicAddInput.checked = wizard.dataset.publicAddView === 'true';
  permissionsInput.value = wizard.dataset.permissions || 'public';

  function selectedValue(inputs) {
    var selected = Array.prototype.find.call(inputs, function(input) { return input.checked; });
    return selected ? selected.value : '';
  }

  function selectValue(inputs, value) {
    Array.prototype.forEach.call(inputs, function(input) { input.checked = input.value === value; });
  }

  function initializeQuestionSections() {
    document.querySelectorAll('.abx-question[data-status-id]').forEach(function(question) {
      var status = document.getElementById(question.dataset.statusId);
      var toggle = question.querySelector('.abx-question-toggle');
      var toggleIcon = question.querySelector('.abx-question-toggle-icon');

      function setCollapsed(collapsed) {
        question.classList.toggle('is-collapsed', collapsed);
        toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
        toggleIcon.textContent = collapsed ? '▸' : '▾';
      }

      function syncQuestionState() {
        var statusText = status.textContent.trim();
        var isValid = statusText.indexOf('✅') === 0;
        var isInvalid = statusText.indexOf('❌') === 0;
        question.classList.toggle('is-valid', isValid);
        question.classList.toggle('is-invalid', isInvalid);
        if (isValid) setCollapsed(true);
        if (isInvalid) setCollapsed(false);
      }

      toggle.addEventListener('click', function() {
        setCollapsed(!question.classList.contains('is-collapsed'));
      });
      new MutationObserver(syncQuestionState).observe(status, {childList: true, characterData: true, subtree: true});
      syncQuestionState();
    });
  }

  initializeQuestionSections();

  var detectedUrl = new URL(baseUrlInput.value);
  var detectedLocalhost = detectedUrl.hostname === 'localhost' || detectedUrl.hostname.endsWith('.localhost');
  if (detectedLocalhost) {
    selectValue(hostingInputs, 'localhost');
    selectValue(dnsInputs, 'localhost');
    selectValue(tlsInputs, 'localhost');
    securityModeInput.value = 'auto';
  } else {
    selectValue(dnsInputs, 'single');
    selectValue(tlsInputs, detectedUrl.protocol === 'https:' ? 'single' : 'none');
    securityModeInput.value = 'auto';
  }

  function setPreviewValue(id, value) {
    document.getElementById(id).value = value;
  }

  function updateUrlComparison(configuredUrl, expectedAdminOrigin) {
    var browserUrl = window.location.origin;
    var status = document.getElementById('archivebox-setup-url-match');
    document.getElementById('archivebox-setup-browser-url').textContent = browserUrl;
    document.getElementById('archivebox-setup-configured-url').textContent = configuredUrl;
    if (browserUrl.toLowerCase() === configuredUrl.toLowerCase()) {
      status.className = 'abx-url-comparison-status is-match';
      status.textContent = '✅ Browser URL matches BASE_URL.';
    } else if (expectedAdminOrigin && browserUrl.toLowerCase() === expectedAdminOrigin.toLowerCase()) {
      status.className = 'abx-url-comparison-status is-match';
      status.textContent = '✅ Browser URL matches admin.BASE_URL as expected.';
    } else {
      status.className = 'abx-url-comparison-status is-warning';
      status.textContent = '⚠️ Browser URL does not match BASE_URL' + (expectedAdminOrigin ? ' or its expected admin URL.' : '.');
    }
  }

  function updatePreview() {
    var parsed;
    try {
      parsed = new URL(baseUrlInput.value.trim() || baseUrlInput.placeholder);
      if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') throw new Error('Unsupported URL scheme');
    } catch (error) {
      currentPreview = null;
      updateUrlComparison(baseUrlInput.value.trim() || '(invalid BASE_URL)', '');
      reviewButton.disabled = true;
      validationStatus.textContent = 'Enter a valid http:// or https:// BASE_URL to continue.';
      ['archivebox-preview-admin', 'archivebox-preview-api', 'archivebox-preview-index', 'archivebox-preview-snapshot', 'archivebox-preview-save', 'archivebox-preview-last'].forEach(function(id) { setPreviewValue(id, 'Enter a valid http:// or https:// BASE_URL'); });
      ['archivebox-preview-admin-status', 'archivebox-preview-api-status', 'archivebox-preview-index-status', 'archivebox-preview-snapshot-status', 'archivebox-preview-save-status', 'archivebox-preview-last-status'].forEach(function(id) { document.getElementById(id).textContent = '❌ Invalid BASE_URL'; });
      return;
    }

    var hostname = parsed.hostname.toLowerCase();
    var isLocalhost = hostname === 'localhost' || hostname.endsWith('.localhost');
    var selectedHosting = selectedValue(hostingInputs);
    var selectedDnsMode = selectedValue(dnsInputs);
    var selectedTlsMode = selectedValue(tlsInputs);
    var selectedLocalhost = selectedHosting === 'localhost' && selectedDnsMode === 'localhost' && selectedTlsMode === 'localhost';
    var usesSubdomains = securityModeInput.value === 'safe-subdomains-fullreplay' || (securityModeInput.value === 'auto' && selectedLocalhost);
    var fullJsReplay = usesSubdomains || securityModeInput.value === 'unsafe-onedomain-noadmin' || securityModeInput.value === 'danger-onedomain-fullreplay';
    var controlPlaneEnabled = securityModeInput.value !== 'unsafe-onedomain-noadmin';
    var baseHost = parsed.host;
    var originFor = function(role) { return parsed.protocol + '//' + (usesSubdomains ? role + '.' + baseHost : baseHost); };
    var adminOrigin = originFor('admin');
    var webOrigin = originFor('web');
    var apiOrigin = originFor('api');
    var snapshotOrigin = usesSubdomains ? parsed.protocol + '//snap-456789abcdef.' + baseHost : webOrigin + '/snapshot/0123456789abcdef0123456789abcdef';
    var originalOrigin = webOrigin + '/original/reddit.com';
    var permission = permissionsInput.value;
    var httpsReady = selectedTlsMode === 'wildcard' || selectedTlsMode === 'single' || selectedTlsMode === 'localhost';
    var effectiveMode = document.getElementById('archivebox-setup-effective-mode');

    document.getElementById('archivebox-setup-wildcard-example').textContent = 'https://*.' + parsed.host;
    document.getElementById('archivebox-setup-base-url-example').textContent = parsed.origin;
    updateUrlComparison(parsed.origin, usesSubdomains ? adminOrigin : parsed.origin);

    if (securityModeInput.value === 'auto') {
      effectiveMode.textContent = selectedLocalhost
        ? 'Effective result for this BASE_URL: isolated full replay. Localhost needs no DNS or HTTPS setup.'
        : 'Effective result for this BASE_URL: one-domain replay with archived JavaScript disabled. Only one DNS record is needed; HTTPS unlocks service-worker replay viewers.';
    } else if (securityModeInput.value === 'safe-onedomain-nojsreplay') {
      effectiveMode.textContent = 'Effective result: one-domain replay with archived JavaScript disabled. Only one DNS record is needed; ' + (httpsReady ? 'high-fidelity replay viewers are available.' : 'add HTTPS to enable service-worker replay viewers.');
    } else if (securityModeInput.value === 'safe-subdomains-fullreplay') {
      effectiveMode.textContent = selectedLocalhost
        ? 'Effective result: isolated full replay with no manual DNS or HTTPS setup.'
        : 'Effective result: isolated full replay. Configure wildcard DNS and a wildcard HTTPS certificate for all replay features.';
    } else if (securityModeInput.value === 'unsafe-onedomain-noadmin') {
      effectiveMode.textContent = 'Effective result: full replay on one shared domain, with login, admin, API, submissions, and mutations disabled.';
    } else {
      effectiveMode.textContent = 'Effective result: full replay and privileged UI/API share one domain. Malicious archived JavaScript can compromise the archive and your browser session.';
    }

    setPreviewValue('archivebox-preview-admin', adminOrigin + '/admin/');
    setPreviewValue('archivebox-preview-api', apiOrigin + '/api/v1/docs');
    setPreviewValue('archivebox-preview-index', webOrigin + '/public/');
    setPreviewValue('archivebox-preview-snapshot', snapshotOrigin + '/');
    setPreviewValue('archivebox-preview-save', webOrigin + '/web/https://example.com');
    setPreviewValue('archivebox-preview-last', originalOrigin + '/r/somesubpage');

    var routeSemantics = {
      admin: controlPlaneEnabled ? 'Admin login required' : 'Disabled in this mode',
      api: controlPlaneEnabled ? 'Available; access-controlled' : 'Disabled in this mode',
      index: publicIndexInput.checked ? 'Anonymous index enabled' : 'Sign-in required',
      snapshot: permission === 'private' ? (controlPlaneEnabled ? 'Admin only by default' : 'Private content unavailable') : (permission === 'unlisted' ? 'Anyone with URL' : 'Anonymous and listed'),
      save: controlPlaneEnabled ? (publicAddInput.checked ? 'Anonymous submissions' : 'Admin only') : 'Submissions disabled',
      last: permission === 'private' ? (controlPlaneEnabled ? 'Admin only by default' : 'Private content unavailable') : 'Anonymous direct access',
    };
    document.getElementById('archivebox-preview-admin-status').textContent = '⏳ Testing · ' + routeSemantics.admin;
    document.getElementById('archivebox-preview-api-status').textContent = '⏳ Testing · ' + routeSemantics.api;
    document.getElementById('archivebox-preview-index-status').textContent = '⏳ Testing · ' + routeSemantics.index;
    document.getElementById('archivebox-preview-snapshot-status').textContent = '⏳ Testing host · ' + routeSemantics.snapshot;
    document.getElementById('archivebox-preview-save-status').textContent = '⏳ Testing web host · ' + routeSemantics.save;
    document.getElementById('archivebox-preview-last-status').textContent = '⏳ Testing host · ' + routeSemantics.last;

    document.getElementById('archivebox-preview-dns').textContent = selectedDnsMode === 'localhost'
      ? '✅ No manual DNS setup is needed with localhost.'
      : (selectedDnsMode === 'wildcard' ? '✱ Configure wildcard DNS for the base hostname and all *.hostname subdomains.' : (selectedDnsMode === 'single' ? '🔢 Configure one A/AAAA/CNAME or /etc/hosts entry for the base hostname.' : '❌ Choose a DNS mode.'));
    document.getElementById('archivebox-preview-tls').textContent = selectedTlsMode === 'localhost'
      ? '✅ No HTTPS setup is needed with localhost.'
      : (selectedTlsMode === 'wildcard' ? '✱ Configure a browser-trusted wildcard HTTPS certificate.' : (selectedTlsMode === 'single' ? '🔒 Configure one browser-trusted HTTPS certificate for the base hostname.' : (selectedTlsMode === 'none' ? '⚠️ Direct HTTP selected; in-browser WARC viewing will not work.' : '❌ Choose an ingress and TLS mode.')));
    document.getElementById('archivebox-preview-warc').textContent = httpsReady ? '✅ Available' : '❌ Requires HTTPS (or localhost)';
    document.getElementById('archivebox-preview-js').textContent = fullJsReplay ? (usesSubdomains ? '✅ Available with per-snapshot isolation' : '⚠️ Available on the shared archive origin') : '❌ Archived JavaScript is disabled';

    var risks = [];
    if (usesSubdomains) {
      risks.push('✅ Snapshot replay origins are isolated from the admin UI, API, and other snapshots.');
    } else if (securityModeInput.value === 'unsafe-onedomain-noadmin') {
      risks.push('⚠️ Untrusted archived JavaScript can read any anonymous public or unlisted archive content on the shared origin. Admin UI, API, login, submissions, and all state-changing requests are disabled; private snapshots are unavailable because every visitor is anonymous.');
    } else if (securityModeInput.value === 'danger-onedomain-fullreplay') {
      risks.push('🛑 Malicious archived JavaScript shares an origin with the archive index, every reachable snapshot, saved headers, admin UI, and REST API. It can trivially read sensitive data and use your authenticated browser to change configuration, install or invoke binaries, archive intranet URLs, or delete data. Use only on a disposable isolated server with no secrets or trusted browser session.');
    } else {
      risks.push('⚠️ UI, API, and archive replay share one origin. CSP disables risky archived scripts, but a CSP or content-type bypass could expose the archive index, other snapshots, saved headers, admin pages, API data, and canonical-host mutations.');
    }
    risks.push(publicIndexInput.checked
      ? '⚠️ Anonymous visitors can enumerate public snapshot URLs and titles; saved URLs may contain private share tokens or other secrets.'
      : '✅ Anonymous visitors cannot browse the snapshot index.');
    risks.push(!controlPlaneEnabled
      ? '✅ URL submission and other state-changing requests are disabled for everyone in this replay-only mode.'
      : (publicAddInput.checked ? '⚠️ Anonymous visitors can submit malicious or private/intranet URLs. A filtering or per-crawl configuration bypass could expose internal content or threaten the server.' : '✅ Only signed-in admins can submit new URLs.'));
    risks.push(permission === 'public'
      ? '⚠️ New snapshots are listed and readable anonymously. Replayed pages, metadata, headers, cookies, PII, and API keys captured in an archive may become public.'
      : (permission === 'unlisted' ? '⚠️ New snapshots are hidden from listings but remain readable by anyone who discovers or receives their URL.' : (controlPlaneEnabled ? '✅ New snapshots require an authenticated ArchiveBox admin by default.' : '⚠️ Private snapshots cannot be viewed while the replay-only mode disables authentication.')));
    document.getElementById('archivebox-setup-risks').innerHTML = risks.map(function(risk) { return '<li>' + risk + '</li>'; }).join('');

    currentPreview = {
      parsed: parsed,
      isLocalhost: isLocalhost,
      usesSubdomains: usesSubdomains,
      controlPlaneEnabled: controlPlaneEnabled,
      routeSemantics: routeSemantics,
      adminUrl: adminOrigin + '/admin/login/',
      apiUrl: apiOrigin + '/api/v1/docs',
      indexUrl: webOrigin + '/public/',
      webHealthUrl: webOrigin + '/health/',
      snapshotHealthUrl: (usesSubdomains ? snapshotOrigin : webOrigin) + '/health/',
      originalHealthUrl: webOrigin + '/health/',
      expectedBrowserOrigin: usesSubdomains ? adminOrigin : parsed.origin,
    };
    updateOptionGuidance();
    scheduleAccessChecks();
  }

  function updateOptionGuidance() {
    var hosting = selectedValue(hostingInputs);
    var dnsMode = selectedValue(dnsInputs);
    var tlsMode = selectedValue(tlsInputs);
    var desiredScheme = tlsMode === 'wildcard' || tlsMode === 'single' ? 'https://' : 'http://';
    var exampleBaseHost = currentPreview ? currentPreview.parsed.hostname : 'archivebox.example.com';
    var exampleWildcardHost = '*.' + exampleBaseHost;
    var exampleBaseUrl = desiredScheme + exampleBaseHost;
    var exampleWildcardUrl = desiredScheme + exampleWildcardHost;
    var exampleAdminUrl = desiredScheme + (dnsMode === 'wildcard' ? 'admin.' + exampleBaseHost : exampleBaseHost) + '/admin/';
    var localhostAdminUrl = 'http://admin.archivebox.localhost:8000/admin/';

    document.getElementById('archivebox-setup-hosting-status').textContent = hosting === 'localhost'
      ? '❌ Visit ' + localhostAdminUrl + ' from the same machine to continue setup.'
      : (hosting === 'private'
        ? '❌ Configure a LAN, VPN, Tailscale, or intranet hostname/IP such as ' + exampleBaseHost + ' pointing to this ArchiveBox server. The URL will have the shape ' + exampleBaseUrl + '; visit ' + exampleAdminUrl + ' to continue setup.'
        : (hosting === 'public'
          ? '❌ Point public DNS for a hostname such as ' + exampleBaseHost + ' to this ArchiveBox server or ingress. The URL will have the shape ' + exampleBaseUrl + '; visit ' + exampleAdminUrl + ' to continue setup.'
          : '❌ Choose where this server is hosted. Your choice will not be changed automatically.'));
    document.getElementById('archivebox-setup-dns-status').textContent = dnsMode === 'localhost'
      ? '❌ Visit ' + localhostAdminUrl + ' from the same machine to continue setup. No DNS record is needed.'
      : (dnsMode === 'wildcard'
        ? '❌ Create DNS records for ' + exampleBaseHost + ' and ' + exampleWildcardHost + ' pointing to this ArchiveBox server or ingress. The wildcard URL will have the shape ' + exampleWildcardUrl + '; visit ' + exampleAdminUrl + ' to continue setup.'
        : (dnsMode === 'single'
          ? '❌ Create one A/AAAA/CNAME record or /etc/hosts entry for ' + exampleBaseHost + ' pointing to this ArchiveBox server. The URL will have the shape ' + exampleBaseUrl + '; visit ' + exampleAdminUrl + ' to continue setup.'
          : '❌ Choose a DNS mode. Your choice will not be changed automatically.'));
    document.getElementById('archivebox-setup-tls-status').textContent = tlsMode === 'localhost'
      ? '❌ Visit ' + localhostAdminUrl + ' from this machine to continue setup. No certificate is needed.'
      : (tlsMode === 'wildcard'
        ? '❌ In your ingress provider, proxy to ArchiveBox on port 8000 and configure one browser-trusted certificate covering ' + exampleBaseHost + ' and ' + exampleWildcardHost + ', normally through DNS-01. Never enable on-demand TLS or request individual snapshot certificates. Visit ' + exampleAdminUrl + ' to continue setup.'
        : (tlsMode === 'single'
          ? '❌ In your ingress provider, proxy to ArchiveBox on port 8000 and configure one browser-trusted certificate for ' + exampleBaseHost + '. Visit ' + exampleAdminUrl + ' to continue setup.'
          : (tlsMode === 'none'
            ? '❌ Expose this ArchiveBox server directly over HTTP without a separate ingress or SSL termination service. Visit ' + exampleAdminUrl + ' to continue setup. In-browser WARC viewing will remain disabled unless browsing through localhost or HTTPS.'
            : '❌ Choose an ingress and TLS mode. Your choice will not be changed automatically.')));
    document.getElementById('archivebox-setup-wildcard-help').hidden = dnsMode === 'localhost';
  }

  function probeUrl(url, generation, requireArchiveBoxHealth) {
    var controller = new AbortController();
    var timeout = window.setTimeout(function() { controller.abort(); }, 5000);
    var target = new URL(url);
    target.searchParams.set('archivebox_setup_probe', String(generation));
    return fetch(target.toString(), {
      method: 'GET',
      mode: requireArchiveBoxHealth ? 'cors' : 'no-cors',
      credentials: 'omit',
      cache: 'no-store',
      redirect: 'follow',
      signal: controller.signal,
    }).then(function(response) {
      window.clearTimeout(timeout);
      return requireArchiveBoxHealth
        ? response.ok && response.headers.get('X-ArchiveBox-Health') === 'OK'
        : true;
    }).catch(function() {
      window.clearTimeout(timeout);
      return false;
    });
  }

  function setRouteCheck(id, reachable, semantic, noun) {
    document.getElementById(id).textContent = (reachable ? '✅ ' + noun + ' reachable' : '❌ ' + noun + ' unreachable') + ' · ' + semantic;
  }

  function setValidationState(state, message) {
    reviewButton.disabled = state !== 'success';
    validationStatus.className = state ? 'is-' + state : '';
    validationStatus.textContent = message;
  }

  function setInvalidSetup(message) {
    setValidationState('', message);
    ['archivebox-preview-admin-status', 'archivebox-preview-api-status', 'archivebox-preview-index-status', 'archivebox-preview-snapshot-status', 'archivebox-preview-save-status', 'archivebox-preview-last-status'].forEach(function(id) {
      var status = document.getElementById(id);
      if (status.textContent.indexOf('⏳') === 0) status.textContent = '⏸ Waiting for a matching browser URL and valid setup options';
    });
  }

  function scheduleAccessChecks() {
    window.clearTimeout(probeTimer);
    setValidationState('testing', 'Testing the generated ArchiveBox URLs from this browser…');
    probeTimer = window.setTimeout(runAccessChecks, 450);
  }

  function runAccessChecks() {
    var preview = currentPreview;
    var hosting = selectedValue(hostingInputs);
    var dnsMode = selectedValue(dnsInputs);
    var tlsMode = selectedValue(tlsInputs);
    if (!preview || !hosting || !dnsMode || !tlsMode) {
      setInvalidSetup('Choose hosting, DNS, and HTTPS/ingress options to test this setup.');
      return;
    }
    if (tlsMode === 'single' && dnsMode !== 'single') {
      setInvalidSetup('Single-domain HTTPS is only allowed with Single-domain DNS. Choose Single-domain DNS or use a TLS option that covers the selected DNS mode.');
      return;
    }
    if (hosting === 'public' && tlsMode === 'none') {
      setInvalidSetup('Public servers require HTTPS. Configure a single-domain or wildcard certificate in your ingress provider, then visit the HTTPS admin URL to continue.');
      return;
    }
    if (preview.isLocalhost && hosting !== 'localhost') {
      setInvalidSetup('The detected BASE_URL is local-only, but ' + (hosting === 'private' ? 'Private Server' : 'Public Server') + ' is selected. Finish the selected DNS or ingress setup, then visit the new ArchiveBox admin URL to continue.');
      return;
    }
    if (!preview.isLocalhost && hosting === 'localhost') {
      setInvalidSetup('This page is not open through localhost. Choose the matching hosting option, or visit the intended *.localhost admin URL to continue.');
      return;
    }
    if (preview.isLocalhost && dnsMode !== 'localhost') {
      setInvalidSetup('This page is open through localhost, but ' + (dnsMode === 'wildcard' ? 'wildcard DNS' : 'single-domain DNS') + ' is selected. Finish that DNS setup, then visit the new ArchiveBox admin URL to continue.');
      return;
    }
    if (!preview.isLocalhost && dnsMode === 'localhost') {
      setInvalidSetup('This page is not open through localhost DNS. Choose the matching DNS option, or visit the intended *.localhost admin URL to continue.');
      return;
    }
    if (preview.isLocalhost && tlsMode !== 'localhost') {
      setInvalidSetup('This page is open through localhost, but a separate ingress/TLS mode is selected. Finish that ingress setup, then visit the new ArchiveBox admin URL to continue.');
      return;
    }
    if (!preview.isLocalhost && tlsMode === 'localhost') {
      setInvalidSetup('Localhost ingress mode only works with a .localhost BASE_URL. Choose the ingress/TLS setup used by ' + preview.parsed.hostname + '.');
      return;
    }
    if ((dnsMode === 'wildcard' || dnsMode === 'localhost') !== preview.usesSubdomains) {
      setInvalidSetup('The selected SERVER_SECURITY_MODE does not match the selected DNS mode.');
      return;
    }
    if ((tlsMode === 'wildcard' || tlsMode === 'single') && preview.parsed.protocol !== 'https:') {
      setInvalidSetup('The selected HTTPS mode requires an https:// BASE_URL.');
      return;
    }
    if (tlsMode === 'none' && preview.parsed.protocol !== 'http:') {
      setInvalidSetup('Direct access without separate ingress / SSL termination requires an http:// BASE_URL.');
      return;
    }
    var expectedAdminUrl = preview.expectedBrowserOrigin + '/admin/';
    if (window.location.origin.toLowerCase() !== preview.expectedBrowserOrigin.toLowerCase()) {
      setInvalidSetup('This wizard is open at ' + window.location.origin + ', but these settings are available at ' + preview.expectedBrowserOrigin + '. Finish the selected DNS, ingress, and TLS setup, then visit ' + expectedAdminUrl + ' to continue.');
      return;
    }

    updateOptionGuidance();
    var dnsGuidance = document.getElementById('archivebox-setup-dns-status').textContent;
    var tlsGuidance = document.getElementById('archivebox-setup-tls-status').textContent;
    document.getElementById('archivebox-setup-hosting-status').textContent = '✅ Current browser URL matches this hosting choice.';
    document.getElementById('archivebox-setup-dns-status').textContent = dnsGuidance;
    document.getElementById('archivebox-setup-tls-status').textContent = tlsGuidance;

    var generation = ++probeGeneration;
    var checks = {
      admin: probeUrl(preview.adminUrl, generation),
      api: probeUrl(preview.apiUrl, generation),
      index: probeUrl(preview.indexUrl, generation),
      web: probeUrl(preview.webHealthUrl, generation, true),
      snapshot: probeUrl(preview.snapshotHealthUrl, generation, true),
      original: probeUrl(preview.originalHealthUrl, generation, true),
    };
    Promise.all(Object.keys(checks).map(function(key) { return checks[key].then(function(ok) { return [key, ok]; }); })).then(function(entries) {
      if (generation !== probeGeneration || preview !== currentPreview) return;
      var results = {};
      entries.forEach(function(entry) { results[entry[0]] = entry[1]; });
      setRouteCheck('archivebox-preview-admin-status', results.admin, preview.routeSemantics.admin, 'Admin URL');
      setRouteCheck('archivebox-preview-api-status', results.api, preview.routeSemantics.api, 'API URL');
      setRouteCheck('archivebox-preview-index-status', results.index, preview.routeSemantics.index, 'Public index');
      setRouteCheck('archivebox-preview-snapshot-status', results.snapshot, preview.routeSemantics.snapshot, 'Snapshot host');
      setRouteCheck('archivebox-preview-save-status', results.web, preview.routeSemantics.save, 'Web host');
      setRouteCheck('archivebox-preview-last-status', results.original, preview.routeSemantics.last, 'Last-save host');

      var coreReachable = results.admin && results.api && results.index && results.web && results.snapshot;
      document.getElementById('archivebox-setup-dns-status').textContent = coreReachable
        ? '✅ Browser requests reached the configured ' + (dnsMode === 'wildcard' || dnsMode === 'localhost' ? 'role and snapshot subdomains.' : 'single ArchiveBox hostname.')
        : dnsGuidance + ' One or more configured ArchiveBox hosts are still unreachable.';
      if (tlsMode === 'wildcard' || tlsMode === 'single') {
        document.getElementById('archivebox-setup-tls-status').textContent = coreReachable
          ? '✅ Browser-trusted HTTPS reached every configured ArchiveBox URL.'
          : tlsGuidance + ' HTTPS is still unreachable for one or more configured ArchiveBox URLs.';
      } else {
        document.getElementById('archivebox-setup-tls-status').textContent = coreReachable ? '✅ Direct HTTP access reached every configured ArchiveBox URL.' : tlsGuidance + ' Direct HTTP access is still unreachable.';
      }
      if (!coreReachable) {
        setInvalidSetup('Setup is not reachable yet. Fix the failed URLs above and retry the access checks.');
        return;
      }

      setValidationState('success', results.original
        ? '✅ Required ArchiveBox URLs are reachable. Review and save these settings.'
        : '✅ Core ArchiveBox URLs are reachable. The optional last-save domain shortcut did not respond; review its warning before saving.');
    });
  }

  [publicIndexInput, publicAddInput, permissionsInput].forEach(function(input) {
    input.addEventListener('input', updatePreview);
  });
  baseUrlInput.addEventListener('input', updatePreview);
  securityModeInput.addEventListener('change', updatePreview);
  [hostingInputs, dnsInputs, tlsInputs].forEach(function(inputs) {
    Array.prototype.forEach.call(inputs, function(input) { input.addEventListener('change', updatePreview); });
  });
  document.getElementById('archivebox-setup-retry').addEventListener('click', function() { scheduleAccessChecks(); });
  document.getElementById('archivebox-setup-wildcard-help').hidden = detectedLocalhost;
  updatePreview();
  document.getElementById('archivebox-setup-review').addEventListener('click', function () {
    if (reviewButton.disabled) return;
    machineAdminUrl.searchParams.set('BASE_URL', baseUrlInput.value.trim());
    machineAdminUrl.searchParams.set('SERVER_SECURITY_MODE', securityModeInput.value);
    machineAdminUrl.searchParams.set('PUBLIC_INDEX', publicIndexInput.checked ? 'True' : 'False');
    machineAdminUrl.searchParams.set('PUBLIC_ADD_VIEW', publicAddInput.checked ? 'True' : 'False');
    machineAdminUrl.searchParams.set('PERMISSIONS', permissionsInput.value);
    machineAdminUrl.hash = 'BASE_URL';
    window.location.assign(machineAdminUrl.pathname + machineAdminUrl.search + machineAdminUrl.hash);
  });
})();
