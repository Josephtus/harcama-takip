from flask import Flask, render_template, redirect, url_for, request, flash, session
from flask_login import LoginManager, login_user, logout_user, current_user, login_required, UserMixin
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func
from sqlalchemy import Text
from datetime import datetime
import cloudinary
import cloudinary.uploader
import cloudinary.api
import os
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

# Yapılandırmalar
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///database.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'yusuf123')
app.config['UPLOAD_FOLDER'] = 'static/uploads'
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True
)

# Eklentiler
db = SQLAlchemy(app)
migrate = Migrate(app, db)
login_manager = LoginManager(app)
login_manager.login_view = "login"

# Veritabanı Modelleri
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.Text, unique=True, nullable=False)
    password_hash = db.Column(db.Text, nullable=False)
    person = db.relationship('Person', backref='user', uselist=False)
    

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Person(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    is_admin = db.Column(db.Boolean, default=False)

class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    date = db.Column(db.Date, nullable=False)
    receipt_filename = db.Column(db.String(255), nullable=True)
    paid_by_id = db.Column(db.Integer, db.ForeignKey('person.id'), nullable=False)
    owed_to_id = db.Column(db.Integer, db.ForeignKey('person.id'), nullable=True)
    payer_id = db.Column(db.Integer, db.ForeignKey('person.id'), nullable=False)
    is_paid = db.Column(db.Boolean, default=False)

    payer = db.relationship('Person', backref='expenses_paid', foreign_keys=[payer_id])
    paid_by = db.relationship('Person', foreign_keys=[paid_by_id])
    owed_to = db.relationship('Person', foreign_keys=[owed_to_id])

class ExpenseShare(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    expense_id = db.Column(db.Integer, db.ForeignKey('expense.id'), nullable=False)
    person_id = db.Column(db.Integer, db.ForeignKey('person.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    is_paid = db.Column(db.Boolean, default=False)

    expense = db.relationship('Expense', backref='shares')
    person = db.relationship('Person')

# Kullanıcı yükleyici
@login_manager.user_loader
def load_user(user_id):
    return Person.query.get(int(user_id))

# Kayıt
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if User.query.filter_by(username=username).first():
            flash('Bu kullanıcı adı zaten var.')
            return redirect('/register')
        user = User(username=username)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        person = Person(name=username, user_id=user.id)
        db.session.add(person)
        db.session.commit()

        flash('Kayıt başarılı! Giriş yapabilirsiniz.')
        return redirect('/login')
    return render_template('register.html')

# Giriş
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            person = Person.query.filter_by(user_id=user.id).first()
            if person:
                login_user(person)
                return redirect(request.args.get('next') or '/')
            flash("Person kaydı bulunamadı.")
        else:
            flash('Kullanıcı adı veya şifre yanlış.')
    return render_template('login.html')

# Çıkış
@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Çıkış yapıldı.')
    return redirect('/login')

# Ana sayfa
@app.route("/")
@login_required
def index():
    per_page = 10
    total_expenses = Expense.query.count()
    last_page = (total_expenses - 1) // per_page + 1

    page = request.args.get('page', type=int) or last_page
    expenses_pagination = Expense.query.order_by(Expense.date.desc()).paginate(page=page, per_page=per_page, error_out=False)
    persons = Person.query.filter_by(is_admin=False).all()

    return render_template("index.html", username=current_user.name, persons=persons, expenses=expenses_pagination.items, pagination=expenses_pagination)

# Kullanıcı yönetimi (admin)
@app.route('/admin/users')
@login_required
def admin_users():
    if not current_user.is_admin:
        flash("Bu sayfaya erişim yetkiniz yok.")
        return redirect(url_for('index'))
    persons = Person.query.filter_by(is_admin=False).all()
    return render_template('admin_users.html', persons=persons)

@app.route('/admin/delete_user/<int:user_id>', methods=['POST'])
@login_required
def admin_delete_user(user_id):
    if not current_user.is_admin:
        flash("Bu işlemi yapmaya yetkiniz yok.")
        return redirect(url_for('index'))

    user = User.query.get_or_404(user_id)
    person = Person.query.filter_by(user_id=user.id).first()

    if person and person.is_admin:
        flash("Admin kullanıcı silinemez.")
        return redirect(url_for('admin_users'))

    if person:
        # Kullanıcının yaptığı harcamalar ve paylaşımları sil
        user_expenses = Expense.query.filter_by(payer_id=person.id).all()
        for exp in user_expenses:
            ExpenseShare.query.filter_by(expense_id=exp.id).delete()
            db.session.delete(exp)

        ExpenseShare.query.filter_by(person_id=person.id).delete()
        db.session.delete(person)

    db.session.delete(user)
    db.session.commit()

    flash(f"{user.username} adlı kullanıcı ve ilişkili kayıtlar silindi.")
    return redirect(url_for('admin_users'))


# Harcama ekle
@app.route("/add_expense", methods=["GET", "POST"])
@login_required
def add_expense():
    persons = Person.query.filter_by(is_admin=False).all()
    if request.method == "POST":
        description = request.form["description"]
        amount = float(request.form["amount"])
        date_str = request.form["date"]
        date = datetime.strptime(date_str, "%Y-%m-%d").date()
        is_paid = request.form.get("is_paid") == "on"
        owed_to_id = int(request.form.get("owed_to")) if request.form.get("owed_to") else None

        person = current_user

        if not person:
            flash("Person kaydı bulunamadı!")
            return redirect("/")

        file = request.files.get("receipt")
        filename = None
        if file and file.filename:
        # Cloudinary'ye yükle
            upload_result = cloudinary.uploader.upload(file)
            filename = upload_result.get("secure_url")  # Bu URL'i kaydet


        expense = Expense(
            description=description,
            amount=amount,
            date=date,
            receipt_filename=filename,
            paid_by_id=person.id,
            payer_id=person.id,
            owed_to_id=owed_to_id,
            is_paid=is_paid
        )
        db.session.add(expense)
        db.session.commit()

        share_amount = round(amount / len(persons), 2)
        for p in persons:
            if p.id != person.id:
                db.session.add(ExpenseShare(expense_id=expense.id, person_id=p.id, amount=share_amount))
        db.session.commit()

        return redirect("/")
    return render_template("add_expense.html", persons=persons)


# Harcama sil
@app.route('/delete_expense/<int:expense_id>', methods=['POST'])
@login_required
def delete_expense(expense_id):
    expense = Expense.query.get_or_404(expense_id)
    if expense.payer_id != current_user.id:
        flash("Bu harcamayı silmek için yetkiniz yok.")
        return redirect(url_for('index'))

    ExpenseShare.query.filter_by(expense_id=expense.id).delete()
    db.session.delete(expense)
    db.session.commit()
    flash("Harcama başarıyla silindi.")
    return redirect(url_for('index'))

# Borç sayfası
@app.route('/debts')
@login_required
def debts():
    user_id = current_user.id
    people = User.query.all()
    person_map = {p.person.id: p.username for p in people if p.id != user_id}
    shares = ExpenseShare.query.all()

    net_balances, detailed_shares = {}, {}
    for s in shares:
        if s.is_paid or s.expense is None or s.expense.payer_id == s.person_id:
            continue
        key = (s.expense.payer_id, s.person_id)
        net_balances[key] = net_balances.get(key, 0) + s.amount
        detailed_shares.setdefault(key, []).append(s.id)

    simplified, final_shares = {}, {}
    for (a, b), amount_ab in net_balances.items():
        if (b, a) in simplified:
            continue
        amount_ba = net_balances.get((b, a), 0)
        net = amount_ab - amount_ba
        if net > 0:
            simplified[(a, b)] = net
            final_shares[(a, b)] = detailed_shares.get((a, b), [])
        elif net < 0:
            simplified[(b, a)] = -net
            final_shares[(b, a)] = detailed_shares.get((b, a), [])

    debts, receivables = [], []
    for (alacakli_id, borclu_id), miktar in simplified.items():
        if user_id == borclu_id:
            debts.append({"person_id": alacakli_id, "name": person_map.get(alacakli_id, "Bilinmeyen"), "amount": miktar, "can_pay": True, "share_ids": final_shares.get((alacakli_id, borclu_id), [])})
        elif user_id == alacakli_id:
            receivables.append({"person_id": borclu_id, "name": person_map.get(borclu_id, "Bilinmeyen"), "amount": miktar, "can_pay": False, "share_ids": []})

    return render_template('debts.html', debts=debts, receivables=receivables)

# Borç ödenmiş olarak işaretle
@app.route("/mark_paid/<int:share_id>", methods=["POST"])
@login_required
def mark_paid(share_id):
    share = ExpenseShare.query.get_or_404(share_id)
    if share.person_id != current_user.id:
        flash("Bu borcu işaretleyemezsiniz.")
        return redirect(url_for("debts"))
    share.is_paid = True
    db.session.commit()
    flash("Borç ödendi olarak işaretlendi.")
    return redirect(url_for("debts"))

# Ödeme durumlarını toggle et
@app.route("/toggle_paid/<int:expense_id>")
@login_required
def toggle_paid(expense_id):
    expense = Expense.query.get_or_404(expense_id)
    expense.is_paid = not expense.is_paid
    db.session.commit()
    return redirect("/summary")

@app.route("/toggle_payment/<int:expense_id>", methods=["POST"])
@login_required
def toggle_payment(expense_id):
    expense = Expense.query.get_or_404(expense_id)
    expense.is_paid = not expense.is_paid
    db.session.commit()
    return redirect("/")

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
