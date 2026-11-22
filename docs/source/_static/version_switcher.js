/* Version switcher & left-sidebar "Other versions" navigation (#296).
 *
 * The site root / (and /stable/) serves the latest final release; pinned releases live under /<version>/ and the
 * development branch under /dev/. Switching versions opens the equivalent page in the chosen version when it exists
 * there, or falls back to that version's start page when the page is missing. Without versions.json (for example in a
 * local single-version build) both controls stay hidden.
 */
(function (root) {
  'use strict';

  var VERSION_SUBDIR_RE = /^(?:dev|stable|[0-9]+\.[0-9]+\.[0-9]+(?:(?:a|b|rc)[0-9]+)?)\/$/;

  /** Whether a trailing directory segment ("dev/", "stable/", "3.6.0/") is a version subdirectory. */
  function isVersionSubdir(segment) {
    return VERSION_SUBDIR_RE.test(segment || '');
  }

  /** Site root URL for a Sphinx build whose root is buildRoot (works at /, /stable/, /<version>/, /dev/, or a subpath). */
  function siteRootOf(buildRoot) {
    var parsed = new URL(buildRoot);
    var match = parsed.pathname.match(/([^/]+\/)$/);
    if (match && isVersionSubdir(match[1])) {
      parsed.pathname = parsed.pathname.slice(0, parsed.pathname.length - match[1].length);
      return parsed.href;
    }
    return buildRoot;
  }

  /** Path of the current page below the build root, e.g. "guides/features.html" or "" for the start page. */
  function pageOf(pathname, buildRootPath) {
    var rel = pathname.indexOf(buildRootPath) === 0 ? pathname.slice(buildRootPath.length) : '';
    return rel === 'index.html' ? '' : rel;
  }

  /** Active entry in versions.json for pathBelowSiteRoot (recognises both "" root and "stable/" as stable). */
  function currentEntry(entries, pathBelowSiteRoot) {
    if (pathBelowSiteRoot.indexOf('stable/') === 0) {
      var stableAlias = entries.filter(function (e) { return e.version === 'stable'; })[0];
      if (stableAlias) { return stableAlias; }
    }
    var best = null;
    entries.forEach(function (entry) {
      if (entry.path && pathBelowSiteRoot.indexOf(entry.path) === 0 && (!best || entry.path.length > best.path.length)) {
        best = entry;
      }
    });
    return best || entries.filter(function (entry) { return !entry.path; })[0] || entries[0] || null;
  }

  function targetUrl(siteRoot, entry, page) {
    return siteRoot + entry.path + (page || '');
  }

  /** URL probed with HEAD to check whether page exists in entry (avoids root /dev/ redirect stubs on stable). */
  function probeUrl(siteRoot, entry, page) {
    var prefix = entry.version === 'stable' && !entry.path ? 'stable/' : entry.path;
    return siteRoot + prefix + (page || '');
  }

  /** Navigate to the equivalent page in entry if it exists (HTTP HEAD 2xx), otherwise to entry's home page. */
  function navigateToEntry(siteRoot, entry, page, fetchImpl, assignUrl) {
    var home = targetUrl(siteRoot, entry, '');
    if (!page) {
      assignUrl(home);
      return Promise.resolve(home);
    }
    var candidate = targetUrl(siteRoot, entry, page);
    return fetchImpl(probeUrl(siteRoot, entry, page), { method: 'HEAD' }).then(function (response) {
      var chosen = response && response.ok ? candidate : home;
      assignUrl(chosen);
      return chosen;
    }, function () {
      assignUrl(home);
      return home;
    });
  }

  function populateSidebar(listEl, containerEl, entries, current, siteRoot, page, fetchImpl, assignUrl) {
    if (!listEl || !containerEl) { return; }
    listEl.innerHTML = '';
    entries.forEach(function (entry) {
      var isCurrent = Boolean(current && entry.version === current.version);
      var li = listEl.ownerDocument.createElement('li');
      li.className = isCurrent ? 'toctree-l1 current' : 'toctree-l1';
      var link = listEl.ownerDocument.createElement('a');
      link.className = isCurrent ? 'reference internal current' : 'reference internal';
      link.href = targetUrl(siteRoot, entry, page);
      if (isCurrent) {
        link.setAttribute('aria-current', 'page');
        link.textContent = entry.name + ' (current)';
      } else {
        link.textContent = entry.name;
      }
      link.addEventListener('click', function (ev) {
        if (ev.defaultPrevented || ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) {
          return;
        }
        ev.preventDefault();
        navigateToEntry(siteRoot, entry, page, fetchImpl, assignUrl);
      });
      li.appendChild(link);
      listEl.appendChild(li);
    });
    containerEl.hidden = false;
  }

  function init() {
    var select = document.getElementById('citylearn-version-select');
    var sidebarBox = document.getElementById('citylearn-sidebar-versions');
    var sidebarList = document.getElementById('citylearn-version-list');
    var script = document.currentScript || document.querySelector('script[src*="version_switcher.js"]');
    if (!select || !script || !root.fetch) { return; }

    var buildRoot = new URL(script.src.replace(/_static\/version_switcher\.js.*$/, ''), location.href).href;
    var siteRoot = siteRootOf(buildRoot);
    var page = pageOf(location.pathname, new URL(buildRoot).pathname);
    var assignUrl = function (url) { location.href = url; };
    var fetchImpl = function (url, opts) { return root.fetch(url, opts); };

    fetchImpl(siteRoot + 'versions.json').then(function (response) {
      return response.ok ? response.json() : Promise.reject(response.status);
    }).then(function (entries) {
      var relBelowRoot = location.pathname.slice(new URL(siteRoot).pathname.length);
      var current = currentEntry(entries, relBelowRoot);
      entries.forEach(function (entry) {
        var option = document.createElement('option');
        option.value = entry.version;
        option.textContent = entry.name;
        option.selected = Boolean(current && entry.version === current.version);
        select.appendChild(option);
      });
      select.addEventListener('change', function () {
        var chosen = entries.filter(function (e) { return e.version === select.value; })[0];
        if (chosen) {
          navigateToEntry(siteRoot, chosen, page, fetchImpl, assignUrl);
        }
      });
      select.parentNode.hidden = false;
      populateSidebar(sidebarList, sidebarBox, entries, current, siteRoot, page, fetchImpl, assignUrl);
    }).catch(function () { /* no versions.json: keep the switcher and sidebar section hidden */ });
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
      isVersionSubdir: isVersionSubdir,
      siteRootOf: siteRootOf,
      pageOf: pageOf,
      currentEntry: currentEntry,
      targetUrl: targetUrl,
      probeUrl: probeUrl,
      navigateToEntry: navigateToEntry,
      populateSidebar: populateSidebar
    };
  } else {
    init();
  }
})(typeof window !== 'undefined' ? window : this);
