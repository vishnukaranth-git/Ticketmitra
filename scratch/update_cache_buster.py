import os

base_path = 'Ticketmitra/templates/admin/base.html'
with open(base_path, 'r', encoding='utf-8') as f:
    base_content = f.read()

# Replace css link with cache buster
base_content = base_content.replace(
    "{% static 'admin/css/ticketmitra_admin.css' %}",
    "{% static 'admin/css/ticketmitra_admin.css' %}?v=4.0"
)

critical_style = """  <!-- Inline Cinematic Design System Tokens (Immediate Render) -->
  <style>
    :root {
      --tm-midnight-navy:    #10243A;
      --tm-deep-navy:        #0B192B;
      --tm-surface:          #162238;
      --tm-surface-elevated: #1B2940;
      --tm-crimson:          #D61F45;
      --tm-crimson-hover:    #A91535;
      --tm-crimson-deep:     #A91535;
      --tm-warm-ivory:       #F2E9DC;
      --tm-text-muted:       #C8BBAA;
      --tm-brass:            #B58A5A;
      --tm-border:           rgba(226, 211, 193, 0.16);
      --tm-border-strong:    rgba(226, 211, 193, 0.28);
      --tm-border-subtle:    rgba(226, 211, 193, 0.08);
      --tm-glass:            rgba(22, 34, 56, 0.76);
      --tm-glass-raised:     rgba(27, 41, 64, 0.88);
      --tm-glass-deep:       rgba(11, 25, 43, 0.90);
      --tm-glass-hover:      rgba(226, 211, 193, 0.04);
      --tm-glow-crimson:     0 8px 24px rgba(214, 31, 69, 0.35);

      /* Backward Compatibility Aliases */
      --tm-primary:          #D61F45;
      --tm-primary-hover:    #A91535;
      --tm-orange:           #B58A5A;
      --tm-blue:             #3B82F6;
      --tm-bg:               #0B192B;
      --tm-bg-secondary:     #10243A;
      --tm-card:             rgba(22, 34, 56, 0.76);
      --tm-elevated:         #1B2940;
      --tm-text:             #F2E9DC;
      --tm-radius:           14px;
      --tm-sidebar-width:    270px;
      --tm-topbar-height:    70px;
    }

    html, body {
      background-color: #0B192B !important;
      background-image:
        radial-gradient(ellipse at 88% 4%, rgba(214, 31, 69, 0.12), transparent 36rem),
        radial-gradient(ellipse at 12% 96%, rgba(181, 138, 90, 0.08), transparent 32rem),
        linear-gradient(180deg, rgba(11, 25, 43, 0.90), rgba(16, 36, 58, 0.94)),
        url('/static/images/midnight_paper_texture.png') !important;
      background-attachment: fixed !important;
      background-size: cover, cover, cover, auto !important;
      background-repeat: no-repeat, no-repeat, no-repeat, repeat !important;
      color: #F2E9DC !important;
      font-family: 'DM Sans', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
      margin: 0;
      padding: 0;
    }

    h1, h2, h3, h4, h5, h6, .tm-heading, .tm-page-title, .tm-hero-title, .tm-brand-title, .tm-panel-title, .tm-metric-value, .tm-theater-name {
      font-family: 'Playfair Display', Georgia, 'Times New Roman', serif !important;
      color: #F2E9DC !important;
      letter-spacing: -0.015em;
    }

    .tm-brand-title {
      font-family: 'Playfair Display', Georgia, serif !important;
      font-weight: 800;
      color: #F2E9DC !important;
    }
    .tm-brand-title span {
      color: #D61F45 !important;
    }
    .tm-brand-subtitle {
      color: #B58A5A !important;
      font-family: 'DM Sans', sans-serif !important;
      letter-spacing: 0.16em !important;
      font-weight: 700 !important;
    }

    .tm-sidebar {
      background: rgba(11, 25, 43, 0.92) !important;
      backdrop-filter: blur(20px) !important;
      -webkit-backdrop-filter: blur(20px) !important;
      border-right: 1px solid rgba(226, 211, 193, 0.16) !important;
    }
    .tm-sidebar-brand {
      background: rgba(16, 36, 58, 0.70) !important;
      border-bottom: 1px solid rgba(226, 211, 193, 0.16) !important;
    }
    .tm-brand-logo-icon {
      background: linear-gradient(135deg, #D61F45, #A91535) !important;
      box-shadow: 0 4px 14px rgba(214, 31, 69, 0.35) !important;
      border: 1px solid rgba(226, 211, 193, 0.2) !important;
    }

    .tm-nav-section-title {
      color: #B58A5A !important;
      font-family: 'DM Sans', sans-serif !important;
      letter-spacing: 0.12em !important;
      font-weight: 700 !important;
    }
    .tm-nav-item {
      color: #C8BBAA !important;
      font-family: 'DM Sans', sans-serif !important;
    }
    .tm-nav-item:hover {
      color: #F2E9DC !important;
      background: rgba(226, 211, 193, 0.06) !important;
      border-color: rgba(226, 211, 193, 0.12) !important;
    }
    .tm-nav-item.active {
      color: #F2E9DC !important;
      background: rgba(214, 31, 69, 0.14) !important;
      border: 1px solid rgba(214, 31, 69, 0.38) !important;
    }
    .tm-nav-item.active i {
      color: #D61F45 !important;
    }

    .tm-topbar {
      background: rgba(11, 25, 43, 0.88) !important;
      backdrop-filter: blur(18px) !important;
      border-bottom: 1px solid rgba(226, 211, 193, 0.16) !important;
    }

    .tm-dashboard-hero {
      background: linear-gradient(135deg, rgba(22, 34, 56, 0.82), rgba(11, 25, 43, 0.88)),
                  radial-gradient(ellipse at top right, rgba(214, 31, 69, 0.16), transparent 70%) !important;
      border: 1px solid rgba(226, 211, 193, 0.16) !important;
      backdrop-filter: blur(14px) !important;
    }
    .tm-dashboard-hero::before {
      background: linear-gradient(to bottom, #D61F45, #B58A5A) !important;
    }

    .tm-panel-card, .tm-metric-card, .tm-stat-card, #changelist {
      background: rgba(22, 34, 56, 0.76) !important;
      border: 1px solid rgba(226, 211, 193, 0.16) !important;
      backdrop-filter: blur(14px) !important;
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.22) !important;
    }
    .tm-panel-header, .results thead th, .tm-data-table thead th, table.table thead th {
      background: rgba(27, 41, 64, 0.75) !important;
      color: #B58A5A !important;
      font-family: 'DM Sans', sans-serif !important;
      font-weight: 700 !important;
      letter-spacing: 0.08em !important;
      border-bottom: 1px solid rgba(226, 211, 193, 0.16) !important;
    }
    .results tbody tr:hover, .tm-data-table tbody tr:hover, table.table tbody tr:hover {
      background: rgba(226, 211, 193, 0.04) !important;
    }
    .results td, .results th, .tm-data-table td, table.table td {
      border-bottom: 1px solid rgba(226, 211, 193, 0.08) !important;
      color: #F2E9DC !important;
    }

    .tm-btn-primary, .btn-primary {
      background: #D61F45 !important;
      border-color: #D61F45 !important;
      color: #F2E9DC !important;
      font-family: 'DM Sans', sans-serif !important;
      box-shadow: 0 4px 14px rgba(214, 31, 69, 0.3) !important;
    }
    .tm-btn-primary:hover, .btn-primary:hover {
      background: #A91535 !important;
      border-color: #A91535 !important;
      color: #fff !important;
    }

    .tm-btn-secondary, .btn-secondary {
      background: rgba(181, 138, 90, 0.14) !important;
      border: 1px solid rgba(181, 138, 90, 0.35) !important;
      color: #F2E9DC !important;
    }
    .tm-btn-ghost {
      background: rgba(226, 211, 193, 0.06) !important;
      border: 1px solid rgba(226, 211, 193, 0.16) !important;
      color: #F2E9DC !important;
    }
  </style>
"""

# Insert critical style before </head>
if '<!-- Inline Cinematic Design System Tokens' not in base_content:
    base_content = base_content.replace('</head>', critical_style + '\n</head>')

with open(base_path, 'w', encoding='utf-8') as f:
    f.write(base_content)
print("Updated base.html with critical styles and ?v=4.0")

# Update base_site.html as well
site_path = 'Ticketmitra/templates/admin/base_site.html'
with open(site_path, 'r', encoding='utf-8') as f:
    site_content = f.read()

site_content = site_content.replace(
    "/static/admin/css/ticketmitra_admin.css",
    "/static/admin/css/ticketmitra_admin.css?v=4.0"
)

with open(site_path, 'w', encoding='utf-8') as f:
    f.write(site_content)
print("Updated base_site.html with ?v=4.0")

