/**
 * TicketMitra Operations - Admin Dashboard Interactivity
 */

document.addEventListener('DOMContentLoaded', function() {
  // 1. Sidebar Toggle
  const sidebar = document.getElementById('tmSidebar');
  const toggleBtn = document.getElementById('tmSidebarToggle');
  if (toggleBtn && sidebar) {
    toggleBtn.addEventListener('click', function(e) {
      e.stopPropagation();
      sidebar.classList.toggle('open');
    });

    document.addEventListener('click', function(e) {
      if (window.innerWidth <= 992 && sidebar.classList.contains('open') && !sidebar.contains(e.target) && e.target !== toggleBtn) {
        sidebar.classList.remove('open');
      }
    });
  }

  // 2. User Menu Dropdown Toggle
  const userTrigger = document.getElementById('tmUserTrigger');
  const userDropdown = document.getElementById('tmUserDropdown');
  if (userTrigger && userDropdown) {
    userTrigger.addEventListener('click', function(e) {
      e.stopPropagation();
      userDropdown.classList.toggle('show');
      if (notifDropdown) notifDropdown.classList.remove('show');
    });
  }

  // 3. Notification Dropdown Toggle
  const notifBtn = document.getElementById('tmNotifBtn');
  const notifDropdown = document.getElementById('tmNotifDropdown');
  if (notifBtn && notifDropdown) {
    notifBtn.addEventListener('click', function(e) {
      e.stopPropagation();
      notifDropdown.classList.toggle('show');
      if (userDropdown) userDropdown.classList.remove('show');
    });
  }

  // Close dropdowns on outside click
  document.addEventListener('click', function(e) {
    if (userDropdown && !userDropdown.contains(e.target)) {
      userDropdown.classList.remove('show');
    }
    if (notifDropdown && !notifDropdown.contains(e.target)) {
      notifDropdown.classList.remove('show');
    }
  });

  // 4. Modal Helpers
  window.tmOpenModal = function(modalId) {
    const m = document.getElementById(modalId);
    if (m) m.classList.add('show');
  };

  window.tmCloseModal = function(modalId) {
    const m = document.getElementById(modalId);
    if (m) m.classList.remove('show');
  };

  // Close modal when clicking backdrop
  document.querySelectorAll('.tm-modal-backdrop').forEach(function(m) {
    m.addEventListener('click', function(e) {
      if (e.target === m) {
        m.classList.remove('show');
      }
    });
  });
});
