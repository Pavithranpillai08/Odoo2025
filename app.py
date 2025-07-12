import math
import os
from flask import Flask, render_template, url_for, flash, request, redirect, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_migrate import Migrate
from flask_socketio import SocketIO
from flask_cors import CORS
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secretkey1234'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///skillswapf.db'
db = SQLAlchemy(app)
migrate = Migrate(app, db)

CORS(app)
socketio = SocketIO(app, cors_allowed_origins="")

# Gemini AI config
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-1.5-flash")

# User model
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    uname = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

    user_skills = db.relationship('UserSkill', backref='user', lazy=True)

    def __repr__(self):
        return f"{self.uname}, {self.email}"

class UserSkill(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    skill = db.Column(db.String(100), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class SwapRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(20), default="pending")

    sender = db.relationship('User', foreign_keys=[sender_id], backref='sent_requests')
    receiver = db.relationship('User', foreign_keys=[receiver_id], backref='received_requests')

# DB setup
with app.app_context():
    try:
        db.create_all()
        db.session.commit()
        print("\u2705 Database created successfully")
    except Exception as e:
        print(f"❌ Error creating database: {e}")

@app.before_request
def debug_requests():
    print(f"[DEBUG] Route: {request.path}, Method: {request.method}, Session: {dict(session)}")

@app.route('/add-skill', methods=['POST'])
def add_user_skill():
    if 'id' not in session:
        flash("Please login")
        return redirect(url_for('login'))
    try:
        skill = request.form.get('skill')
        if skill:
            skill = skill.strip().lower()
            existing = UserSkill.query.filter_by(skill=skill, user_id=session['id']).first()
            if existing:
                flash("Skill already added")
                return redirect(url_for('profile'))
            new_skill = UserSkill(skill=skill, user_id=session['id'])
            db.session.add(new_skill)
            db.session.commit()
            flash("Skill added")
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error adding skill: {e}")
        flash("An error occurred while adding skill.")
    return redirect(url_for('profile'))

@app.route('/delete-skill/<int:skill_id>', methods=['POST'])
def delete_skill(skill_id):
    if 'id' not in session:
        flash("Please login")
        return redirect(url_for('login'))
    try:
        skill = UserSkill.query.get_or_404(skill_id)
        if skill.user_id == session['id']:
            db.session.delete(skill)
            db.session.commit()
            flash("Skill removed")
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error deleting skill: {e}")
        flash("An error occurred while removing skill.")
    return redirect(url_for('profile'))

@app.route('/send-swap-request/<int:user_id>', methods=['POST'])
def send_swap_request(user_id):
    if 'id' not in session:
        flash("Please login to send a swap request")
        return redirect(url_for('login'))
    try:
        existing = SwapRequest.query.filter_by(sender_id=session['id'], receiver_id=user_id).first()
        if existing:
            flash("Swap request already sent")
        else:
            swap = SwapRequest(sender_id=session['id'], receiver_id=user_id)
            db.session.add(swap)
            db.session.commit()
            flash("Swap request sent!")
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error sending swap request: {e}")
        flash("Error sending swap request.")
    return redirect(url_for('view_user_profile', user_id=user_id))

@app.route('/accept-swap/<int:request_id>', methods=['POST'])
def accept_swap(request_id):
    if 'id' not in session:
        flash("Please login to accept swap requests")
        return redirect(url_for('login'))
    try:
        swap = SwapRequest.query.get_or_404(request_id)
        if swap.receiver_id != session['id']:
            flash("Unauthorized action.")
            return redirect(url_for('profile'))
        swap.status = 'accepted'
        db.session.commit()
        flash("Swap request accepted!")
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error accepting swap request: {e}")
        flash("Error accepting request.")
    return redirect(url_for('profile'))

@app.route("/", methods=["GET", "POST"])
def landing():
    current_user_id = session.get('id')
    try:
        if request.method == "POST":
            keyword = request.form.get("keyword", "").strip().lower()
            searched = keyword
            if keyword:
                results = db.session.query(User).join(UserSkill).filter(UserSkill.skill.ilike(f"%{keyword}%"))
                results = results.filter(User.id != current_user_id).all()
            else:
                results = []
            return render_template("landing.html", results=results, searched=searched, id=current_user_id)
        return render_template("landing.html", results=[], searched="", id=current_user_id)
    except Exception as e:
        print(f"❌ Error in landing page: {e}")
        flash("Something went wrong.")
        return render_template("landing.html", results=[], searched="", id=current_user_id)

@app.route('/meet/<int:user_id>')
def meet(user_id):
    current_id = session.get('id')
    if not current_id:
        flash("Please log in")
        return redirect(url_for('login'))
    try:
        accepted = SwapRequest.query.filter(
            ((SwapRequest.sender_id == current_id) & (SwapRequest.receiver_id == user_id)) |
            ((SwapRequest.sender_id == user_id) & (SwapRequest.receiver_id == current_id)),
            SwapRequest.status == 'accepted'
        ).first()
        if not accepted:
            flash("Meeting not allowed without accepted swap")
            return redirect(url_for('profile'))
        room = f"skillswap_{min(current_id, user_id)}_{max(current_id, user_id)}"
        return render_template('meet.html', room=room)
    except Exception as e:
        print(f"❌ Error in meeting route: {e}")
        flash("Error opening meeting page.")
        return redirect(url_for('profile'))

@app.route("/ai", methods=["GET", "POST"])
def chat():
    reply = ""
    if request.method == "POST":
        try:
            user_input = request.form.get("message")
            if user_input:
                response = model.generate_content(user_input)
                reply = response.text
        except Exception as e:
            print(f"❌ Gemini AI Error: {e}")
            flash("Gemini AI is currently unavailable.")
    return render_template("chat.html", reply=reply)

@app.route('/profile')
def profile():
    if 'id' not in session:
        flash("Please login to access your profile")
        return redirect(url_for('login'))
    try:
        user = User.query.get(session['id'])
        pending_sent = SwapRequest.query.filter_by(sender_id=user.id, status='pending').all()
        pending_received = SwapRequest.query.filter_by(receiver_id=user.id, status='pending').all()
        accepted_requests = SwapRequest.query.filter(
            ((SwapRequest.sender_id == user.id) | (SwapRequest.receiver_id == user.id)) &
            (SwapRequest.status == 'accepted')
        ).all()
        return render_template('profile.html', user=user, pending_sent=pending_sent, pending_received=pending_received, accepted_requests=accepted_requests, current_user=user)
    except Exception as e:
        print(f"❌ Error in profile route: {e}")
        flash("Unable to load profile.")
        return redirect(url_for('index'))

@app.route('/user/<int:user_id>')
def view_user_profile(user_id):
    try:
        user = User.query.get_or_404(user_id)
        skills = UserSkill.query.filter_by(user_id=user.id).all()
        already_sent = False
        if 'id' in session:
            already_sent = SwapRequest.query.filter_by(sender_id=session['id'], receiver_id=user_id).first() is not None
        return render_template('user_profile.html', user=user, skills=skills, id=session.get('id'), already_sent=already_sent)
    except Exception as e:
        print(f"❌ Error loading user profile: {e}")
        flash("Could not load user profile.")
        return redirect(url_for('landing'))

@app.route('/index')
def index():
    if 'id' not in session:
        flash("Please login to access the dashboard")
        return redirect(url_for('login'))
    uname = session.get('uname')
    login_id = session.get('id')
    return render_template('landing.html', id=login_id, uname=uname)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        try:
            email = request.form.get('email')
            password = request.form.get('password')
            user = User.query.filter_by(email=email).first()
            if not user or not check_password_hash(user.password, password):
                flash('Invalid details')
                return redirect(url_for('login'))
            session.clear()
            session['id'] = user.id
            session['email'] = user.email
            session['uname'] = user.uname
            session.modified = True
            flash("Login successful")
            return redirect(url_for('index'))
        except Exception as e:
            print(f"❌ Login Error: {e}")
            flash("Login failed due to an internal error.")
            return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        try:
            uname = request.form['uname']
            email = request.form['email']
            password = request.form['password']
            hashed_password = generate_password_hash(password)
            existing_user = User.query.filter_by(email=email).first()
            if existing_user:
                flash("User already exists!")
                return redirect(url_for('register'))
            new_user = User(uname=uname, email=email, password=hashed_password)
            db.session.add(new_user)
            db.session.commit()
            session['id'] = new_user.id
            session['email'] = new_user.email
            session['uname'] = new_user.uname
            session['first_time'] = True
            session.modified = True
            flash("Welcome! Complete your profile.")
            return redirect(url_for('profile'))
        except Exception as e:
            db.session.rollback()
            print(f"❌ Error during registration: {e}")
            flash("An error occurred during registration. Please try again.")
            return redirect(url_for('register'))
    return render_template('register.html')

@app.route('/logout', methods=['GET', 'POST'])
def logout():
    session.clear()
    flash("You have been logged out", "info")
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)
