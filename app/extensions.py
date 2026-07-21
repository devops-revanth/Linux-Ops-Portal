"""
Flask extension singletons.

Import these from here rather than re-creating them in each module
to avoid circular imports and duplicate instances.
"""
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect

db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()
