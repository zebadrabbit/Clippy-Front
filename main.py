#        _ _
#    ___| (_)_ __  _ __  _   _
#   / __| | | '_ \| '_ \| | | |
#  | (__| | | |_) | |_) | |_| |
#   \___|_|_| .__/| .__/ \__, |
#           |_|   |_|    |___/
#
#  Clippy: Self-hosted Video Generation and Editing Service
#
#  github.com/zebadrabbit/Clippy-Front

"""
Main entry point for the Flask application.
"""
from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host=app.config["HOST"], port=app.config["PORT"], debug=app.config["DEBUG"])
