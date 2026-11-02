import io
import json
import logging
from datetime import timedelta

import qrcode
from django.db.models import Q
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus import Image as RLImage

logger = logging.getLogger(__name__)


def generate_qr_code_image(data_str, size_pixels=150):
    """
    Generates a high-contrast QR code image as an in-memory BytesIO buffer.
    """
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=6,
        border=2,
    )
    qr.add_data(data_str)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#070B14", back_color="#FFFFFF")
    
    buf = io.BytesIO()
    img.save(buf, format='PNG')  # type: ignore[call-arg]
    buf.seek(0)
    return buf


def generate_ticket_pdf(booking):
    """
    Generates a professional cinema ticket PDF containing:
    - Movie details (title, language, certification, runtime)
    - Theater & Venue details (name, city, address)
    - Screen (screen name, screen type e.g. IMAX, 4DX, Standard)
    - Show timing (date, formatted time)
    - Booked seats (all companion seats in batch)
    - Booking ID & Timestamp
    - Payment reference (order id, payment id, status, amount)
    - QR code for gate verification
    
    Returns raw PDF bytes.
    """
    from movies.models import Booking, Payment

    # Fetch companion seats booked together
    companion_bookings = Booking.objects.filter(
        user=booking.user,
        theater=booking.theater,
        booked_at__gte=booking.booked_at - timedelta(minutes=1),
        booked_at__lte=booking.booked_at + timedelta(minutes=1)
    ).select_related('seat')

    seats_list = [b.seat.seat_number for b in companion_bookings] or [booking.seat.seat_number]
    seats_display = ", ".join(sorted(seats_list))
    seats_count = len(seats_list)

    # Locate associated Payment
    payment = Payment.objects.filter(
        Q(booking=booking) | Q(bookings=booking),
        status='SUCCESS'
    ).first()

    total_amount = float(payment.amount) if payment else float(booking.amount * seats_count)
    payment_ref = (payment.payment_id or payment.order_id) if payment else f"REF-{booking.id:06d}"
    order_ref = payment.order_id if payment else f"ORD-{booking.id:06d}"

    movie = booking.movie
    theater = booking.theater
    user = booking.user

    # Screen details
    if theater.screen:
        screen_display = f"{theater.screen.name} ({theater.screen.screen_type})"
    else:
        screen_display = "Audi 1 (Dolby Atmos 4K)"

    # Formatted showtime
    show_date = theater.time.strftime("%A, %B %d, %Y")
    show_time = theater.time.strftime("%I:%M %p")

    # Generate QR Code verification payload
    qr_payload = json.dumps({
        "service": "TicketMitra",
        "booking_id": booking.id,
        "ref": f"TM-BK-{booking.id:06d}",
        "movie": movie.get_display_title(),
        "theater": theater.name,
        "screen": screen_display,
        "seats": seats_list,
        "show_time": f"{show_date} {show_time}",
        "user": user.username,
        "payment_ref": payment_ref,
        "verified": True
    })
    qr_buf = generate_qr_code_image(qr_payload)

    # Setup ReportLab Document
    pdf_buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        pdf_buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()
    
    # Custom Brand Palette
    BRAND_NAVY = colors.HexColor('#0F172A')
    BRAND_RED = colors.HexColor('#E63946')
    BRAND_GRAY = colors.HexColor('#64748B')
    BRAND_CARD_BG = colors.HexColor('#F1F5F9')
    BRAND_SUCCESS = colors.HexColor('#16A34A')
    TEXT_DARK = colors.HexColor('#0F172A')

    # Typography Styles
    style_header_title = ParagraphStyle(
        'HeaderTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=18,
        leading=22,
        textColor=colors.white,
        alignment=0
    )
    style_header_ref = ParagraphStyle(
        'HeaderRef',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=14,
        textColor=BRAND_RED,
        alignment=2
    )
    style_movie_title = ParagraphStyle(
        'MovieTitle',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=16,
        leading=20,
        textColor=TEXT_DARK
    )
    style_meta_label = ParagraphStyle(
        'MetaLabel',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10,
        textColor=BRAND_GRAY
    )
    style_meta_val = ParagraphStyle(
        'MetaVal',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=14,
        textColor=TEXT_DARK
    )
    style_seat_val = ParagraphStyle(
        'SeatVal',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=14,
        leading=18,
        textColor=BRAND_RED
    )
    style_terms = ParagraphStyle(
        'Terms',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=7.5,
        leading=10,
        textColor=BRAND_GRAY
    )

    story = []

    # 1. HEADER BANNER
    header_table_data = [
        [
            Paragraph("<b>TICKETMITRA CINEMAS</b><br/><font size=8 color='#CBD5E1'>OFFICIAL DIGITAL ADMISSION PASS</font>", style_header_title),
            Paragraph(f"<font color='#CBD5E1'>BOOKING ID</font><br/><b>#TM-BK-{booking.id:06d}</b>", style_header_ref)
        ]
    ]
    header_table = Table(header_table_data, colWidths=[360, 180])
    header_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), BRAND_NAVY),
        ('PADDING', (0, 0), (-1, -1), 14),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 14),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 10))

    # 2. MOVIE & SHOWTIME MAIN SECTION
    lang_name = movie.languages.first().name if movie.languages.exists() else (movie.original_language or "Original Audio")
    cert = movie.age_certification or "U/A"
    runtime = movie.get_runtime_display() if hasattr(movie, 'get_runtime_display') else f"{movie.runtime or 135} Mins"

    # QR Code Flowable
    qr_img = RLImage(qr_buf, width=110, height=110)

    movie_details_data = [
        [
            Paragraph(f"<b>{movie.get_display_title()}</b>", style_movie_title),
            Paragraph("<font color='#16A34A'><b>VERIFIED BOOKING</b></font>", ParagraphStyle('StatusBdg', fontName='Helvetica-Bold', fontSize=10, alignment=2, textColor=BRAND_SUCCESS))
        ],
        [
            Paragraph(f"<font color='#64748B'>Certification:</font> <b>{cert}</b> &nbsp;&bull;&nbsp; <font color='#64748B'>Language:</font> <b>{lang_name}</b> &nbsp;&bull;&nbsp; <font color='#64748B'>Runtime:</font> <b>{runtime}</b>", style_terms),
            Paragraph("<font size=8 color='#64748B'>Gate Scan QR Code</font>", ParagraphStyle('QRLbl', fontName='Helvetica', fontSize=8, alignment=2, textColor=BRAND_GRAY))
        ]
    ]
    movie_top_table = Table(movie_details_data, colWidths=[380, 160])
    movie_top_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('PADDING', (0, 0), (-1, -1), 2),
    ]))
    story.append(movie_top_table)
    story.append(Spacer(1, 8))

    # 3. DETAILS GRID + QR CODE SIDEBAR
    info_grid_data = [
        [
            Paragraph("THEATER & VENUE", style_meta_label),
            Paragraph("AUDITORIUM / SCREEN", style_meta_label),
            Paragraph("GATE VERIFICATION", style_meta_label)
        ],
        [
            Paragraph(f"<b>{theater.name}</b><br/><font size=8 color='#64748B'>{theater.address or theater.location}, {theater.city}</font>", style_meta_val),
            Paragraph(f"<b>{screen_display}</b>", style_meta_val),
            qr_img  # Spans 3 rows
        ],
        [
            Paragraph("DATE & SHOWTIME", style_meta_label),
            Paragraph("BOOKED SEATS", style_meta_label),
            ""
        ],
        [
            Paragraph(f"<b>{show_date}</b><br/><font size=12 color='#2563EB'><b>{show_time}</b></font>", style_meta_val),
            Paragraph(f"<b>{seats_display}</b><br/><font size=9 color='#64748B'>Total {seats_count} Seat{'s' if seats_count > 1 else ''}</font>", style_seat_val),
            ""
        ]
    ]

    info_table = Table(info_grid_data, colWidths=[220, 180, 140])
    info_table.setStyle(TableStyle([
        ('SPAN', (2, 1), (2, 3)),
        ('BACKGROUND', (0, 0), (-1, -1), BRAND_CARD_BG),
        ('PADDING', (0, 0), (-1, -1), 8),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (2, 1), (2, 3), 'CENTER'),
        ('VALIGN', (2, 1), (2, 3), 'MIDDLE'),
        ('LINEBELOW', (0, 1), (1, 1), 0.5, colors.HexColor('#CBD5E1')),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 10))

    # 4. PAYMENT & TRANSACTION SUMMARY
    payment_grid_data = [
        [
            Paragraph("PAYMENT REFERENCE", style_meta_label),
            Paragraph("ORDER / INTENT ID", style_meta_label),
            Paragraph("TOTAL AMOUNT PAID", style_meta_label),
            Paragraph("PAYMENT STATUS", style_meta_label),
        ],
        [
            Paragraph(f"<font size=9 color='#0F172A'><b>{payment_ref}</b></font>", style_meta_val),
            Paragraph(f"<font size=9 color='#0F172A'><b>{order_ref}</b></font>", style_meta_val),
            Paragraph(f"<font size=11 color='#16A34A'><b>₹{total_amount:.2f}</b></font>", style_meta_val),
            Paragraph("<font size=10 color='#16A34A'><b>PAID & CONFIRMED</b></font>", style_meta_val),
        ],
        [
            Paragraph("CUSTOMER NAME", style_meta_label),
            Paragraph("CUSTOMER EMAIL", style_meta_label),
            Paragraph("BOOKING TIMESTAMP", style_meta_label),
            Paragraph("PLATFORM", style_meta_label),
        ],
        [
            Paragraph(f"{user.get_full_name() or user.username}", style_meta_val),
            Paragraph(f"{user.email or 'customer@ticketmitra.com'}", style_meta_val),
            Paragraph(f"{booking.booked_at.strftime('%b %d, %Y - %I:%M %p')}", style_meta_val),
            Paragraph("TicketMitra Web", style_meta_val),
        ]
    ]

    pay_table = Table(payment_grid_data, colWidths=[135, 155, 125, 125])
    pay_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F8FAFC')),
        ('PADDING', (0, 0), (-1, -1), 6),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LINEBELOW', (0, 1), (-1, 1), 0.5, colors.HexColor('#E2E8F0')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
    ]))
    story.append(pay_table)
    story.append(Spacer(1, 12))

    # 5. PERFORATED CUTTING LINE
    story.append(HRFlowable(
        width="100%", thickness=1, color=colors.HexColor('#94A3B8'),
        spaceAfter=10, spaceBefore=4, dash=[4, 4]
    ))

    # 6. IMPORTANT CINEMA INSTRUCTIONS
    guidelines_text = """
    <b>IMPORTANT INSTRUCTIONS FOR ENTRY:</b><br/>
    &bull; Please present this PDF pass with QR code at the ticket scanner or box office counter for swift admission.<br/>
    &bull; Entry closes 15 minutes after showtime starts. No admission is permitted during the final 30 minutes of runtime.<br/>
    &bull; Outside food and beverages are strictly prohibited inside the auditorium premises.<br/>
    &bull; For any support or inquiries regarding this pass, contact <b>support@ticketmitra.com</b> with Booking ID <b>#TM-BK-""" + f"{booking.id:06d}" + """</b>.
    """
    story.append(Paragraph(guidelines_text, style_terms))

    # Build PDF Document
    doc.build(story)
    pdf_buffer.seek(0)
    return pdf_buffer.getvalue()
