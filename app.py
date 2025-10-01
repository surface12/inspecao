
import os
import uuid
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}  # (se tiver iPhone com HEIC, posso te mostrar como converter)

app = Flask(__name__, instance_relative_config=True)
app.config["SECRET_KEY"] = "troque-esta-chave"
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{(BASE_DIR / 'instance' / 'app.db')}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024  # 30 MB por requisição (ajuste se quiser)
app.config["UPLOAD_FOLDER"] = str(UPLOAD_DIR)

# garante pasta instance/
(Path(app.instance_path)).mkdir(parents=True, exist_ok=True)

db = SQLAlchemy(app)

class Equipment(db.Model):
    __tablename__ = "equipments"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(120), nullable=False)        # ex: TR-018 ou patrimônio
    location = db.Column(db.String(255), nullable=True)     # ex: Setor/linha/fábrica
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    photos = db.relationship("Photo", backref="equipment", cascade="all, delete-orphan")

class Photo(db.Model):
    __tablename__ = "photos"
    id = db.Column(db.Integer, primary_key=True)
    equipment_id = db.Column(db.Integer, db.ForeignKey("equipments.id"), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)   # caminho relativo em uploads/
    original_name = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

with app.app_context():
    db.create_all()

def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route("/")
def form():
    return render_template("form.html")

@app.route("/upload", methods=["POST"])
def upload():
    code = request.form.get("equipamento", "").strip()
    location = request.form.get("local", "").strip()
    notes = request.form.get("observacoes", "").strip()
    files = request.files.getlist("fotos")

    if not code:
        flash("Informe o código/nome do equipamento.", "error")
        return redirect(url_for("form"))
    if not files or len(files) == 0:
        flash("Envie pelo menos uma foto.", "error")
        return redirect(url_for("form"))

    # cria/recupera registro do equipamento (um registro por envio)
    eq = Equipment(code=code, location=location, notes=notes)
    db.session.add(eq)
    db.session.flush()  # garante eq.id antes do commit

    # pasta com estrutura: uploads/<codigo-sanitizado>/<YYYY-MM-DD>
    safe_code = secure_filename(code)
    date_dir = datetime.utcnow().strftime("%Y-%m-%d")
    target_dir = UPLOAD_DIR / safe_code / date_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    saved_any = False
    for f in files:
        if not f or f.filename == "":
            continue
        if not allowed_file(f.filename):
            flash(f"Arquivo não permitido: {f.filename}", "error")
            continue

        ext = f.filename.rsplit(".", 1)[1].lower()
        new_name = f"{uuid.uuid4().hex}.{ext}"
        final_path = target_dir / new_name
        f.save(final_path)

        photo_rel_path = str(final_path.relative_to(UPLOAD_DIR))
        p = Photo(
            equipment_id=eq.id,
            file_path=photo_rel_path.replace("\\", "/"),
            original_name=f.filename
        )
        db.session.add(p)
        saved_any = True

    if not saved_any:
        db.session.rollback()
        flash("Nenhuma foto válida foi enviada.", "error")
        return redirect(url_for("form"))

    db.session.commit()
    flash("Upload realizado com sucesso!", "success")
    return redirect(url_for("detail_equipment", equipment_id=eq.id))

@app.route("/equipamentos")
def list_equipments():
    q = Equipment.query.order_by(Equipment.created_at.desc()).all()
    return render_template("list.html", items=q)

@app.route("/equipamento/<int:equipment_id>")
def detail_equipment(equipment_id):
    eq = Equipment.query.get_or_404(equipment_id)
    return render_template("detail.html", eq=eq)

# servir os arquivos enviados
@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename, as_attachment=False)

if __name__ == "__main__":
    # Rode com: python app.py
    app.run(host="0.0.0.0", port=5000, debug=True)
