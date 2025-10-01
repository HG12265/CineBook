#!/bin/bash

# This line tells the script to exit immediately if a command fails.
set -e

echo "Running Flask DB Upgrade..."
# This command will create all the database tables based on your models.
# It safely runs db.create_all() and the init_db() seeder function.
flask shell <<EOF
from app import db, init_db
db.create_all()
init_db()
exit()
EOF

echo "Starting Gunicorn..."
# This command starts the web server. It will only run if the command above succeeds.
exec gunicorn app:app