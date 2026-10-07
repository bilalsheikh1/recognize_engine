from config.config import Config
from flask import Flask
from extensions import db
from models.user import User

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

with app.app_context():
    db.create_all()   # users table bana dega
    u = User.query.filter_by(username="admin").first() or User(username="admin")
    u.set_password("admin123")
    db.session.add(u)
    db.session.commit()
    print("done")