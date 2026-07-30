(() => {
  let translations = {};

  function parseTranslations(text) {
    const result = {};
    text.split(/\r?\n/).forEach(line => {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) return;
      // Use the final spaced equals sign as the divider. This lets a source
      // phrase itself contain "=" (for example, a legend entry).
      const separator = trimmed.lastIndexOf(" = ");
      if (separator < 1) return;
      const source = trimmed.slice(0, separator).trim();
      const target = trimmed.slice(separator + 3).trim();
      if (source && target) result[source] = target;
    });
    return result;
  }

  window.translateGameText = value => {
    let result = String(value ?? "");
    Object.keys(translations)
      .filter(key => !key.startsWith("__"))
      .sort((a, b) => b.length - a.length)
      .forEach(source => {
        const escaped = source.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        const beginsWithWord = /^[A-Za-z0-9_]/.test(source);
        const endsWithWord = /[A-Za-z0-9_]$/.test(source);
        const pattern = `${beginsWithWord ? "\\b" : ""}${escaped}${endsWithWord ? "\\b" : ""}`;
        result = result.replace(new RegExp(pattern, "g"), translations[source]);
      });
    return result;
  };

  window.applyGameTranslations = (root = document.body) => {
    if (!root) return;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(node => {
      const parent = node.parentElement;
      if (parent?.closest("script, style, textarea")) return;
      node.nodeValue = window.translateGameText(node.nodeValue);
    });
    root.querySelectorAll("[placeholder], [title], [aria-label], [alt]").forEach(element => {
      ["placeholder", "title", "aria-label", "alt"].forEach(attribute => {
        if (element.hasAttribute(attribute)) {
          element.setAttribute(attribute, window.translateGameText(element.getAttribute(attribute)));
        }
      });
    });
  };

  async function loadTranslations() {
    try {
      const response = await fetch(`/static/translations.txt?version=${Date.now()}`, { cache: "no-store" });
      if (response.ok) translations = parseTranslations(await response.text());
    } catch (_) {
      translations = {};
    }
    document.documentElement.lang = translations.__language__ || "en";
    document.documentElement.dir = translations.__direction__ || "ltr";
    document.title = window.translateGameText(document.title);
    window.applyGameTranslations();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", loadTranslations, { once: true });
  } else {
    loadTranslations();
  }
})();
