from flask import Blueprint, render_template
from teile.kern import get_db

bp = Blueprint("start", __name__)


@bp.route("/")
def index():
    """Landing ohne Token – freundliche Erklärung."""
    return render_template("denied.html", reason="landing"), 200


@bp.route("/p/<token>")
def startseite(token):
    db = get_db()

    # Token muss für die 'home'-App ausgestellt sein
    row = db.execute("""
        SELECT u.id, u.name, u.farbe, u.is_admin, u.dark_mode
        FROM   grants g
        JOIN   users u ON u.id = g.user_id
        JOIN   apps  a ON a.id = g.app_id
        WHERE  g.token = ? AND a.slug = 'home'
    """, (token,)).fetchone()

    if not row:
        return render_template("denied.html", reason="invalid"), 403

    # Alle Apps außer 'home' auflisten
    apps = db.execute("""
        SELECT a.slug, a.name, a.emoji, g.token AS app_token
        FROM   grants g
        JOIN   apps   a ON a.id = g.app_id
        WHERE  g.user_id = ? AND a.slug != 'home'
        ORDER  BY a.id
    """, (row["id"],)).fetchall()

    return render_template(
        "startseite.html",
        user=row,
        apps=apps,
        token=token,
        farbe=row["farbe"],
        greeting="Hallo",  # JS überschreibt mit tageszeit-abhängigem Gruß
    )


def init_app(app):
    app.register_blueprint(bp)
