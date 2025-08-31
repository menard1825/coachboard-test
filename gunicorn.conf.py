# Gunicorn configuration file
# This file allows you to run the application with `gunicorn --config gunicorn.conf.py run:app`

# Worker Class
# As recommended for Socket.IO, use eventlet. This is crucial for handling websockets.
worker_class = 'eventlet'

# Number of worker processes
# The review suggested 1. For a small application, this is a reasonable starting point.
# You can increase this later based on server resources and load.
workers = 1

# The socket to bind to.
# '0.0.0.0' makes the server accessible from any network interface.
# The port 5002 was used as an example in the review.
bind = '0.0.0.0:5002'

# Logging
# Log to stdout and stderr, which is standard for containerized environments
# and systemd services.
accesslog = '-'
errorlog = '-'
loglevel = 'info'

# Reload
# Set to True for development to automatically reload workers on code changes.
# Should be False in production.
reload = False
