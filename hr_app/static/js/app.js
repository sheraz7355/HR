document.addEventListener('DOMContentLoaded', function () {
    // Sidebar toggle (desktop: collapse, mobile: open/close)
    const toggle = document.getElementById('sidebar-toggle');
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebar-overlay');
    const isMobile = () => window.innerWidth <= 768;

    if (toggle && sidebar) {
        toggle.addEventListener('click', () => {
            if (isMobile()) {
                sidebar.classList.toggle('open');
                if (overlay) overlay.classList.toggle('show');
            } else {
                sidebar.classList.toggle('collapsed');
            }
        });
    }
    if (overlay) {
        overlay.addEventListener('click', () => {
            sidebar.classList.remove('open');
            overlay.classList.remove('show');
        });
    }
    window.addEventListener('resize', () => {
        if (!isMobile()) {
            sidebar.classList.remove('open');
            if (overlay) overlay.classList.remove('show');
        }
    });

    // Notification dropdown
    const notifBtn = document.getElementById('notif-btn');
    const notifMenu = document.getElementById('notif-menu');
    if (notifBtn && notifMenu) {
        notifBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            notifMenu.classList.toggle('hidden');
        });
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.notif-dropdown')) {
                notifMenu.classList.add('hidden');
            }
        });
    }

    // Mark notification read
    document.querySelectorAll('.notif-item').forEach(item => {
        item.addEventListener('click', function () {
            const id = this.dataset.id;
            if (id) {
                fetch(`/auth/api/notifications/${id}/read`, { method: 'POST' });
                this.remove();
                const badge = document.querySelector('.notif-badge');
                if (badge) {
                    const count = parseInt(badge.textContent) - 1;
                    badge.textContent = count;
                    if (count <= 0) badge.remove();
                }
            }
        });
    });

    // Mark all read
    const markAllBtn = document.getElementById('mark-all-read');
    if (markAllBtn) {
        markAllBtn.addEventListener('click', () => {
            fetch('/auth/api/notifications/read-all', { method: 'POST' }).then(() => {
                document.querySelectorAll('.notif-item').forEach(el => el.remove());
                const badge = document.querySelector('.notif-badge');
                if (badge) badge.remove();
            });
        });
    }

    // Auto-close flash messages
    document.querySelectorAll('.flash-success, .flash-danger, .flash-warning, .flash-info').forEach(el => {
        setTimeout(() => { el.style.opacity = '0'; el.style.transition = 'opacity 0.5s'; }, 4000);
        setTimeout(() => { el.remove(); }, 4500);
    });
});
