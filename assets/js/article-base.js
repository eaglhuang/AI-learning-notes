(function () {
  var COUNTER_SRC = 'https://hits.sh/eaglhuang.github.io/AI-learning-notes.svg?label=traffic&color=10252D&labelColor=0C6F68';
  var OVERLAY_ID = 'page-overlay';

  function isEnglishPage() {
    var lang = (document.documentElement.getAttribute('lang') || '').toLowerCase();
    return lang.indexOf('en') === 0 || /_en\.html$/i.test(location.pathname);
  }

  function homeLabel() {
    return isEnglishPage() ? 'Home' : '回首頁';
  }

  function footerCopy() {
    return isEnglishPage()
      ? 'AI Learning Notes technical article base.'
      : 'AI Learning Notes 技術文章基底。';
  }

  function createCounterElement() {
    var counter = document.createElement('div');
    counter.className = 'footer-counter traffic-counter';
    counter.setAttribute('aria-label', isEnglishPage() ? 'Traffic counter' : '網站流量計數器');
    counter.innerHTML =
      '<span class="footer-counter-label traffic-counter-label">' +
      (isEnglishPage() ? 'Traffic' : '網站流量') +
      '</span>' +
      '<img src="' + COUNTER_SRC + '" alt="' + (isEnglishPage() ? 'Site traffic counter' : '網站累積流量計數器') + '">';
    return counter;
  }

  function createTailActionsElement() {
    var actions = document.createElement('p');
    actions.className = 'back-links article-tail-actions';
    actions.innerHTML =
      '<a href="./">' + homeLabel() + '</a> ｜ <a href="#top">Top</a>';
    return actions;
  }

  function ensureBodyTop() {
    if (!document.body.id) {
      document.body.id = 'top';
    }
  }

  function ensureOverlay() {
    var overlay = document.getElementById(OVERLAY_ID);
    if (overlay) {
      return overlay;
    }

    overlay = document.createElement('div');
    overlay.id = OVERLAY_ID;
    overlay.setAttribute('aria-hidden', 'true');
    overlay.innerHTML =
      '<div class="cell-stage">' +
      '<div class="cell-a"></div>' +
      '<div class="cell-bridge"></div>' +
      '<div class="cell-b"></div>' +
      '</div>';

    document.body.insertBefore(overlay, document.body.firstChild);
    return overlay;
  }

  function findArticleContainer() {
    return document.querySelector('.main-column') || document.body;
  }

  function hasTailActions(container) {
    return !!container.querySelector('.article-tail-actions');
  }

  function hasFooterLike(container) {
    return !!container.querySelector('.footer, .site-footer, .traffic-counter');
  }

  function ensureTailActions(container) {
    if (hasTailActions(container)) {
      return;
    }

    var footer = container.querySelector('.footer, .site-footer, .traffic-counter');
    var tailActions = createTailActionsElement();
    if (footer && footer.parentNode === container) {
      container.insertBefore(tailActions, footer);
      return;
    }

    container.appendChild(tailActions);
  }

  function ensureFooter(container) {
    var footer = document.querySelector('.footer, .site-footer');
    var trafficCounter = document.querySelector('.traffic-counter');

    if (!footer && !trafficCounter) {
      footer = document.createElement('div');
      footer.className = 'footer';
      footer.innerHTML = '<div>' + footerCopy() + '</div>';
      footer.appendChild(createCounterElement());
      container.appendChild(footer);
      return;
    }

    if (footer && !footer.querySelector('.footer-counter, .traffic-counter')) {
      footer.appendChild(createCounterElement());
    }
  }

  function ensureCounterImages() {
    document.querySelectorAll('.footer-counter img, .traffic-counter img').forEach(function (img) {
      img.setAttribute('loading', 'eager');
      img.setAttribute('decoding', 'async');
      if ('fetchPriority' in img) {
        img.fetchPriority = 'high';
      }
    });
  }

  function showStatus(figure, message) {
    var status = figure.querySelector('.copy-status');
    if (!status) {
      return;
    }
    status.textContent = message;
    status.classList.add('is-visible');
    window.clearTimeout(status._timer);
    status._timer = window.setTimeout(function () {
      status.classList.remove('is-visible');
    }, 1800);
  }

  function serializeSvg(svg) {
    var clone = svg.cloneNode(true);
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    clone.setAttribute('xmlns:xlink', 'http://www.w3.org/1999/xlink');
    return new XMLSerializer().serializeToString(clone);
  }

  function figureDownloadName(figure, extension) {
    var name = figure.getAttribute('data-figure-name') || 'figure';
    return name + '.' + extension;
  }

  function triggerDownload(blob, fileName) {
    var url = URL.createObjectURL(blob);
    var anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = fileName;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(function () {
      URL.revokeObjectURL(url);
    }, 0);
  }

  async function downloadSvg(button) {
    var figure = button.closest('figure');
    var svg = figure && figure.querySelector('svg');
    if (!svg) {
      return;
    }

    try {
      var svgMarkup = serializeSvg(svg);
      var blob = new Blob([svgMarkup], { type: 'image/svg+xml;charset=utf-8' });
      triggerDownload(blob, figureDownloadName(figure, 'svg'));
      showStatus(figure, '已下載 SVG');
    } catch (error) {
      showStatus(figure, '下載 SVG 失敗');
    }
  }

  function svgViewBoxSize(svg) {
    var viewBox = svg.viewBox && svg.viewBox.baseVal;
    if (viewBox && viewBox.width && viewBox.height) {
      return { width: viewBox.width, height: viewBox.height };
    }

    return {
      width: Number(svg.getAttribute('width')) || 1200,
      height: Number(svg.getAttribute('height')) || 800,
    };
  }

  async function downloadPng(button) {
    var figure = button.closest('figure');
    var svg = figure && figure.querySelector('svg');
    if (!svg) {
      return;
    }

    var svgMarkup = serializeSvg(svg);
    var blob = new Blob([svgMarkup], { type: 'image/svg+xml;charset=utf-8' });
    var url = URL.createObjectURL(blob);
    var image = new Image();
    var size = svgViewBoxSize(svg);

    try {
      var pngBlob = await new Promise(function (resolve, reject) {
        image.onload = function () {
          var canvas = document.createElement('canvas');
          canvas.width = size.width * 2;
          canvas.height = size.height * 2;
          var context = canvas.getContext('2d');
          if (!context) {
            reject(new Error('2d context unavailable'));
            return;
          }
          context.fillStyle = '#fffaf2';
          context.fillRect(0, 0, canvas.width, canvas.height);
          context.drawImage(image, 0, 0, canvas.width, canvas.height);
          canvas.toBlob(function (result) {
            if (result) {
              resolve(result);
            } else {
              reject(new Error('png blob failed'));
            }
          }, 'image/png');
        };
        image.onerror = function () {
          reject(new Error('svg load failed'));
        };
        image.src = url;
      });

      triggerDownload(pngBlob, figureDownloadName(figure, 'png'));
      showStatus(figure, '已下載 PNG');
    } catch (error) {
      showStatus(figure, '下載 PNG 失敗');
    } finally {
      URL.revokeObjectURL(url);
    }
  }

  function initFigureDownloads() {
    document.querySelectorAll('[data-download-svg]').forEach(function (button) {
      button.addEventListener('click', function () {
        downloadSvg(button);
      });
    });

    document.querySelectorAll('[data-download-png]').forEach(function (button) {
      button.addEventListener('click', function () {
        downloadPng(button);
      });
    });
  }

  function initOverlayTransitions() {
    var overlay = ensureOverlay();

    document.addEventListener('click', function (event) {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
        return;
      }

      var anchor = event.target.closest('a[href]');
      if (!anchor || anchor.target === '_blank' || anchor.hasAttribute('download')) {
        return;
      }

      var url;
      try {
        url = new URL(anchor.href, location.href);
      } catch (error) {
        return;
      }

      if (url.origin !== location.origin) {
        return;
      }

      if (url.hash && url.pathname === location.pathname && url.search === location.search) {
        return;
      }

      event.preventDefault();
      overlay.classList.add('active');
      window.setTimeout(function () {
        location.href = anchor.href;
      }, 560);
    });
  }

  function initArticleShell() {
    ensureBodyTop();
    var container = findArticleContainer();
    ensureTailActions(container);
    ensureFooter(container);
    ensureCounterImages();
    initFigureDownloads();
    initOverlayTransitions();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initArticleShell);
  } else {
    initArticleShell();
  }
})();
