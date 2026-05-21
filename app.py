from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
from flask import Flask, flash, redirect, render_template, request, url_for
from flask_sqlalchemy import SQLAlchemy

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_SQLITE_PATH = BASE_DIR / "data.db"


def build_database_uri() -> str:
    # Vercel production: set DATABASE_URL to Postgres (Neon, Supabase, Railway, etc.)
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)
        return database_url
    return f"sqlite:///{DEFAULT_SQLITE_PATH}"


app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key")
app.config["SQLALCHEMY_DATABASE_URI"] = build_database_uri()
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


class Student(db.Model):
    __tablename__ = "students"

    id = db.Column(db.Integer, primary_key=True)
    exam_number = db.Column(db.String(50), unique=True, nullable=False)
    full_name = db.Column(db.String(255), nullable=False)
    class_name = db.Column(db.String(50), nullable=False)

    scores = db.relationship("Score", back_populates="student", cascade="all, delete-orphan")


class Subject(db.Model):
    __tablename__ = "subjects"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)

    scores = db.relationship("Score", back_populates="subject", cascade="all, delete-orphan")


class Score(db.Model):
    __tablename__ = "scores"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=False)
    score = db.Column(db.Float, nullable=False)

    student = db.relationship("Student", back_populates="scores")
    subject = db.relationship("Subject", back_populates="scores")


REQUIRED_COLUMNS = ["so_bao_danh", "ho_va_ten", "lop"]


@app.get("/")
def index():
    class_options = [row[0] for row in db.session.query(Student.class_name).distinct().order_by(Student.class_name)]
    subject_options = [row[0] for row in db.session.query(Subject.name).distinct().order_by(Subject.name)]

    selected_class = request.args.get("class_name", "")
    selected_subject = request.args.get("subject_name", "")

    query = (
        db.session.query(
            Student.exam_number,
            Student.full_name,
            Student.class_name,
            Subject.name.label("subject_name"),
            Score.score,
        )
        .join(Score, Score.student_id == Student.id)
        .join(Subject, Subject.id == Score.subject_id)
    )

    if selected_class:
        query = query.filter(Student.class_name == selected_class)
    if selected_subject:
        query = query.filter(Subject.name == selected_subject)

    rows = query.order_by(Student.class_name, Student.full_name, Subject.name).all()

    return render_template(
        "index.html",
        class_options=class_options,
        subject_options=subject_options,
        selected_class=selected_class,
        selected_subject=selected_subject,
        rows=rows,
    )


@app.post("/import")
def import_excel():
    excel_file = request.files.get("excel_file")
    if not excel_file or excel_file.filename == "":
        flash("Vui lòng chọn file Excel.", "error")
        return redirect(url_for("index"))

    try:
        df = pd.read_excel(excel_file)
    except Exception:
        flash("Không thể đọc file Excel. Hãy kiểm tra định dạng file.", "error")
        return redirect(url_for("index"))

    columns = [str(c).strip().lower() for c in df.columns]
    df.columns = columns

    missing = [col for col in REQUIRED_COLUMNS if col not in columns]
    if missing:
        flash(
            f"Thiếu cột bắt buộc: {', '.join(missing)}. Cần có: so_bao_danh, ho_va_ten, lop.",
            "error",
        )
        return redirect(url_for("index"))

    subject_cols = [c for c in columns if c not in REQUIRED_COLUMNS]
    if not subject_cols:
        flash("Không tìm thấy cột điểm môn học nào trong file.", "error")
        return redirect(url_for("index"))

    imported_count = 0

    for _, row in df.iterrows():
        exam_number = str(row.get("so_bao_danh", "")).strip()
        full_name = str(row.get("ho_va_ten", "")).strip()
        class_name = str(row.get("lop", "")).strip()

        if not exam_number or not full_name or not class_name:
            continue

        student = Student.query.filter_by(exam_number=exam_number).first()
        if student is None:
            student = Student(exam_number=exam_number, full_name=full_name, class_name=class_name)
            db.session.add(student)
            db.session.flush()
        else:
            student.full_name = full_name
            student.class_name = class_name

        for subject_name in subject_cols:
            value = row.get(subject_name)
            if pd.isna(value):
                continue

            try:
                score_value = float(value)
            except (TypeError, ValueError):
                continue

            subject = Subject.query.filter_by(name=subject_name).first()
            if subject is None:
                subject = Subject(name=subject_name)
                db.session.add(subject)
                db.session.flush()

            existing = Score.query.filter_by(student_id=student.id, subject_id=subject.id).first()
            if existing is None:
                db.session.add(Score(student_id=student.id, subject_id=subject.id, score=score_value))
            else:
                existing.score = score_value

        imported_count += 1

    db.session.commit()
    flash(f"Import thành công {imported_count} học sinh.", "success")
    return redirect(url_for("index"))


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
