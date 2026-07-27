from flask import Blueprint, render_template, abort
from teile.kern import grant as check_grant

bp  = Blueprint("hilfe_app", __name__)
APP = "hilfe"


@bp.route("/a/hilfe/<token>/")
def index(token):
    user = check_grant(token, APP)
    if not user:
        abort(403)
    return render_template("hilfe.html", user=user, token=token, farbe=user["farbe"])


def init_app(app):
    app.register_blueprint(bp)
