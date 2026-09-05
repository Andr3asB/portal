from flask import Blueprint, abort, render_template

from teile.kern import grant as check_grant
from teile.kern import ki_modell_uebersicht

bp  = Blueprint("hilfe_app", __name__)
APP = "hilfe"


@bp.route("/a/hilfe/", defaults={"token": None})
@bp.route("/a/hilfe/<token>/")
def index(token):
    user = check_grant(token, APP)
    if not user:
        abort(403)
    # Wunsch #259: Das Kapitel "KI-Modelle" zeigt den Live-Stand aus der
    # Datenbank, keine abgetippte Liste.
    return render_template("hilfe.html", user=user, token=token, farbe=user["farbe"],
                           ki=ki_modell_uebersicht())


def init_app(app):
    app.register_blueprint(bp)
