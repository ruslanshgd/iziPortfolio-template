(function() {
  'use strict';
  
  // Initialize filters when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initFilters);
  } else {
    initFilters();
  }
  
  function initFilters() {
    const filterButtons = document.querySelectorAll('.cases-filter-btn');
    if (filterButtons.length === 0) return;
    
    // Set initial active state
    const companyButtons = document.querySelectorAll('.cases-filter-btn--company');
    const platformButtons = document.querySelectorAll('.cases-filter-btn--platform');
    
    // Activate "all" buttons by default
    companyButtons.forEach(btn => {
      if (btn.dataset.filter === 'all') {
        btn.classList.add('cases-filter-btn--active');
      }
    });
    
    platformButtons.forEach(btn => {
      if (btn.dataset.filter === 'all') {
        btn.classList.add('cases-filter-btn--active');
      }
    });
    
    // Add click handlers
    filterButtons.forEach(button => {
      button.addEventListener('click', function() {
        const filterType = this.dataset.type;
        const filterValue = this.dataset.filter;
        
        // Update active state for buttons of the same type
        if (filterType === 'company') {
          companyButtons.forEach(btn => {
            btn.classList.remove('cases-filter-btn--active');
          });
          this.classList.add('cases-filter-btn--active');
        } else if (filterType === 'platform') {
          platformButtons.forEach(btn => {
            btn.classList.remove('cases-filter-btn--active');
          });
          this.classList.add('cases-filter-btn--active');
        }
        
        // Apply filters
        applyFilters();
      });
    });
  }
  
  function applyFilters() {
    const caseCards = document.querySelectorAll('.case-card');
    if (caseCards.length === 0) return;
    
    // Get active filters
    const activeCompanyFilter = document.querySelector('.cases-filter-btn--company.cases-filter-btn--active')?.dataset.filter || 'all';
    const activePlatformFilter = document.querySelector('.cases-filter-btn--platform.cases-filter-btn--active')?.dataset.filter || 'all';
    
      // Filter cards
      let visibleCount = 0;
      caseCards.forEach(card => {
        const cardCompany = card.dataset.company || '';
        const cardPlatform = card.dataset.platform || 'web';
        
        let showCard = true;
        
        // Check company filter
        if (activeCompanyFilter !== 'all') {
          if (cardCompany === '' || cardCompany !== activeCompanyFilter) {
            showCard = false;
          }
        }
        
        // Check platform filter
        if (activePlatformFilter !== 'all' && cardPlatform !== activePlatformFilter) {
          showCard = false;
        }
        
        // Show/hide card with smooth transition
        if (showCard) {
          card.classList.remove('case-card--hidden');
          card.style.display = '';
          visibleCount++;
        } else {
          card.classList.add('case-card--hidden');
          card.style.display = 'none';
        }
      });
      
      // Optional: show message if no cards visible
      const cardsContainer = document.querySelector('.case-cards');
      if (cardsContainer) {
        let noResultsMsg = cardsContainer.querySelector('.no-results-message');
        if (visibleCount === 0) {
          if (!noResultsMsg) {
            noResultsMsg = document.createElement('li');
            noResultsMsg.className = 'no-results-message';
            noResultsMsg.style.gridColumn = '1 / -1';
            noResultsMsg.style.textAlign = 'center';
            noResultsMsg.style.padding = '3rem 1rem';
            noResultsMsg.style.color = '#666';
            noResultsMsg.textContent = 'Кейсы не найдены';
            cardsContainer.appendChild(noResultsMsg);
          }
        } else if (noResultsMsg) {
          noResultsMsg.remove();
        }
      }
  }
})();
