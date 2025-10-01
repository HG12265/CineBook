import os
import re
import qrcode
import secrets
from PIL import Image
import json
from io import BytesIO
from datetime import datetime, timedelta, time as dtime
from functools import wraps
import random
# --- Third-party Libraries ---
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, send_file
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart # This import is correct
from email.mime.application import MIMEApplication
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
import stripe


# --- Load Environment Variables ---
load_dotenv()

# ==============================================================================
# APP & CONFIGURATION SETUP
# ==============================================================================
app = Flask(__name__)

# Load configuration from environment variables with safe defaults
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///cinema.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = os.getenv("UPLOAD_FOLDER", "static/uploads")
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}

# Email configuration
app.config["MAIL_SERVER"] = os.getenv("MAIL_SERVER", "smtp.gmail.com")
app.config["MAIL_PORT"] = int(os.getenv("MAIL_PORT", 587))
app.config["MAIL_USE_TLS"] = os.getenv("MAIL_USE_TLS", "True").lower() in ("true", "1")
app.config["MAIL_USERNAME"] = os.getenv("MAIL_USERNAME")
app.config["MAIL_PASSWORD"] = os.getenv("MAIL_PASSWORD")

# OAuth configuration
app.config["GOOGLE_CLIENT_ID"] = os.getenv("GOOGLE_CLIENT_ID")
app.config["GOOGLE_CLIENT_SECRET"] = os.getenv("GOOGLE_CLIENT_SECRET")

# Stripe configuration
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
app.config["STRIPE_PUBLISHABLE_KEY"] = os.getenv("STRIPE_PUBLISHABLE_KEY")

# ==============================================================================
# EXTENSIONS INITIALIZATION
# ==============================================================================
db = SQLAlchemy(app)
oauth = OAuth(app)

google = oauth.register(
    name="google",
    client_id=app.config["GOOGLE_CLIENT_ID"],
    client_secret=app.config["GOOGLE_CLIENT_SECRET"],
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"}
)

# ==============================================================================
# DATABASE MODELS
# ==============================================================================
class Theater(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    address = db.Column(db.String(200), nullable=False)
    city = db.Column(db.String(50), nullable=False)
    image_url = db.Column(db.String(200))

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    full_name = db.Column(db.String(100))
    phone = db.Column(db.String(20))
    role = db.Column(db.String(20), default="user")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    avatar = db.Column(db.String(200), default="/static/images/default-avatar.png")
    provider = db.Column(db.String(20), default="local")
    reset_token = db.Column(db.String(100), unique=True)
    reset_token_expiry = db.Column(db.DateTime)
    def set_password(self, p): self.password_hash = generate_password_hash(p)
    def check_password(self, p): return check_password_hash(self.password_hash, p) if self.password_hash else False

class Movie(db.Model):
    id = db.Column(db.Integer,  primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    genre = db.Column(db.String(50), nullable=False)
    duration = db.Column(db.Integer, nullable=False)
    description = db.Column(db.Text)
    poster_url = db.Column(db.String(200))
    is_active = db.Column(db.Boolean, default=True)
    language = db.Column(db.String(50), default="English")
    rating = db.Column(db.Float, default=0.0)
    director = db.Column(db.String(100))
    cast = db.Column(db.Text)
    trailer_url = db.Column(db.String(200))

class Showtime(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    movie_id = db.Column(db.Integer, db.ForeignKey("movie.id", ondelete="CASCADE"), nullable=False)
    theater_id = db.Column(db.Integer, db.ForeignKey("theater.id", ondelete="CASCADE"), nullable=False)
    time = db.Column(db.DateTime, nullable=False)
    hall = db.Column(db.String(50), nullable=False)
    rows = db.Column(db.Integer, nullable=False)
    cols = db.Column(db.Integer, nullable=False)
    price_standard = db.Column(db.Float, default=250.0)
    price_premium = db.Column(db.Float, default=400.0)
    price_vip = db.Column(db.Float, default=600.0)
    movie = db.relationship("Movie", backref=db.backref("showtimes", lazy=True, cascade="all, delete-orphan"))
    theater = db.relationship("Theater", backref=db.backref("showtimes", lazy=True, cascade="all, delete-orphan"))

class SeatLayout(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    showtime_id = db.Column(db.Integer, db.ForeignKey("showtime.id", ondelete="CASCADE"), unique=True, nullable=False)
    layout = db.Column(db.Text, nullable=False)
    showtime = db.relationship("Showtime", backref=db.backref("seat_layout", uselist=False, cascade="all, delete-orphan"))

class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    showtime_id = db.Column(db.Integer, db.ForeignKey('showtime.id'), nullable=False)
    food_items = db.Column(db.Text, nullable=True)
    seats = db.Column(db.Text, nullable=False)
    total_price = db.Column(db.Float, nullable=False)
    booking_time = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default="confirmed")
    attended = db.Column(db.Boolean, default=False)
    user = db.relationship('User', backref='bookings', lazy=True)
    showtime = db.relationship('Showtime', backref='bookings', lazy=True)

class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    movie_id = db.Column(db.Integer, db.ForeignKey("movie.id"), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship("User", backref=db.backref("reviews", lazy=True))
    movie = db.relationship("Movie", backref=db.backref("reviews", lazy=True, cascade="all, delete-orphan"))

class FoodItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    price = db.Column(db.Float, nullable=False)
    image_url = db.Column(db.String(200), default="/static/images/default-food.png")
    category = db.Column(db.String(50), default="Snacks") # e.g., Snacks, Drinks, Combo
    is_active = db.Column(db.Boolean, default=True)

# ==============================================================================
# HELPER FUNCTIONS & DECORATORS
# ==============================================================================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = session.get("user")
        if not user or user.get("role") != "admin":
            flash("Admin access is required for this page.", "danger")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return decorated_function
    
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def create_seat_layout(rows, cols, seat_categories=None):
    # Create a 2D list (grid) with plain Python
    layout = [[0 for _ in range(int(cols))] for _ in range(int(rows))]
    if seat_categories:
        for cat, positions in seat_categories.items():
            for r, c in positions:
                if 0 <= r < int(rows) and 0 <= c < int(cols):
                    if cat.lower() == "premium": layout[r][c] = 2
                    elif cat.lower() == "vip": layout[r][c] = 4
    return layout

def get_seat_type(code):
    if code in {0, 1}: return "Standard"
    if code in {2, 3}: return "Premium"
    if code in {4, 5}: return "VIP"
    return "Unknown"

def get_seat_price(showtime, seat_type):
    if seat_type == "Premium": return float(showtime.price_premium)
    if seat_type == "VIP": return float(showtime.price_vip)
    return float(showtime.price_standard)
    
def generate_ticket_pdf(booking):
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=(8*inch, 4*inch)) # Custom ticket size
    width, height = (8*inch, 4*inch)
    bg_color = colors.HexColor("#1e2a38")
    primary_color = colors.HexColor("#ffffff")
    secondary_color = colors.HexColor("#a0b0c0")
    accent_color = colors.HexColor("#ffc107")
    p.setFillColor(bg_color)
    p.rect(0, 0, width, height, fill=1, stroke=0)
    stub_width = 2.5 * inch
    p.setFillColor(colors.HexColor("#15202b"))
    p.rect(width - stub_width, 0, stub_width, height, fill=1, stroke=0)
    p.setFillColor(accent_color)
    p.rect(0, height - 0.1*inch, width, 0.1*inch, fill=1, stroke=0)
    p.setFont("Helvetica-Bold", 24)
    p.setFillColor(primary_color)
    p.drawString(0.5*inch, height - 0.7*inch, "CineBook")

    poster_path = os.path.join(os.path.dirname(__file__), booking.showtime.movie.poster_url[1:].replace('/', os.sep))
    try:
        p.drawImage(poster_path, 0.5*inch, height - 3.5*inch, width=1.5*inch, height=2.25*inch, preserveAspectRatio=True, anchor='n')
    except Exception:
        pass
    
    qr_data = f"CineBook Booking ID: {booking.id:05d}, Movie: {booking.showtime.movie.title}"
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(qr_data)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert('RGB')
    qr_buffer = BytesIO()
    qr_img.save(qr_buffer, format="jpeg")
    qr_buffer.seek(0)

    main_content_x = 2.5 * inch
    y_curr = height - 1.2 * inch
    p.setFont("Helvetica-Bold", 20)
    p.setFillColor(primary_color)
    p.drawString(main_content_x, y_curr, booking.showtime.movie.title)
    y_curr -= 0.5 * inch
    p.setFont("Helvetica", 11)
    p.setFillColor(secondary_color)
    p.drawString(main_content_x, y_curr, "THEATER")
    p.setFont("Helvetica-Bold", 12)
    p.setFillColor(primary_color)
    p.drawString(main_content_x, y_curr - 0.2*inch, f"{booking.showtime.theater.name} | Screen: {booking.showtime.hall}")
    y_curr -= 0.6 * inch
    p.setFont("Helvetica", 11)
    p.setFillColor(secondary_color)
    p.drawString(main_content_x, y_curr, "SHOWTIME")
    p.setFont("Helvetica-Bold", 12)
    p.setFillColor(primary_color)
    p.drawString(main_content_x, y_curr - 0.2*inch, booking.showtime.time.strftime('%A, %d %B %Y at %I:%M %p'))
    y_curr -= 0.6 * inch
    seats_str = ", ".join([f"R{s['row']+1}-S{s['col']+1}" for s in json.loads(booking.seats)])
    p.setFont("Helvetica", 11)
    p.setFillColor(secondary_color)
    p.drawString(main_content_x, y_curr, "SEATS")
    p.setFont("Helvetica-Bold", 12)
    p.setFillColor(primary_color)
    p.drawString(main_content_x, y_curr - 0.2*inch, seats_str)
    y_curr -= 0.6 * inch
    food_items = json.loads(booking.food_items) if booking.food_items else []
    if food_items:
        food_str = ", ".join([f"{item['name']} (x{item['quantity']})" for item in food_items])
        p.setFont("Helvetica", 11)
        p.setFillColor(secondary_color)
        p.drawString(main_content_x, y_curr, "ORDER")
        p.setFont("Helvetica-Bold", 12)
        p.setFillColor(primary_color)
        p.drawString(main_content_x, y_curr - 0.2*inch, food_str)
    
    stub_x = width - stub_width + 0.25*inch
    p.drawImage(ImageReader(qr_buffer), stub_x, height - 2.0*inch, width=2.0*inch, height=2.0*inch)
    p.setFont("Helvetica", 10)
    p.setFillColor(secondary_color)
    p.drawCentredString(width - stub_width/2, height - 2.3*inch, "BOOKING ID")
    p.setFont("Helvetica-Bold", 16)
    p.setFillColor(primary_color)
    p.drawCentredString(width - stub_width/2, height - 2.6*inch, f"{booking.id:05d}")
    p.setFont("Helvetica", 10)
    p.setFillColor(secondary_color)
    p.drawCentredString(width - stub_width/2, height - 3.0*inch, "TOTAL PAID")
    p.setFont("Helvetica-Bold", 16)
    p.setFillColor(accent_color)
    p.drawCentredString(width - stub_width/2, height - 3.3*inch, f"Rs. {booking.total_price:.2f}")

    p.showPage()
    p.save()
    buffer.seek(0)
    return buffer

def send_email(recipient, subject, html_body, pdf_attachment=None, filename=None):
    if not all([app.config.get("MAIL_USERNAME"), app.config.get("MAIL_PASSWORD")]):
        app.logger.warning("Email not configured. Skipping email dispatch.")
        return
    msg = MIMEMultipart()
    msg["From"], msg["To"], msg["Subject"] = app.config["MAIL_USERNAME"], recipient, subject
    msg.attach(MIMEText(html_body, "html"))
    if pdf_attachment and filename:
        part = MIMEApplication(pdf_attachment.read(), _subtype="pdf")
        part.add_header("Content-Disposition", "attachment", filename=filename)
        msg.attach(part)
    try:
        with smtplib.SMTP(app.config["MAIL_SERVER"], app.config["MAIL_PORT"]) as server:
            server.starttls()
            server.login(app.config["MAIL_USERNAME"], app.config["MAIL_PASSWORD"])
            server.sendmail(app.config["MAIL_USERNAME"], recipient, msg.as_string())
    except Exception as e:
        app.logger.error(f"Failed to send email to {recipient}: {e}")

@app.template_filter("to_ist")
def to_ist_filter(utc_dt):
    if not utc_dt: return None
    return utc_dt + timedelta(hours=5, minutes=30)

@app.template_filter("fromjson")
def from_json_filter(value):
    try: return json.loads(value)
    except: return {}

# ==============================================================================
# USER-FACING ROUTES
# ==============================================================================
@app.route("/")
def index():
    theaters = Theater.query.order_by(Theater.name).all()
    return render_template("index.html", theaters=theaters, user=session.get("user"))

@app.route("/theater/<int:theater_id>")
def theater_movies(theater_id):
    theater = db.get_or_404(Theater, theater_id)
    movie_ids = [st.movie_id for st in Showtime.query.filter_by(theater_id=theater_id).distinct(Showtime.movie_id)]
    movies = Movie.query.filter(Movie.id.in_(movie_ids), Movie.is_active == True).all()
    return render_template("theater_movies.html", theater=theater, movies=movies, user=session.get("user"))

@app.route("/movies")
def movies():
    search_query = request.args.get('search', '')
    selected_genre = request.args.get('genre', 'all')
    query = Movie.query.filter_by(is_active=True)
    if search_query:
        query = query.filter(Movie.title.ilike(f'%{search_query}%'))
    if selected_genre != 'all':
        query = query.filter_by(genre=selected_genre)
    movies_list = query.all()
    genres = sorted(list(set(m.genre for m in Movie.query.filter_by(is_active=True).all())))
    return render_template("movies.html", movies=movies_list, user=session.get("user"), 
                           genres=genres, selected_genre=selected_genre, search_query=search_query)

@app.route("/movie/<int:movie_id>")
def movie_detail(movie_id):
    movie = db.get_or_404(Movie, movie_id)
    theater_id = request.args.get('theater_id', type=int)
    theater = db.get_or_404(Theater, theater_id) if theater_id else None
    
    start_dt = datetime.combine(datetime.now().date(), dtime.min)
    showtimes_query = Showtime.query.filter(Showtime.movie_id == movie_id, Showtime.time >= start_dt)
    if theater:
        showtimes_query = showtimes_query.filter_by(theater_id=theater.id)
    
    showtimes = showtimes_query.order_by(Showtime.time).all()
    showtimes_by_date = {}
    for st in showtimes:
        date_str = st.time.strftime("%A, %d %B %Y")
        showtimes_by_date.setdefault(date_str, []).append(st)

    reviews = Review.query.filter_by(movie_id=movie_id).order_by(Review.created_at.desc()).all()
    avg_rating = db.session.query(db.func.avg(Review.rating)).filter_by(movie_id=movie_id).scalar() or 0
    user_review = None
    if "user_id" in session:
        user_review = Review.query.filter_by(movie_id=movie_id, user_id=session["user_id"]).first()
        
    return render_template("movie_detail.html", movie=movie, showtimes_by_date=showtimes_by_date, 
                           reviews=reviews, avg_rating=round(avg_rating, 1), user_review=user_review, 
                           user=session.get("user"), theater=theater)

@app.route("/showtime/<int:showtime_id>")
@login_required
def showtime_detail(showtime_id):
    showtime = db.get_or_404(Showtime, showtime_id)
    layout = "[]"
    if showtime.seat_layout: layout = showtime.seat_layout.layout
    return render_template("showtime.html", showtime=showtime, layout=layout, movie=showtime.movie, user=session.get("user"))

@app.route("/create-payment-intent", methods=["POST"])
@login_required
def create_payment_intent():
    try:
        data = request.get_json()
        food_items = data.get("food_items", [])
        if 'pending_booking' not in session:
            return jsonify(error={'message': 'Booking session expired'}), 400
        pending_booking = session['pending_booking']
        seat_total = float(pending_booking.get('seat_total', 0))
        food_total = sum(db.get_or_404(FoodItem, int(item['id'])).price * int(item['quantity']) for item in food_items)
        grand_total = seat_total + food_total
        pending_booking['food_items'] = food_items
        pending_booking['total_price'] = grand_total
        session['pending_booking'] = pending_booking
        intent = stripe.PaymentIntent.create(amount=int(grand_total * 100), currency='inr')
        return jsonify({'clientSecret': intent.client_secret})
    except Exception as e:
        app.logger.error(f"Error creating payment intent: {e}")
        return jsonify(error=str(e)), 403

@app.route("/payment-success")
@login_required
def payment_success():
    if 'pending_booking' not in session:
        flash("Booking session expired.", "warning")
        return redirect(url_for('index'))
    
    pb = session.pop('pending_booking')
    showtime = db.get_or_404(Showtime, int(pb["showtime_id"]))
    layout_obj = db.get_or_404(SeatLayout, showtime.id)
    layout = json.loads(layout_obj.layout)
    
    for seat in pb["seats"]:
        r, c = int(seat["row"]), int(seat["col"])
        if layout[r][c] % 2 != 0:
            flash(f"Seat R{r+1}C{c+1} was taken. Please try again.", "danger")
            return redirect(url_for('showtime_detail', showtime_id=showtime.id))
        layout[r][c] += 1
    
    layout_obj.layout = json.dumps(layout)
    booking = Booking(user_id=session["user_id"], showtime_id=showtime.id, seats=json.dumps(pb["seats"]),
                      food_items=json.dumps(pb.get('food_items', [])), total_price=pb.get('total_price', 0))
    db.session.add(booking)
    db.session.commit()
    
    user = db.session.get(User, session["user_id"])
    email_body = render_template("email/booking_confirmation.html", user=user, booking=booking)
    pdf_ticket = generate_ticket_pdf(booking)
    send_email(user.email, f"Ticket for {showtime.movie.title}", email_body, pdf_ticket, f"ticket_{booking.id}.pdf")
    
    return redirect(url_for('booking_confirmation', booking_id=booking.id))

@app.route("/booking-confirmation/<int:booking_id>")
@login_required
def booking_confirmation(booking_id):
    booking = db.get_or_404(Booking, booking_id)
    is_admin = session.get("user", {}).get("role") == "admin"
    if booking.user_id != session.get("user_id") and not is_admin:
        flash("Unauthorized access.", "danger")
        return redirect(url_for("index"))
    return render_template("booking_confirmation.html", booking=booking, user=session.get("user"))

@app.route("/my_bookings")
@login_required
def my_bookings():
    bookings = Booking.query.filter_by(user_id=session["user_id"]).order_by(Booking.booking_time.desc()).all()
    return render_template("my_bookings.html", bookings=bookings, now=datetime.utcnow(), buffer_time=timedelta(hours=2), user=session.get("user"))

@app.route("/download_ticket/<int:booking_id>")
@login_required
def download_ticket(booking_id):
    booking = db.get_or_404(Booking, booking_id)
    is_admin = session.get("user", {}).get("role") == "admin"
    if booking.user_id != session["user_id"] and not is_admin:
        flash("Unauthorized.", "danger")
        return redirect(url_for("my_bookings"))
    pdf_buffer = generate_ticket_pdf(booking)
    return send_file(pdf_buffer, as_attachment=True, download_name=f"Ticket_{booking.id}.pdf", mimetype="application/pdf")

@app.route("/booking/<int:booking_id>/cancel")
@login_required
def cancel_booking(booking_id):
    booking = db.get_or_404(Booking, booking_id)
    if booking.user_id != session["user_id"]:
        flash("Unauthorized.", "danger")
        return redirect(url_for("my_bookings"))
    if booking.showtime.time < datetime.utcnow() + timedelta(hours=2):
        flash("Cannot cancel within 2 hours of showtime.", "warning")
        return redirect(url_for("my_bookings"))
    if booking.status == 'cancelled':
        flash("Already cancelled.", "info")
        return redirect(url_for("my_bookings"))

    booking.status = "cancelled"
    layout_obj = SeatLayout.query.filter_by(showtime_id=booking.showtime_id).first()
    if layout_obj:
        layout = json.loads(layout_obj.layout)
        for seat in json.loads(booking.seats):
            r, c = int(seat["row"]), int(seat["col"])
            if layout[r][c] % 2 != 0: layout[r][c] -= 1
        layout_obj.layout = json.dumps(layout)
    db.session.commit()
    user = db.session.get(User, session["user_id"])
    email_body = render_template("email/booking_cancellation.html", user=user, booking=booking)
    send_email(user.email, f"Cancellation for {booking.showtime.movie.title}", email_body)
    flash("Booking cancelled.", "success")
    return redirect(url_for("my_bookings"))

@app.route("/booking/start", methods=["POST"])
@login_required
def start_booking():
    data = request.get_json()
    showtime = db.get_or_404(Showtime, data['showtime_id'])
    session['pending_booking'] = {'showtime_id': data['showtime_id'], 'seats': data['seats'], 'seat_total': data['total_price']}
    return jsonify({"success": True, "redirect_url": url_for('add_food_to_booking')})

@app.route("/booking/add-food")
@login_required
def add_food_to_booking():
    if 'pending_booking' not in session:
        flash("Session expired.", "warning")
        return redirect(url_for('index'))
    pb = session['pending_booking']
    showtime = db.get_or_404(Showtime, pb['showtime_id'])
    food_items = FoodItem.query.filter_by(is_active=True).order_by(FoodItem.category).all()
    return render_template("food_selection.html", user=session.get("user"), showtime=showtime,
                           pending_booking=pb, food_items=food_items, stripe_publishable_key=app.config["STRIPE_PUBLISHABLE_KEY"])

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"].strip()
        email = request.form["email"].strip().lower()
        if User.query.filter((User.username == username) | (User.email == email)).first():
            flash("Username or email already exists.", "danger")
            return redirect(url_for("register"))
        otp = random.randint(1000, 9999)
        session['registration_data'] = {
            'username': username, 'email': email, 'full_name': request.form.get("full_name"), 'phone': request.form.get("phone"),
            'password_hash': generate_password_hash(request.form["password"]), 'otp': otp,
            'otp_expiry': (datetime.utcnow() + timedelta(minutes=10)).isoformat()
        }
        email_body = render_template("email/otp_verification.html", otp=otp)
        send_email(email, "Your CineBook Verification Code", email_body)
        flash("Verification code sent to your email.", "info")
        return redirect(url_for('verify_otp'))
    return render_template("register.html")

@app.route("/verify_otp", methods=["GET", "POST"])
def verify_otp():
    if 'registration_data' not in session:
        flash("Please register first.", "warning")
        return redirect(url_for('register'))
    reg_data = session['registration_data']
    if request.method == "POST":
        if datetime.utcnow() > datetime.fromisoformat(reg_data['otp_expiry']):
            session.pop('registration_data', None)
            flash("OTP expired. Please register again.", "danger")
            return redirect(url_for('register'))
        if request.form.get("otp") and int(request.form.get("otp")) == reg_data['otp']:
            user = User(username=reg_data['username'], email=reg_data['email'], full_name=reg_data.get('full_name'),
                        phone=reg_data.get('phone'), password_hash=reg_data['password_hash'])
            db.session.add(user)
            db.session.commit()
            session.pop('registration_data', None)
            flash("Account created! Please log in.", "success")
            return redirect(url_for("login"))
        else:
            flash("Invalid OTP.", "danger")
    return render_template("verify_otp.html", email=reg_data.get('email'))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = User.query.filter_by(username=request.form["username"]).first()
        if user and user.check_password(request.form["password"]):
            session["user_id"] = user.id
            session["user"] = {"id": user.id, "username": user.username, "role": user.role, "avatar": user.avatar}
            return redirect(url_for("index"))
        flash("Invalid credentials.", "danger")
    return render_template("login.html")

@app.route("/login/google")
def login_google():
    return oauth.google.authorize_redirect(url_for("authorize_google", _external=True))

@app.route("/authorize/google")
def authorize_google():
    try:
        token = oauth.google.authorize_access_token()
        user_info = token.get('userinfo')
        if not user_info:
            flash("Google login failed.", "danger")
            return redirect(url_for("login"))
        user = User.query.filter_by(email=user_info['email']).first()
        if not user:
            user = User(username=user_info['email'].split('@')[0], email=user_info['email'], full_name=user_info.get('name'),
                        avatar=user_info.get('picture'), provider='google')
            db.session.add(user)
            db.session.commit()
        session["user_id"] = user.id
        session["user"] = {"id": user.id, "username": user.username, "role": user.role, "avatar": user.avatar}
        return redirect(url_for("index"))
    except Exception as e:
        app.logger.error(f"Google Auth Error: {e}")
        flash("Google authentication failed.", "danger")
        return redirect(url_for("login"))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        user = User.query.filter_by(email=request.form.get("email")).first()
        if user:
            token = secrets.token_urlsafe(32)
            user.reset_token = token
            user.reset_token_expiry = datetime.utcnow() + timedelta(hours=1)
            db.session.commit()
            reset_url = url_for('reset_password', token=token, _external=True)
            email_body = render_template("email/password_reset.html", reset_url=reset_url, user=user)
            send_email(user.email, "Reset Your CineBook Password", email_body)
        flash("If an account exists, a reset link has been sent.", "info")
        return redirect(url_for("login"))
    return render_template("forgot_password.html")

@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    user = User.query.filter_by(reset_token=token).filter(User.reset_token_expiry > datetime.utcnow()).first()
    if not user:
        flash("Invalid or expired reset link.", "danger")
        return redirect(url_for("login"))
    if request.method == "POST":
        if request.form.get("new_password") != request.form.get("confirm_password"):
            flash("Passwords do not match.", "danger")
            return render_template("reset_password.html", token=token)
        user.set_password(request.form.get("new_password"))
        user.reset_token = None
        user.reset_token_expiry = None
        db.session.commit()
        flash("Password updated! Please log in.", "success")
        return redirect(url_for("login"))
    return render_template("reset_password.html", token=token)

@app.route("/profile")
@login_required
def profile():
    user = db.session.get(User, session["user_id"])
    bookings = Booking.query.filter_by(user_id=user.id).order_by(Booking.booking_time.desc()).all()
    reviews = Review.query.filter_by(user_id=user.id).order_by(Review.created_at.desc()).all()
    return render_template("profile.html", user=user, bookings=bookings, reviews=reviews)

@app.route("/profile/edit", methods=["POST"])
@login_required
def edit_profile():
    user = db.session.get(User, session["user_id"])
    user.full_name = request.form.get("full_name")
    user.phone = request.form.get("phone")
    if 'avatar' in request.files:
        file = request.files['avatar']
        if file and allowed_file(file.filename):
            filename = f"user_{user.id}_{secure_filename(file.filename)}"
            avatar_path = os.path.join(app.config['UPLOAD_FOLDER'], 'avatars', filename)
            file.save(avatar_path)
            user.avatar = url_for('static', filename=f'uploads/avatars/{filename}')
    db.session.commit()
    session["user"]["avatar"] = user.avatar
    session.modified = True
    flash("Profile updated.", "success")
    return redirect(url_for("profile"))

@app.route("/profile/change_password", methods=["POST"])
@login_required
def change_password():
    user = db.session.get(User, session["user_id"])
    if not user.check_password(request.form.get("current_password")):
        flash("Incorrect current password.", "danger")
        return redirect(url_for("profile"))
    if request.form.get("new_password") != request.form.get("confirm_password"):
        flash("New passwords don't match.", "danger")
        return redirect(url_for("profile"))
    user.set_password(request.form.get("new_password"))
    db.session.commit()
    flash("Password changed.", "success")
    return redirect(url_for("profile"))

@app.route("/movie/<int:movie_id>/review", methods=["POST"])
@login_required
def add_review(movie_id):
    theater_id = request.args.get('theater_id')
    redirect_url = url_for("movie_detail", movie_id=movie_id, theater_id=theater_id)
    rating = request.form.get("rating", type=int)
    comment = request.form.get("comment", "").strip()
    if not rating or not comment:
        flash("Rating and comment are required.", "danger")
        return redirect(redirect_url)
    existing_review = Review.query.filter_by(movie_id=movie_id, user_id=session["user_id"]).first()
    if existing_review:
        existing_review.rating, existing_review.comment = rating, comment
        flash("Review updated.", "success")
    else:
        db.session.add(Review(user_id=session["user_id"], movie_id=movie_id, rating=rating, comment=comment))
        flash("Review submitted!", "success")
    db.session.commit()
    return redirect(redirect_url)

# ==============================================================================
# ADMIN ROUTES
# ==============================================================================
@app.route("/admin")
@admin_required
def admin_dashboard():
    total_movies = Movie.query.count()
    total_bookings = Booking.query.count()
    total_users = User.query.count()
    total_revenue = db.session.query(db.func.sum(Booking.total_price)).filter(Booking.status == 'confirmed').scalar() or 0
    recent_bookings = Booking.query.order_by(Booking.booking_time.desc()).limit(5).all()
    return render_template("admin/dashboard.html", total_movies=total_movies, total_bookings=total_bookings,
                           total_users=total_users, total_revenue=round(total_revenue, 2), 
                           recent_bookings=recent_bookings, user=session.get("user"))

@app.route("/admin/movies")
@admin_required
def admin_movies():
    movies = Movie.query.all()
    return render_template("admin/movies.html", movies=movies, user=session.get("user"))

@app.route("/admin/movies/add", methods=['GET', 'POST'])
@admin_required
def admin_add_movie():
    if request.method == 'POST':
        title = request.form.get('title')
        if Movie.query.filter_by(title=title).first():
            flash('Movie with this title already exists.', 'danger')
            return redirect(url_for('admin_add_movie'))
        poster_url = "/static/images/default-poster.png"
        if 'poster' in request.files:
            file = request.files['poster']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                poster_url = url_for('static', filename=f'uploads/{filename}')
        new_movie = Movie(
            title=title, genre=request.form.get('genre'), duration=request.form.get('duration', type=int),
            language=request.form.get('language'), rating=request.form.get('rating', type=float),
            director=request.form.get('director'), cast=json.dumps([c.strip() for c in request.form.get('cast', '').split(',')]),
            trailer_url=request.form.get('trailer_url'), description=request.form.get('description'), poster_url=poster_url)
        db.session.add(new_movie)
        db.session.commit()
        flash('Movie added successfully!', 'success')
        return redirect(url_for('admin_movies'))
    return render_template("admin/add_movie.html", user=session.get("user"))

@app.route('/admin/movies/edit/<int:movie_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_movie(movie_id):
    movie = db.get_or_404(Movie, movie_id)
    if request.method == 'POST':
        movie.title = request.form.get('title')
        movie.genre = request.form.get('genre')
        movie.duration = request.form.get('duration', type=int)
        movie.description = request.form.get('description')
        movie.language = request.form.get('language')
        movie.rating = request.form.get('rating', type=float)
        movie.director = request.form.get('director')
        movie.cast = json.dumps([c.strip() for c in request.form.get('cast', '').split(',')])
        movie.trailer_url = request.form.get('trailer_url')
        movie.is_active = 'is_active' in request.form

        if 'poster' in request.files:
            file = request.files['poster']
            if file and file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                movie.poster_url = url_for('static', filename=f'uploads/{filename}')
        
        db.session.commit()
        flash('Movie updated successfully.', 'success')
        return redirect(url_for('admin_movies'))
        
    return render_template('admin/edit_movie.html', movie=movie, user=session.get("user"))

@app.route('/admin/movies/delete/<int:movie_id>', methods=['POST'])
@admin_required
def admin_delete_movie(movie_id):
    movie = db.get_or_404(Movie, movie_id)
    db.session.delete(movie)
    db.session.commit()
    flash('Movie has been deleted.', 'success')
    return redirect(url_for('admin_movies'))

@app.route("/admin/showtimes")
@admin_required
def admin_showtimes():
    showtimes = Showtime.query.order_by(Showtime.time.desc()).all()
    return render_template("admin/showtimes.html", showtimes=showtimes, user=session.get("user"))

@app.route("/admin/showtimes/add", methods=['GET', 'POST'])
@admin_required
def admin_add_showtime():
    if request.method == 'POST':
        showtime = Showtime(
            movie_id=request.form.get('movie_id', type=int),
            theater_id=request.form.get('theater_id', type=int),
            time=datetime.fromisoformat(request.form.get('time')),
            hall=request.form.get('hall'),
            rows=request.form.get('rows', type=int),
            cols=request.form.get('cols', type=int),
            price_standard=request.form.get('price_standard', type=float),
            price_premium=request.form.get('price_premium', type=float),
            price_vip=request.form.get('price_vip', type=float))
        db.session.add(showtime)
        db.session.flush()
        layout_data = create_seat_layout(showtime.rows, showtime.cols)
        seat_layout = SeatLayout(showtime_id=showtime.id, layout=json.dumps(layout_data))
        db.session.add(seat_layout)
        db.session.commit()
        flash('Showtime added successfully!', 'success')
        return redirect(url_for('admin_showtimes'))
    movies = Movie.query.filter_by(is_active=True).all()
    theaters = Theater.query.all()
    return render_template("admin/add_showtime.html", movies=movies, theaters=theaters, user=session.get("user"))

@app.route('/admin/showtimes/edit/<int:showtime_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_showtime(showtime_id):
    showtime = db.get_or_404(Showtime, showtime_id)
    if request.method == 'POST':
        showtime.movie_id = request.form.get('movie_id', type=int)
        showtime.theater_id = request.form.get('theater_id', type=int)
        showtime.time = datetime.fromisoformat(request.form.get('time'))
        showtime.hall = request.form.get('hall')
        showtime.price_standard = request.form.get('price_standard', type=float)
        showtime.price_premium = request.form.get('price_premium', type=float)
        showtime.price_vip = request.form.get('price_vip', type=float)
        db.session.commit()
        flash('Showtime updated successfully!', 'success')
        return redirect(url_for('admin_showtimes'))
    movies = Movie.query.filter_by(is_active=True).all()
    theaters = Theater.query.all()
    return render_template('admin/edit_showtime.html', showtime=showtime, movies=movies, theaters=theaters, user=session.get("user"))

@app.route('/admin/showtimes/delete/<int:showtime_id>', methods=['POST'])
@admin_required
def admin_delete_showtime(showtime_id):
    showtime = db.get_or_404(Showtime, showtime_id)
    db.session.delete(showtime)
    db.session.commit()
    flash('Showtime has been deleted.', 'success')
    return redirect(url_for('admin_showtimes'))

@app.route("/admin/bookings")
@admin_required
def admin_bookings():
    bookings = Booking.query.order_by(Booking.booking_time.desc()).all()
    return render_template("admin/bookings.html", bookings=bookings, user=session.get("user"))

@app.route('/admin/bookings/cancel/<int:booking_id>', methods=['POST'])
@admin_required
def admin_cancel_booking(booking_id):
    booking = db.get_or_404(Booking, booking_id)
    if booking.status != 'cancelled':
        booking.status = 'cancelled'
        layout_obj = SeatLayout.query.filter_by(showtime_id=booking.showtime_id).first()
        if layout_obj:
            layout = json.loads(layout_obj.layout)
            for seat in json.loads(booking.seats):
                r, c = int(seat["row"]), int(seat["col"])
                if layout[r][c] % 2 != 0: layout[r][c] -= 1
            layout_obj.layout = json.dumps(layout)
        db.session.commit()
        flash(f"Booking #{booking.id} has been cancelled.", 'success')
    else:
        flash(f"Booking #{booking.id} was already cancelled.", 'info')
    return redirect(url_for('admin_bookings'))

@app.route("/admin/users")
@admin_required
def admin_users():
    users = User.query.all()
    return render_template("admin/users.html", users=users, user=session.get("user"))

@app.route('/admin/users/delete/<int:user_id>', methods=['POST'])
@admin_required
def admin_delete_user(user_id):
    user = db.get_or_404(User, user_id)
    if user.role == 'admin':
        flash('Cannot delete an admin account.', 'danger')
        return redirect(url_for('admin_users'))
    db.session.delete(user)
    db.session.commit()
    flash('User has been deleted.', 'success')
    return redirect(url_for('admin_users'))

@app.route("/admin/get-booking-details/<int:booking_id>")
@admin_required
def admin_get_booking_details(booking_id):
    booking = Booking.query.get(booking_id)
    return render_template("admin/booking_details_partial.html", booking=booking)

@app.route("/admin/mark-attended/<int:booking_id>", methods=["POST"])
@admin_required
def admin_mark_attended(booking_id):
    booking = db.get_or_404(Booking, booking_id)
    if not booking.attended:
        booking.attended = True
        db.session.commit()
        flash(f"Booking ID {booking.id:05d} marked as attended.", "success")
    else:
        flash(f"Booking ID {booking.id:05d} already marked as attended.", "warning")
    return redirect(url_for('admin_verify_ticket', booking_id=booking_id))

@app.route("/admin/verify-ticket", methods=["GET", "POST"])
@admin_required
def admin_verify_ticket():
    booking = None
    booking_id = request.args.get('booking_id')
    if request.method == "POST":
        booking_id = request.form.get("booking_id")
    if booking_id:
        booking = Booking.query.get(int(booking_id))
        if not booking:
            flash(f"Booking ID {booking_id} not found.", "danger")
    return render_template("admin/verify_ticket.html", user=session.get("user"), booking=booking)

@app.route("/admin/food")
@admin_required
def admin_food_items():
    items = FoodItem.query.all()
    return render_template("admin/food_items.html", items=items, user=session.get("user"))

@app.route("/admin/food/add", methods=['GET', 'POST'])
@admin_required
def admin_add_food_item():
    if request.method == 'POST':
        new_item = FoodItem(name=request.form.get('name'), description=request.form.get('description'),
                            price=request.form.get('price', type=float), category=request.form.get('category'),
                            is_active='is_active' in request.form)
        db.session.add(new_item)
        db.session.commit()
        flash('Food item added.', 'success')
        return redirect(url_for('admin_food_items'))
    return render_template("admin/add_edit_food_item.html", action="Add", item=None, user=session.get("user"))

@app.route("/admin/food/edit/<int:item_id>", methods=['GET', 'POST'])
@admin_required
def admin_edit_food_item(item_id):
    item = db.get_or_404(FoodItem, item_id)
    if request.method == 'POST':
        item.name, item.description = request.form.get('name'), request.form.get('description')
        item.price, item.category = request.form.get('price', type=float), request.form.get('category')
        item.is_active = 'is_active' in request.form
        db.session.commit()
        flash('Food item updated.', 'success')
        return redirect(url_for('admin_food_items'))
    return render_template("admin/add_edit_food_item.html", action="Edit", item=item, user=session.get("user"))

@app.route("/admin/food/delete/<int:item_id>", methods=['POST'])
@admin_required
def admin_delete_food_item(item_id):
    item = db.get_or_404(FoodItem, item_id)
    db.session.delete(item)
    db.session.commit()
    flash('Food item deleted.', 'success')
    return redirect(url_for('admin_food_items'))

# ==============================================================================
# DATABASE INITIALIZATION & APP EXECUTION
# ==============================================================================
def init_db():
    if Theater.query.count() > 0: 
        return
        
    print("Seeding database with initial data...")
    theaters_data = [
        Theater(name="ARRS Multiplex", address="2/1, Omalur Main Road, Near New Bus Stand", city="Salem", image_url="/static/images/theaters/arrs.jpg"),
        Theater(name="INOX Cinemas", address="Reliance Mall, Omalur Main Road", city="Salem", image_url="/static/images/theaters/inox.jpg"),
        Theater(name="Kailash Prakash Theatre", address="Trichy Main Road, Dadagapatti", city="Salem", image_url="/static/images/theaters/kailash.jpg"),
        Theater(name="Sapna Cinemas", address="Four Roads", city="Salem", image_url="/static/images/theaters/sapna.jpg"),
        Theater(name="Santham Theatre", address="Omalur Main Road", city="Salem", image_url="/static/images/theaters/santham.jpg"),
    ]
    db.session.bulk_save_objects(theaters_data)
    db.session.commit()
    
    admin = User(username="admin", email="admin@app.com", role="admin")
    admin.set_password("admin")
    user1 = User(username="testuser", email="user@app.com", role="user")
    user1.set_password("password")
    db.session.add_all([admin, user1])
    
    movies_data = [
        Movie(title="Avatar: The Way of Water", genre="Sci-Fi", duration=192, rating=8.5, description="Jake Sully and Ney'tiri have formed a family...", poster_url="/static/images/avatar.jpg", cast=json.dumps(["Sam Worthington", "Zoe Saldaña"]), director="James Cameron"),
        Movie(title="John Wick: Chapter 4", genre="Action", duration=169, rating=8.2, description="John Wick takes his fight against the High Table global...", poster_url="/static/images/johnwick.jpg", cast=json.dumps(["Keanu Reeves", "Donnie Yen"]), director="Chad Stahelski"),
        Movie(title="Oppenheimer", genre="Biographical", duration=180, rating=9.0, description="The story of American scientist J. Robert Oppenheimer...", poster_url="/static/images/oppenheimer.jpg", cast=json.dumps(["Cillian Murphy", "Emily Blunt"]), director="Christopher Nolan"),
        Movie(title="The Super Mario Bros. Movie", genre="Animation", duration=92, rating=7.8, description="The story of The Super Mario Bros. on their journey through the Mushroom Kingdom.", poster_url="/static/images/mario.jpg", cast=json.dumps(["Chris Pratt", "Anya Taylor-Joy"]), director="Aaron Horvath"),
    ]
    db.session.bulk_save_objects(movies_data)
    db.session.commit() 

    movies = Movie.query.all()
    theaters = Theater.query.all()
    halls = ["Screen 1", "Screen 2", "Screen 3", "Audi 1"]
    today = datetime.now().date()
    
    for i in range(3):
        current_date = today + timedelta(days=i)
        for theater in theaters:
            movies_for_theater = random.sample(movies, k=random.randint(2, 3))
            for movie in movies_for_theater:
                showtime_times = [dtime(10, 30), dtime(14, 0), dtime(18, 30), dtime(22, 0)]
                for st_time in showtime_times:
                    showtime_dt = datetime.combine(current_date, st_time)
                    
                    showtime = Showtime(movie_id=movie.id, theater_id=theater.id, time=showtime_dt, hall=random.choice(halls), rows=8, cols=12, price_standard=180.0, price_premium=250.0, price_vip=400.0)
                    db.session.add(showtime)
                    db.session.flush()
                    
                    seat_categories = {
                        "premium": [(r, c) for r in range(5, 7) for c in range(showtime.cols)],
                        "vip": [(r, c) for r in range(7, 8) for c in range(showtime.cols)]
                    }
                    layout_data = create_seat_layout(showtime.rows, showtime.cols, seat_categories=seat_categories)
                    seat_layout = SeatLayout(showtime_id=showtime.id, layout=json.dumps(layout_data))
                    db.session.add(seat_layout)

    db.session.commit()
    print("Database seeded successfully.")
    
    if FoodItem.query.count() == 0:
        print("Seeding database with initial food items...")
        food_data = [
            FoodItem(name="Salted Popcorn (Large)", description="Classic salted popcorn.", price=180.00, category="Snacks", image_url="/static/images/food/popcorn.jpg"),
            FoodItem(name="Caramel Popcorn (Large)", description="Sweet and crunchy caramel popcorn.", price=220.00, category="Snacks", image_url="/static/images/food/caramel-popcorn.jpg"),
            FoodItem(name="Nachos with Cheese Dip", description="Crispy nachos served with a warm cheese dip.", price=160.00, category="Snacks", image_url="/static/images/food/nachos.jpg"),
            FoodItem(name="Coca-Cola (500ml)", description="Chilled soft drink.", price=90.00, category="Drinks", image_url="/static/images/food/coke.jpg"),
            FoodItem(name="Pepsi (500ml)", description="Chilled soft drink.", price=90.00, category="Drinks", image_url="/static/images/food/pepsi.jpg"),
            FoodItem(name="Classic Combo", description="1 Salted Popcorn + 1 Coke", price=250.00, category="Combo", image_url="/static/images/food/combo.jpg"), 
        ]
        db.session.bulk_save_objects(food_data)
        
    db.session.commit()
    print("Database seeded successfully.")    

if __name__ == "__main__":
    with app.app_context():        
        db.create_all()
        init_db()
 