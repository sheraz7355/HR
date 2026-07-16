from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from shared.extensions import db
from shared.models.base import User, Role, UserPermission
from shared.permissions import MODULES, ACTIONS

admin_settings_bp = Blueprint("admin_settings", __name__, url_prefix="/settings")


def _require_admin():
    if not current_user.is_admin():
        flash("Only administrators can manage access rights.", "error")
        return False
    return True


@admin_settings_bp.route("/")
@login_required
def users():
    if not _require_admin():
        return redirect(url_for("dashboard.hub"))
    all_users = User.query.order_by(User.full_name).all()
    configured = {uid for (uid,) in db.session.query(UserPermission.user_id).distinct()}
    return render_template("admin_settings/users.html",
                           users=all_users, modules=MODULES, configured=configured)


@admin_settings_bp.route("/users/<int:uid>/rights", methods=["GET", "POST"])
@login_required
def user_rights(uid):
    if not _require_admin():
        return redirect(url_for("dashboard.hub"))
    u = User.query.get_or_404(uid)

    if request.method == "POST":
        # Optional password reset — admin must type the new password twice.
        new_pw = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        if new_pw or confirm:
            if len(new_pw) < 4:
                flash("Password must be at least 4 characters.", "error")
                return redirect(url_for("admin_settings.user_rights", uid=uid))
            if new_pw != confirm:
                flash("Passwords do not match — enter the new password twice.", "error")
                return redirect(url_for("admin_settings.user_rights", uid=uid))
            u.set_password(new_pw)

        # Module access flags
        for module_key, _label, flag_attr, _sections in MODULES:
            setattr(u, flag_attr, request.form.get(f"module_{module_key}") == "on")

        # Section rights: rewrite this user's rows from the submitted grid so
        # the stored state always matches exactly what admin sees on screen.
        UserPermission.query.filter_by(user_id=u.id).delete()
        for _module_key, _label, _flag, sections in MODULES:
            for resource, _res_label in sections:
                db.session.add(UserPermission(
                    user_id=u.id, resource=resource,
                    **{f"can_{a}": request.form.get(f"perm_{resource}_{a}") == "on"
                       for a in ACTIONS}
                ))
        db.session.commit()
        flash(f"Access rights saved for {u.full_name}.", "success")
        return redirect(url_for("admin_settings.users"))

    perms = {p.resource: p for p in UserPermission.query.filter_by(user_id=u.id).all()}
    is_configured = bool(perms)
    return render_template("admin_settings/user_rights.html",
                           u=u, modules=MODULES, actions=ACTIONS,
                           perms=perms, is_configured=is_configured)


@admin_settings_bp.route("/account", methods=["GET", "POST"])
@login_required
def account():
    """Admin's own credentials (email/password) — changeable only here."""
    if not _require_admin():
        return redirect(url_for("dashboard.hub"))
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        login_id = request.form.get("login_id", "").strip()
        new_pw = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        if full_name:
            current_user.full_name = full_name
        if email and email != current_user.email:
            if User.query.filter(User.email == email, User.id != current_user.id).first():
                flash("That email is already in use.", "error")
                return redirect(url_for("admin_settings.account"))
            current_user.email = email
        if login_id and login_id != current_user.login_id:
            if User.query.filter(db.func.lower(User.login_id) == login_id.lower(),
                                 User.id != current_user.id).first():
                flash("That User ID is already taken.", "error")
                return redirect(url_for("admin_settings.account"))
            current_user.login_id = login_id
        if new_pw or confirm:
            if len(new_pw) < 4:
                flash("Password must be at least 4 characters.", "error")
                return redirect(url_for("admin_settings.account"))
            if new_pw != confirm:
                flash("Passwords do not match — enter the new password twice.", "error")
                return redirect(url_for("admin_settings.account"))
            current_user.set_password(new_pw)
        db.session.commit()
        flash("Admin account updated.", "success")
        return redirect(url_for("admin_settings.users"))
    return render_template("admin_settings/account.html")


@admin_settings_bp.route("/users/<int:uid>/reset-rights", methods=["POST"])
@login_required
def reset_rights(uid):
    if not _require_admin():
        return redirect(url_for("dashboard.hub"))
    u = User.query.get_or_404(uid)
    UserPermission.query.filter_by(user_id=u.id).delete()
    db.session.commit()
    flash(f"Rights reset for {u.full_name} — user has unrestricted section access again.", "success")
    return redirect(url_for("admin_settings.users"))
