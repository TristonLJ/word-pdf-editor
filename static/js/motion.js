(function () {
  "use strict";

  var reduceMotion =
    window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---------- Scroll reveal (static, server-rendered lists only) ----------

  var revealTargets = document.querySelectorAll(".action-card, .tool-card, .doc-row");

  function revealEl(el) {
    if (el.classList.contains("revealed")) return;
    var siblings = el.parentElement ? Array.prototype.slice.call(el.parentElement.children) : [];
    var idx = siblings.indexOf(el);
    el.style.transitionDelay = Math.min(Math.max(idx, 0), 8) * 35 + "ms";
    el.classList.add("revealed");
  }

  if (reduceMotion || typeof IntersectionObserver === "undefined") {
    revealTargets.forEach(revealEl);
  } else {
    var observer = new IntersectionObserver(
      function (entries, obs) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          revealEl(entry.target);
          obs.unobserve(entry.target);
        });
      },
      { threshold: 0.05, rootMargin: "0px 0px -30px 0px" }
    );
    revealTargets.forEach(function (el) {
      observer.observe(el);
    });

    // Safety net: some environments (backgrounded/automated tabs) never fire
    // IntersectionObserver callbacks. Never leave content permanently invisible -
    // periodically sweep for anything already in view and reveal it directly.
    var sweepInterval = setInterval(function () {
      var remaining = false;
      revealTargets.forEach(function (el) {
        if (el.classList.contains("revealed")) return;
        var rect = el.getBoundingClientRect();
        if (rect.top < window.innerHeight && rect.bottom > 0) {
          revealEl(el);
        } else {
          remaining = true;
        }
      });
      if (!remaining) clearInterval(sweepInterval);
    }, 500);
  }

  // ---------- Busy button state for native (non-AJAX) form submits ----------

  document.addEventListener("submit", function (evt) {
    if (evt.defaultPrevented) return;
    var form = evt.target;
    var btn = form.querySelector('button[type="submit"].btn-primary');
    if (!btn || btn.disabled) return;

    var original = btn.innerHTML;
    btn.dataset.originalLabel = original;
    btn.disabled = true;
    btn.innerHTML = '<svg class="icon icon-spin"><use href="#icon-refresh"/></svg> Processing…';
  });

  // ---------- PDF Tools hub rail scrollspy ----------

  var hubRail = document.getElementById("hub-rail");
  if (hubRail) {
    var railLinks = Array.prototype.slice.call(hubRail.querySelectorAll("a[data-rail-link]"));
    var railSections = railLinks
      .map(function (link) {
        return document.getElementById(link.dataset.railLink);
      })
      .filter(Boolean);

    var setActiveRailLink = function () {
      var activeId = null;
      var bestTop = -Infinity;
      railSections.forEach(function (section) {
        var top = section.getBoundingClientRect().top;
        if (top - 90 <= 0 && top > bestTop) {
          bestTop = top;
          activeId = section.id;
        }
      });
      if (!activeId && railSections.length) activeId = railSections[0].id;
      railLinks.forEach(function (link) {
        link.classList.toggle("active", link.dataset.railLink === activeId);
      });
    };

    railLinks.forEach(function (link) {
      link.addEventListener("click", function (evt) {
        evt.preventDefault();
        var target = document.getElementById(link.dataset.railLink);
        if (target) {
          target.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
        }
      });
    });

    var railTicking = false;
    window.addEventListener(
      "scroll",
      function () {
        if (railTicking) return;
        railTicking = true;
        requestAnimationFrame(function () {
          setActiveRailLink();
          railTicking = false;
        });
      },
      { passive: true }
    );

    setActiveRailLink();
  }

  // ---------- Shared FLIP helper for reorderable lists ----------

  window.flipAnimate = function flipAnimate(container, itemSelector, keyAttr, mutateFn) {
    if (reduceMotion) {
      mutateFn();
      return;
    }

    var before = {};
    container.querySelectorAll(itemSelector).forEach(function (el) {
      before[el.getAttribute(keyAttr)] = el.getBoundingClientRect();
    });

    mutateFn();

    container.querySelectorAll(itemSelector).forEach(function (el) {
      var prev = before[el.getAttribute(keyAttr)];
      if (!prev) return;
      var next = el.getBoundingClientRect();
      var dx = prev.left - next.left;
      var dy = prev.top - next.top;
      if (!dx && !dy) return;
      el.style.transition = "none";
      el.style.transform = "translate(" + dx + "px, " + dy + "px)";
      requestAnimationFrame(function () {
        el.style.transition = "transform 0.22s ease";
        el.style.transform = "";
      });
    });
  };
})();
