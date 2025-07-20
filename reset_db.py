import os
from app import app, db, User, Person  # app'i de import etmelisin

DATABASE_FILE = 'database.db'

def reset_database():
    # Eğer database dosyası varsa sil
    if os.path.exists(DATABASE_FILE):
        os.remove(DATABASE_FILE)
        print(f"{DATABASE_FILE} dosyası silindi.")
    else:
        print(f"{DATABASE_FILE} dosyası bulunamadı, yeni veritabanı oluşturulacak.")

    # Flask app context içinde çalıştır
    with app.app_context():
        db.create_all()
        print("Veritabanı oluşturuldu.")

        # Admin kullanıcısını ekle
        admin_username = "admin"
        admin_password = "Yusuf123."  # Güvenli parola koyabilirsin

        admin_user = User(username=admin_username)
        admin_user.set_password(admin_password)
        db.session.add(admin_user)
        db.session.commit()
        admin_person = Person(name="Admin", user_id=admin_user.id, is_admin=True)
        db.session.add(admin_person)
        db.session.commit()

        print(f"Admin kullanıcı oluşturuldu: kullanıcı adı: '{admin_username}', şifre: '{admin_password}'")

if __name__ == "__main__":
    reset_database()
