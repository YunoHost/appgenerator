#!/usr/bin/env python3

import hashlib
import importlib
import logging
import os
import random
import re
import string
import tomllib
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path

from flask import (Flask, make_response, redirect, render_template,
                   render_template_string, request, send_file, session)
from flask_babel import Babel
from flask_babel import lazy_gettext as _
from flask_wtf import FlaskForm
from wtforms import (BooleanField, HiddenField, SelectField,
                     SelectMultipleField, StringField, SubmitField,
                     TextAreaField)
from wtforms.validators import URL, DataRequired, Length, Optional, Regexp


def get_version():
    source_location = Path(__file__).parent
    if (pyproject := (source_location / "pyproject.toml")).exists():
        return tomllib.loads(pyproject.read_text())['project']['version']
    else:
        return importlib.metadata.version("package")


__version__ = get_version()
LANGUAGES = {"en": _("English"), "fr": _("French")}

###############################################################################
# App initialization, misc configs
###############################################################################

logger = logging.getLogger()

app = Flask(__name__, static_url_path="/static", static_folder="static")

if app.config.get("DEBUG"):
    app.config["TEMPLATES_AUTO_RELOAD"] = True

app.config["LANGUAGES"] = LANGUAGES
app.config["GENERATOR_VERSION"] = __version__

# This is the secret key used for session signing
app.secret_key = "".join(random.choice(string.ascii_lowercase) for i in range(32))


def get_locale():
    return (
        session.get("lang")
        or request.accept_languages.best_match(LANGUAGES.keys())
        or "en"
    )


babel = Babel(app, locale_selector=get_locale)


@app.context_processor
def jinja_globals():

    d = {
        "locale": get_locale(),
    }

    if app.config.get("DEBUG"):
        d["tailwind_local"] = open("static/tailwind-local.css").read()

    return d


app.jinja_env.globals["is_hidden_field"] = lambda field: isinstance(field, HiddenField)


@app.route("/lang/<lang>")
def set_lang(lang=None):

    assert lang in app.config["LANGUAGES"].keys()
    session["lang"] = lang

    return make_response(redirect(request.referrer or "/"))


###############################################################################
# Forms
###############################################################################


class GeneralInfos(FlaskForm):

    app_id = StringField(
        _("Application identifier (id)"),
        description=_("This is the 'technical' name of the app. Lowercase, no space"),
        validators=[DataRequired(), Regexp(r"[a-z_1-9]+.*(?<!_ynh)$")],
        render_kw={
            "placeholder": "my_awesome_app",
        },
    )

    app_name = StringField(
        _("App name"),
        description=_("It's the application name, displayed in the user interface"),
        validators=[DataRequired()],
        render_kw={
            "placeholder": "My Awesome App",
        },
    )

    description_en = StringField(
        _("Short description (en)"),
        description=_(
            "Explain in a few words (10-15) why this app is useful or what it does (the goal is to give a broad idea for the user browsing an hundred apps long catalog"
        ),
        validators=[DataRequired()],
    )
    description_fr = StringField(
        _("Short description (fr)"),
        description=_(
            "Explain in a few words (10-15) why this app is useful or what it does (the goal is to give a broad idea for the user browsing an hundred apps long catalog"
        ),
    )


class IntegrationInfos(FlaskForm):

    version = StringField(
        _("Version"),
        description=_(
            "Corresponds to the upstream version that will be deployed. Typically this should match the URL of the source that you'll specify in section 5"
        ),
        validators=[Regexp(r"\d{1,4}.\d{1,4}(.\d{1,4})?(.\d{1,4})?")],
        render_kw={"placeholder": "1.0"},
    )

    maintainers = StringField(
        _("Maintainer of the generated app"),
        description=_("Usually you put your name here... If you're okay with it ;)"),
    )

    yunohost_required_version = StringField(
        _("Minimal YunoHost version"),
        description=_("Minimal YunoHost version for the application to work"),
        render_kw={
            "placeholder": "11.1.30",
        },
    )

    architectures = SelectMultipleField(
        _("Supported architectures"),
        choices=[
            ("all", _("All architectures")),
            ("amd64", "amd64"),
            ("i386", "i386"),
            ("armhf", "armhf"),
            ("arm64", "arm64"),
        ],
        default=["all"],
        validators=[DataRequired()],
    )

    multi_instance = BooleanField(
        _(
            "The app can be installed multiple times at the same time on the same server"
        ),
        default=True,
    )

    ldap = SelectField(
        _("The app will be integrating LDAP"),
        description=_(
            "Which means it's possible to use YunoHost credentials to log into this app. LDAP corresponds to the technology used by YunoHost to handle a centralised user base. Bridging the app and YunoHost's LDAP often requires to add the proper technical details in the app's configuration file."
        ),
        choices=[
            ("false", _("No")),
            ("true", _("Yes")),
            ("not_relevant", _("Not relevant")),
        ],
        default="not_relevant",
        validators=[DataRequired()],
    )
    sso = SelectField(
        _("The app will be integrated in YunoHost SSO (Single Sign On)"),
        description=_(
            "Which means that people will be logged in the app after logging in YunoHost's portal, without having to sign on specifically into this app."
        ),
        choices=[
            ("false", _("No")),
            ("true", _("Yes")),
            ("not_relevant", _("Not relevant")),
        ],
        default="false",
        validators=[DataRequired()],
    )


class UpstreamInfos(FlaskForm):

    license = StringField(
        _("Licence"),
        description=_(
            "You should check this on the upstream repository. The expected format is a SPDX id listed in https://spdx.org/licenses/"
        ),
        validators=[DataRequired()],
    )

    website = StringField(
        _("Official website"),
        description=_("Leave empty if there is no official website"),
        validators=[URL(), Optional()],
        render_kw={
            "placeholder": "https://awesome-app-website.com",
        },
    )
    demo = StringField(
        _("Official app demo"),
        description=_("Leave empty if there is no official demo"),
        validators=[URL(), Optional()],
        render_kw={
            "placeholder": "https://awesome-app-website.com/demo",
        },
    )
    admindoc = StringField(
        _("Admin documentation"),
        description=_("Leave empty if there is no official admin doc"),
        validators=[URL(), Optional()],
        render_kw={
            "placeholder": "https://awesome-app-website.com/doc/admin",
        },
    )
    userdoc = StringField(
        _("Usage documentation"),
        description=_("Leave empty if there is no official user doc"),
        validators=[URL(), Optional()],
        render_kw={
            "placeholder": "https://awesome-app-website.com/doc/user",
        },
    )
    code = StringField(
        _("Code repository"),
        validators=[URL(), DataRequired()],
        render_kw={
            "placeholder": "https://some.git.forge/org/app",
        },
    )


class InstallQuestions(FlaskForm):

    domain_and_path = SelectField(
        _("Ask the URL where the app will be installed"),
        description=_(
            "Will correspond to the `$domain` and `$path` variables in scripts, and `__DOMAIN__` and `__PATH__` in configuration templates."
        ),
        default="true",
        choices=[
            ("true", _("Ask domain+path")),
            (
                "full_domain",
                _(
                    "Ask only the domain (the app requires to be installed at the root of a dedicated domain)"
                ),
            ),
            ("false", _("Do not ask (it isn't a webapp)")),
        ],
    )


    init_main_permission = SelectField(
        _("Ask who can access to the app"),
        description=_(
            "In the users groups: by default at least 'visitors', 'all_users' et 'admins' exists."
        ),
        default="visitors",
        choices=[
            ("visitors", "Visitors"),
            ("all_users", "All instance users"),
            ("admins", "Only instance Administrator"),
        ],
    )

    init_admin_permission = BooleanField(
        _("Ask who can access to the admin interface"),
        description=_("In the case where the app has an admin interface"),
        default=False,
    )

# manifest
class Resources(FlaskForm):

    # Sources
    source_url = StringField(
        _("Application source code or executable"),
        validators=[DataRequired(), URL()],
        render_kw={
            "placeholder": "https://github.com/foo/bar/archive/refs/tags/v1.2.3.tar.gz",
        },
    )

    auto_update = SelectField(
        _("Enable automatic update of sources (using a bot running every night)"),
        description=_(
            "If the upstream software is hosted in one of the handled sources and publishes proper releases or tags, the bot will create a pull request to update the sources URL and checksum."
        ),
        default="none",
        choices=[
            ("none", "Non"),
            ("latest_github_tag", "Github (tag)"),
            ("latest_github_release", "Github (release)"),
            ("latest_github_commit", "Github (commit)"),
            ("latest_gitlab_tag", "Gitlab (tag)"),
            ("latest_gitlab_release", "Gitlab (release)"),
            ("latest_gitlab_commit", "Gitlab (commit)"),
            ("latest_gitea_tag", "Gitea (tag)"),
            ("latest_gitea_release", "Gitea (release)"),
            ("latest_gitea_commit", "Gitea (commit)"),
            ("latest_forgejo_tag", "Forgejo (tag)"),
            ("latest_forgejo_release", "Forgejo (release)"),
            ("latest_forgejo_commit", "Forgejo (commit)"),
        ],
    )

    apt_dependencies = StringField(
        _("Dependencies to be installed via apt"),
        description=_("Separated by comma and/or spaces"),
        render_kw={
            "placeholder": "foo, bar2.1-ext, libwat",
        },
    )

    database = SelectField(
        _("Initialize an SQL database"),
        choices=[
            ("false", "Non"),
            ("mysql", "MySQL/MariaDB"),
            ("postgresql", "PostgreSQL"),
        ],
        default="false",
    )

    system_user = BooleanField(
        _("Initialize a system user for this app"),
        default=True,
    )

    install_dir = BooleanField(
        _("Initialize an installation folder for this app"),
        description=_("By default it's /var/www/$app"),
        default=True,
    )

    data_dir = BooleanField(
        _("Initialize a folder to store the app data"),
        description=_("By default it's /var/yunohost.app/$app"),
        default=False,
    )


class SpecificTechnology(FlaskForm):

    main_technology = SelectField(
        _("App main technology"),
        choices=[
            ("none", _("None / Static application")),
            ("php", "PHP"),
            ("nodejs", "NodeJS"),
            ("python", "Python"),
            ("ruby", "Ruby"),
            ("go", "Go"),
            ("other", _("Other")),
        ],
        default="none",
        validators=[DataRequired()],
    )

    install_snippet = TextAreaField(
        _("Installation specific commands"),
        description=_(
            "These commands are executed from the app installation folder (by default, /var/www/$app) after the sources have been deployed. This field uses by default a classic example based on the selected technology. You should probably compare and adapt it according to the app installation documentation."
        ),
        validators=[Optional()],
        render_kw={"spellcheck": "false"},
    )

    #
    # PHP
    #

    use_composer = BooleanField(
        _("Use composer"),
        description=_("Composer is a PHP dependencies manager used by some apps"),
        default=False,
    )

    #
    # NodeJS
    #

    nodejs_version = StringField(
        _("NodeJS version"),
        description=_("For example: 16.4, 18, 18.2, 20, 20.1..."),
        render_kw={
            "placeholder": "20",
        },
    )

    #
    # Go
    #

    go_version = StringField(
        _("Go version"),
        description=_("For example: 1.20, 1.21, 1.22, 1.23..."),
        render_kw={
            "placeholder": "1.22",
        },
    )

    use_yarn = BooleanField(
        _("Install and use Yarn"),
        default=False,
    )

    # NodeJS/Python/Ruby...

    systemd_execstart = StringField(
        _("Command to start the app daemon (from systemd service)"),
        description=_(
            "Corresponds to 'ExecStart' statement in systemd. You can use '__INSTALL_DIR__' to refer to the install directory, or '__APP__' to refer to the app id"
        ),
        render_kw={
            "placeholder": "__INSTALL_DIR__/bin/app --some-option",
        },
    )


class AppConfig(FlaskForm):

    use_custom_config_file = BooleanField(
        _("Add a specific configuration file for the app"),
        description=_("Typically: .env, config.json, conf.ini, params.yml..."),
        default=False,
    )

    custom_config_file = StringField(
        _("App config filename"),
        validators=[Optional()],
        render_kw={
            "placeholder": "config.json",
        },
    )

    custom_config_file_content = TextAreaField(
        _("App config content"),
        description=_(
            "In this field, you can use the syntax __FOO_BAR__ which will automatically replaced by the value of the variable $foo_bar"
        ),
        validators=[Optional()],
        render_kw={"spellcheck": "false", "rows": "10"},
    )


class Documentation(FlaskForm):
    # TODO :    # screenshot
    description = TextAreaField(
        _("Comprehensive presentation"),
        description=_(
            "Corresponds to 'doc/DESCRIPTION.md' and you can use markdown in there. Typically you should list the main features, possible warnings and specific details on its functioning in YunoHost (e.g. warning about integration issues)."
        ),
        validators=[DataRequired()],
        render_kw={
            "spellcheck": "false",
            "rows": "10",
        },
    )
    pre_install = TextAreaField(
        _("Important info to be shown to the admin before installation"),
        description=_("Corresponds to 'doc/PRE_INSTALL.md'")
        + " "
        + _("Leave empty if not relevant"),
        validators=[Optional()],
        render_kw={
            "spellcheck": "false",
        },
    )
    post_install = TextAreaField(
        _("Important info to be shown to the admin after installation"),
        description=_("Corresponds to 'doc/POST_INSTALL.md'")
        + " "
        + _("Leave empty if not relevant"),
        validators=[Optional()],
        render_kw={
            "spellcheck": "false",
        },
    )
    pre_upgrade = TextAreaField(
        _("Important info to be shown to the admin before upgrade"),
        description=_("Corresponds to 'doc/PRE_UPGRADE.md'")
        + " "
        + _("Leave empty if not relevant"),
        validators=[Optional()],
        render_kw={
            "spellcheck": "false",
        },
    )
    post_upgrade = TextAreaField(
        _("Important info to be shown to the admin after upgrade"),
        description=_("Corresponds to 'doc/POST_UPGRADE.md'")
        + " "
        + _("Leave empty if not relevant"),
        validators=[Optional()],
        render_kw={
            "spellcheck": "false",
        },
    )
    admin = TextAreaField(
        _("General tips on how to administrate this app"),
        description=_("Corresponds to 'doc/ADMIN.md'.")
        + " "
        + _("Leave empty if not relevant"),
        validators=[Optional()],
        render_kw={
            "spellcheck": "false",
        },
    )


class MoreAdvanced(FlaskForm):

    enable_change_url = BooleanField(
        _("Support URL change"),
        description=_(
            "Corresponds to the `change_url` script, allowing to change the domain/path where the app is exposed after installation"
        ),
        default=True,
    )

    use_logrotate = BooleanField(
        _("Use logrotate for the logs"),
        default=True,
    )
    # TODO : specify custom log file
    # custom_log_file = "/var/log/$app/$app.log" "/var/log/nginx/${domain}-error.log"

    use_fail2ban = BooleanField(
        _("Protect against brute force attacks"),
        default=False,
        description=_(
            "Use fail2ban, assuming the app logs failed connection attempts, this option allows to automatically ban suspicious IP after a number of failed attempts."
        ),
    )
    use_cron = BooleanField(
        _("Configure a CRON task"),
        description=_("Corresponds to some app periodic operations"),
        default=False,
    )
    cron_config_file = TextAreaField(
        _("CRON file content"),
        validators=[Optional()],
        render_kw={
            "class": "form-control",
            "spellcheck": "false",
        },
    )

    fail2ban_regex = StringField(
        _("Regular expression for Fail2Ban"),
        # Regex to match into the log for a failed login
        description=_(
            "Regular expression to check in the log file to activate FailBan (search for a line that indicates a credentials error)."
        ),
        validators=[Optional()],
        render_kw={
            "placeholder": _("A regular expression"),
            "class": "form-control",
        },
    )


## Main form
class GeneratorForm(
    GeneralInfos,
    IntegrationInfos,
    UpstreamInfos,
    InstallQuestions,
    Resources,
    SpecificTechnology,
    AppConfig,
    Documentation,
    MoreAdvanced,
):

    class Meta:
        csrf = False

    generator_mode = SelectField(
        _("Generator mode"),
        description=_(
            "In tutorial version, the generated app will contain additionnal comments to ease the understanding. In steamlined version, the generated app will only contain the necessary minimum."
        ),
        choices=[
            ("simple", _("Streamlined version")),
            ("tutorial", _("Tutorial version")),
        ],
        default="true",
        validators=[DataRequired()],
    )

    submit_preview = SubmitField(_("Previsualise"))
    submit_download = SubmitField(_("Download the .zip"))
    submit_demo = SubmitField(
        _("Fill with demo values"),
        render_kw={
            "onclick": "fillFormWithDefaultValues()",
            "title": _(
                "Generate a complete and functionnal minimalistic app that you can iterate from"
            ),
        },
    )


# SHA256 sum calculator
def get_remote_sha256_sum(url):
    remote = urllib.request.urlopen(url)
    hash = hashlib.sha256()
    while True:
        data = remote.read(4096)
        if not data:
            break
        hash.update(data)
    return hash.hexdigest()


#### Web pages
@app.route("/", methods=["GET", "POST"])
def main_form_route():

    main_form = GeneratorForm()
    app_files = []

    if request.method == "POST":

        if not main_form.validate_on_submit():
            logging.error("Form not validated?")
            logging.error(main_form.errors)

            return render_template(
                "index.html",
                main_form=main_form,
                generated_files={},
            )

        if main_form.submit_preview.data:
            submit_mode = "preview"
        elif main_form.submit_demo.data:
            submit_mode = "demo"  # TODO : for now this always trigger a preview. Not sure if that's an issue
        else:
            submit_mode = "download"

        class AppFile:
            def __init__(self, id_, destination_path=None):
                self.id = id_
                self.destination_path = destination_path
                self.content = None

        app_files = [
            AppFile("manifest", "manifest.toml"),
            AppFile("tests", "tests.toml"),  # TODO test this
            AppFile("_common.sh", "scripts/_common.sh"),
            AppFile("install", "scripts/install"),
            AppFile("remove", "scripts/remove"),
            AppFile("backup", "scripts/backup"),
            AppFile("restore", "scripts/restore"),
            AppFile("upgrade", "scripts/upgrade"),
            AppFile("nginx", "conf/nginx.conf"),
            AppFile("LICENSE", "LICENSE"),
        ]

        if main_form.enable_change_url.data:
            app_files.append(AppFile("change_url", "scripts/change_url"))

        if main_form.main_technology.data not in ["none", "php"]:
            app_files.append(AppFile("systemd", "conf/systemd.service"))

        # TODO : buggy, tries to open php.j2
        # if main_form.main_technology.data == "php":
        # app_files.append(AppFile("php", "conf/extra_php-fpm.conf"))

        if main_form.description.data:
            app_files.append(AppFile("DESCRIPTION", "doc/DESCRIPTION.md"))

        if main_form.pre_install.data:
            app_files.append(AppFile("PRE_INSTALL", "doc/PRE_INSTALL.md"))

        if main_form.post_install.data:
            app_files.append(AppFile("POST_INSTALL", "doc/POST_INSTALL.md"))

        if main_form.pre_upgrade.data:
            app_files.append(AppFile("PRE_UPGRADE", "doc/PRE_UPGRADE.md"))

        if main_form.post_upgrade.data:
            app_files.append(AppFile("POST_UPGRADE", "doc/POST_UPGRADE.md"))

        if main_form.admin.data:
            app_files.append(AppFile("ADMIN", "doc/ADMIN.md"))

        template_dir = os.path.dirname(__file__) + "/templates/"

        data = dict(request.form)
        data["sha256sum"] = get_remote_sha256_sum(main_form.source_url.data)

        for app_file in app_files:
            template = open(template_dir + app_file.id + ".j2").read()
            app_file.content = render_template_string(template, data=data)
            app_file.content = re.sub(r"\n\s+$", "\n", app_file.content, flags=re.M)
            app_file.content = re.sub(r"\n{3,}", "\n\n", app_file.content, flags=re.M)

        if main_form.use_custom_config_file.data:
            app_files.append(
                AppFile("appconf", "conf/" + main_form.custom_config_file.data)
            )
            app_files[-1].content = main_form.custom_config_file_content.data

        if submit_mode == "download":
            # Generate the zip file
            f = BytesIO()
            with zipfile.ZipFile(f, "w") as zf:
                for app_file in app_files:
                    zf.writestr(app_file.destination_path, app_file.content)
            f.seek(0)
            # Send the zip file to the user
            return send_file(
                f, as_attachment=True, download_name=request.form["app_id"] + "_ynh.zip"
            )

    return render_template(
        "index.html",
        main_form=main_form,
        generated_files=app_files,
    )


#### Running the web server
if __name__ == "__main__":
    app.run(debug=True)
