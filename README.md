# TicketMitra 🎬

> **Your Movie. Your Seat. Your Experience.**  
> An automated movie discovery, intelligent seat reservation, and cinema operations management platform built with Django.

---

## 🌟 Overview

**TicketMitra** combines a customer-facing movie discovery and ticketing web experience with an enterprise-grade Cinema Operations & Administration System. It features automated Indian regional cinema discovery via TMDB, AI-driven metadata synthesis using Groq, intelligent 3-tier movie ranking, a 3D visual auditorium seat generator, and Stripe payment processing.

---

## 🎯 Key Highlights & Features

### 1. 🎞️ Automated Movie Discovery Engine
- **Multilingual Regional Coverage**: Automatically synchronizes Indian cinema across Kannada, Tamil, Telugu, Malayalam, Hindi, Bengali, Marathi, and Gujarati.
- **Weekly Auto-Sync**: Scheduled background synchronization refreshes new releases, OTT availability, and upcoming theatrical movies every Friday.
- **Groq AI Metadata Synthesis**: Employs Groq AI models to analyze synopsis, audience appeal, genre classification, and regional theatrical indicators.
- **YouTube Trailer Integration**: Server-side trailer resolution and embedded cinematic preview modal.

### 2. ⚡ Intelligent 3-Tier Movie Ranking & Prioritization
Unlike static lists, movies are dynamically prioritized into three clear operational tiers:
1. **Trending & Booking Open**: Top-anticipated, high-demand franchise sequels and major productions with active bookable showtimes.
2. **Upcoming Anticipated**: Major productions slated for future theatrical release with "Coming Soon" badges and advance promotion.
3. **Now Showing**: Currently running theatrical releases filtered by city, language, and theatre formats.

### 3. 💺 Visual Auditorium Seating Generator & Synchronization
- **Interactive 3D Seating Grid**: Custom seat layout generator supporting Standard, IMAX, 4DX, Dolby Atmos, and Gold formats.
- **Atomic Database Synchronization**: Automatically creates and synchronizes master seat records without duplicates.
- **Booking Protection**: Safeguards existing audience reservations and confirmed tickets during layout adjustments.
- **Dynamic Tier Pricing**: Category-based seating (Regular, Premium, VIP, Recliner, Accessible).

### 4. 🎟️ Customer Booking & Checkout Flow
- Real-time seat selection with temporary lock/hold mechanisms.
- Transparent fee calculation (ticket price, convenience charges, GST).
- Secure credit card and digital payment processing powered by **Stripe**.
- Instant booking ticket generation with unique QR/booking reference numbers.

### 5. 🏛️ Cinema Operations & Admin Dashboard
A dedicated, unified cinema management suite designed with a **Midnight Cinematic Design System**:
- **Operational Metrics**: Gross revenue, refund processing, theatre occupancy, active holds, and live screenings.
- **Showtime Management**: Automated multi-slot scheduling, pricing plan linking, and recurring slot generation.
- **Screens & Auditoriums**: Comprehensive multi-multiplex screen controls.
- **Live Search & Audit Logs**: Real-time customer, payment, booking, and operational activity tracking.

---

## 🎨 Design System

TicketMitra features a consistent **Midnight Editorial Cinema** aesthetic across both the customer site and the operations dashboard:

| Token | Color Code | Application |
| :--- | :--- | :--- |
| **Deep Navy** | `#0B192B` | Primary backdrop with woven midnight texture |
| **Midnight Navy** | `#10243A` | Foundation background & modal backdrop |
| **Surface Glass** | `rgba(22, 34, 56, 0.76)` | Translucent frosted cards with backdrop blur |
| **Crimson Accent** | `#D61F45` | Primary CTAs, active pills, badges, and focus rings |
| **Deep Crimson** | `#A91535` | Hover states and linear gradients |
| **Warm Ivory** | `#F2E9DC` | High-contrast display typography |
| **Muted Parchment**| `#C8BBAA` | Form labels, subtext, and secondary metadata |
| **Antique Brass** | `#B58A5A` | Section subtitles, metrics labels, and table headers |

- **Typography**: `Playfair Display` for major headings and display titles; `DM Sans` for clean, responsive interface text.

---

## 🛠️ Tech Stack

- **Framework**: Django (Python 3.12+)
- **Frontend**: HTML5, CSS3, JavaScript (ES6+), Bootstrap, FontAwesome 6
- **Typography**: Google Fonts (*Playfair Display*, *DM Sans*)
- **Database**: SQLite (Default development) / PostgreSQL ready
- **External APIs**:
  - [The Movie Database (TMDB) API](https://www.themoviedb.org/documentation/api)
  - [Groq AI Cloud API](https://groq.com/)
  - [Stripe API](https://stripe.com/docs/api)
  - [YouTube Data API v3](https://developers.google.com/youtube/v3)
- **Task Scheduling**: In-process threading scheduler / Celery Beat ready

---

## 🚀 Quick Start & Installation

### 1. Clone the Repository
```bash
git clone https://github.com/vishnukaranth-git/Ticketmitra.git
cd Ticketmitra
```

### 2. Set Up a Virtual Environment
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
# Or if using pyproject.toml:
pip install .
```

### 4. Configure Environment Variables
Copy `.env.example` to `.env` and provide your API keys:
```env
# TMDB API
TMDB_API_KEY=your_tmdb_api_key_here

# Groq AI
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=openai/gpt-oss-120b

# Stripe Payments
STRIPE_PUBLISHABLE_KEY=pk_test_your_key_here
STRIPE_SECRET_KEY=sk_test_your_key_here
STRIPE_WEBHOOK_SECRET=

# YouTube Data API (Optional)
YOUTUBE_API_KEY=your_youtube_api_key_here
```

### 5. Apply Migrations & Create Superuser
```bash
python manage.py migrate
python manage.py createsuperuser
```

### 6. Run the Development Server
```bash
python manage.py runserver
```

Open your browser and navigate to:
- **Customer Portal**: `http://127.0.0.1:8000/`
- **Cinema Operations Center**: `http://127.0.0.1:8000/admin/dashboard/`

---

## 📁 Project Structure

```text
Ticketmitra/
├── movies/                 # Movie discovery, rankings, showtimes, seats & bookings
│   ├── admin_views.py      # Operations dashboard, analytics, visual seating & pricing views
│   ├── models.py           # Movie, Theater, Screen, Seat, Showtime, Booking & Payment models
│   ├── apps.py             # App configuration & background scheduler
│   └── views.py            # Customer-facing movie discovery & booking controllers
├── users/                  # User authentication, profiles & authorization
├── static/
│   ├── admin/css/          # TicketMitra unified admin stylesheet (ticketmitra_admin.css)
│   ├── css/                # Cinema customer styles (ticketmitra-cinema.css)
│   └── images/             # Textures (midnight paper), posters & branding
├── templates/
│   ├── admin/              # Cinema operations dashboard & management templates
│   ├── movies/             # Customer discovery, seat selection, & checkout templates
│   └── users/              # Authentication & user profile templates
├── Ticketmitra/             # Django project settings, ASGI/WSGI & root URL configurations
├── manage.py               # Django CLI entrypoint
└── db.sqlite3              # Sample development database with seed movies & showtimes
```

---

## 🔒 Security & Privacy

- All sensitive credentials, API keys, and secret tokens are strictly loaded via `.env` and kept out of version control.
- Django CSRF protection, sanitized URL parameters, and session-based authentication are enforced throughout.

---

## 📄 License

This project is open-source and available under the [MIT License](LICENSE).
