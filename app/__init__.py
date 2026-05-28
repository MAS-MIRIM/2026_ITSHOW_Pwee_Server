from flask import Flask
from flask_cors import CORS

from config import get_config
from app.models.db import init_db


def create_app() -> Flask:
    app = Flask(__name__)

    app.config.from_object(get_config())

    CORS(app, resources={r"/api/*": {"origins": "*"}})

    init_db(app)

    from app.api.analyze import analyze_bp
    from app.api.solo import solo_bp
    from app.api.leaderboard import leaderboard_bp
    from app.api.admin import admin_bp

    app.register_blueprint(analyze_bp)
    app.register_blueprint(solo_bp)
    app.register_blueprint(leaderboard_bp)
    app.register_blueprint(admin_bp)

    @app.errorhandler(400)
    def bad_request(e):
        from flask import jsonify
        return jsonify({"error": "잘못된 요청입니다."}), 400

    @app.errorhandler(404)
    def not_found(e):
        from flask import jsonify
        return jsonify({"error": "요청한 리소스를 찾을 수 없습니다."}), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        from flask import jsonify
        return jsonify({"error": "허용되지 않는 HTTP 메서드입니다."}), 405

    @app.errorhandler(500)
    def internal_error(e):
        from flask import jsonify
        return jsonify({"error": "서버 내부 오류가 발생했습니다."}), 500

    return app
