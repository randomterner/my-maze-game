(() => {
  let translations = {};

  function parseTranslations(text) {
    const result = {};
    text.split(/\r?\n/).forEach(line => {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) return;
      // `=>` is available for phrases that themselves contain `=`.
      const separatorToken = trimmed.includes(" => ") ? " => " : " = ";
      const separator = separatorToken === " => "
        ? trimmed.indexOf(separatorToken)
        : trimmed.lastIndexOf(separatorToken);
      if (separator < 1) return;
      const source = trimmed.slice(0, separator).trim();
      const target = trimmed.slice(separator + separatorToken.length).trim();
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
    const language = window.localStorage.getItem("maze-game-language") === "he" ? "he" : "en";
    try {
      const file = language === "he" ? "translations_he.txt" : "translations.txt";
      const response = await fetch(`/static/${file}?version=${Date.now()}`, { cache: "no-store" });
      if (response.ok) translations = parseTranslations(await response.text());
    } catch (_) {
      translations = {};
    }
    document.documentElement.lang = translations.__language__ || "en";
    document.documentElement.dir = translations.__direction__ || "ltr";
    document.title = window.translateGameText(document.title);
    window.applyGameTranslations();
    addLanguageSwitcher(language);
  }

  function addLanguageSwitcher(language) {
    let button = document.getElementById("languageSwitcher");
    if (!button) {
      button = document.createElement("button");
      button.id = "languageSwitcher";
      button.type = "button";
      button.style.cssText = "position:fixed;top:12px;right:12px;z-index:9999;padding:8px 12px;border:1px solid #65d8ff;border-radius:8px;background:#10233e;color:#fff;font-weight:700;cursor:pointer;";
      document.body.appendChild(button);
    }
    button.textContent = language === "he" ? "English" : "עברית";
    button.onclick = () => {
      window.localStorage.setItem("maze-game-language", language === "he" ? "en" : "he");
      window.location.reload();
    };
    button.textContent = language === "he" ? "English" : "\u05e2\u05d1\u05e8\u05d9\u05ea";
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", loadTranslations, { once: true });
  } else {
    loadTranslations();
  }
})();
