from flask import current_app
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from service.base import BaseAuthService
from service.response import success, failure
from models.user import User

TOKEN_MAX_AGE = 60 * 60 * 8
_revoked_tokens = set()

class AuthService(BaseAuthService):

    def _serializer(self):
        return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])

    def login(self, username, password):
        if not username or not password:
            return failure("Username and password are required.", status_code=400)

        user = User.query.filter_by(username=username).first()
        if not user or not user.check_password(password):
            return failure("Authentication failed. Please verify credentials.", status_code=401)

        token = self._serializer().dumps({"id": user.id})
        return success("Login successful.", {
            "token": token,
            "user": {"id": user.id, "username": user.username, "role": "Admin"},
        })

    def logout(self, token):
        if not token:
            return failure("Token missing.", status_code=400)
        _revoked_tokens.add(token)
        return success("Logged out.")

    def me(self, token):
        if not token or token in _revoked_tokens:
            return failure("Unauthorized.", status_code=401)
        try:
            payload = self._serializer().loads(token, max_age=TOKEN_MAX_AGE)
        except (BadSignature, SignatureExpired):
            return failure("Unauthorized.", status_code=401)
        user = User.query.get(payload["id"])
        if not user:
            return failure("Unauthorized.", status_code=401)
        return success("OK", {"user": {"id": user.id, "username": user.username, "role": "Admin"}})