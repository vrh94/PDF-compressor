# PDF Compressor — reduce PDF file size using multiple engines.
# Copyright (C) 2026  vrh94
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Flask application factory for the PDF Compressor web interface."""

from __future__ import annotations

import os

from flask import Flask

from pdf_compressor.utils.logging_config import setup_logging
from pdf_compressor.web.routes import blueprint, job_store


def create_app(*, verbose: bool = False) -> Flask:
    """
    Create and configure the Flask application.

    Usage with gunicorn::

        gunicorn "pdf_compressor.web.app:create_app()" --timeout 1800
    """
    setup_logging(verbose=verbose)

    template_dir = os.path.join(os.path.dirname(__file__), "templates")
    app = Flask(__name__, template_folder=template_dir)

    # 2 GB max upload
    app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024
    app.config["JOB_STORE"] = job_store

    app.register_blueprint(blueprint)
    return app


# Module-level WSGI app for gunicorn when called without ()
application = create_app()
