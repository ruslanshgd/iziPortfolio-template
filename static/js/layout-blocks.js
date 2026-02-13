(function () {
  'use strict';

  function initLayoutBlocks() {
    if (typeof lucide === 'undefined') return;

    lucide.createIcons();

    var modal = document.getElementById('layout-modal');
    if (!modal) return;

    var modalImg = modal.querySelector('.layout-modal__img');
    var closeBtn = modal.querySelector('.layout-modal__close');
    var backdrop = modal.querySelector('.layout-modal__backdrop');

    function openModal(src) {
      if (modalImg) modalImg.src = src;
      modal.setAttribute('aria-hidden', 'false');
      document.body.style.overflow = 'hidden';
    }

    function closeModal() {
      modal.setAttribute('aria-hidden', 'true');
      document.body.style.overflow = '';
    }

    document.querySelectorAll('.layout-block__zoom-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var wrap = btn.closest('.layout-block__mockup-image-wrap');
        var img = wrap && wrap.querySelector('.layout-block__mockup-img');
        var src = img && img.getAttribute('data-full-src');
        if (src) openModal(src);
      });
    });

    if (closeBtn) closeBtn.addEventListener('click', closeModal);
    if (backdrop) backdrop.addEventListener('click', closeModal);

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && modal.getAttribute('aria-hidden') === 'false') {
        closeModal();
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initLayoutBlocks);
  } else {
    initLayoutBlocks();
  }
})();
