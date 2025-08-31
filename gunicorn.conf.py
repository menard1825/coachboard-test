# gunicorn.conf.py
# Simple and reliable configuration for your application

# As recommended for Socket.IO, use eventlet for websockets.
worker_class = 'eventlet'
workers = 1

# Bind to your specified testing port
bind = '0.0.0.0:5005'

# Standard logging
accesslog = '-'
errorlog = '-'
loglevel = 'info'
