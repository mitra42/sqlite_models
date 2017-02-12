# encoding: utf-8
#TODO - overhaul logging, understand and make apache like and useful logs

# This gets loaded into a Dict-like object "settings" where you can find things like settings.GSM_HOST

## LOGGING: Dict for logging configuration
LOGGING = {
    "version": 1,
    "loggers": {
        "mylogger1": {
            "level": "DEBUG",
            "handlers": ["logFileHandler"],
        },
        "mylogger2": {
            "handlers": ["accessLogHandler"],
        },
    },
    "root": {
        "level": "INFO",
        "handlers": ["combinedHandler"],
    },
    "handlers": {
        "combinedHandler": {
            "level": "DEBUG",
            "class": "logging.handlers.TimedRotatingFileHandler",
            "formatter": "with_thread",
            ## Note that log file location for logFileHandler can be overridden
            ## using the environment variable APP_LOG_FILE
            ## This allows for example setting it when starting the application
            ## using the DEMO flag (to "../log/lumeter_demo.log")
            ## See also cherryserver.py
            ## The name cherryserver.log is maintained for histoical reasons
            "filename": environ.get("APP_LOG_FILE", "./log/combined.log"),
            ## Rotate the file every sunday
            "when": 'W6',
        },
        "testLogFileHandler": {
            "level": "INFO",
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "with_thread",
            "filename": "test.log",
            "maxBytes": 1000000,
        },
        "testConsoleHandler": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "with_thread",
            #"filters": [allow_foo],
            "stream": "ext://sys.stdout",
        },
        "testEmailHandler": {
            "level": "INFO",
            "class": "logging.handlers.SMTPHandler",
            "mailhost": "localhost",
            "fromaddr": "noone@mitra.biz",
            "toaddrs": "mitra@mitra.biz",
            "subject": "Email log test"
        },
        "accessLogHandler": {
            ## For Apache log format, for web log analysers
            "level": "INFO",
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "apacheLogFormatter",
            "filename": "./log/access.log",
            "maxBytes": 1000000,
            "backupCount": 5,
        }
    },
   "formatters": {
       "apacheLogFormatter": {
           ## The whole message is already formatted to Apache combined log format
           "format": "%(message)s",
           #"datefmt": "%m-%d %H:%M",
       },
        "standard": {
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            #"datefmt": "%m-%d %H:%M",
        },
        "with_thread": {
            "format": "%(asctime)s - %(name)s.%(thread)s - %(levelname)s - %(message)s",
        }
    }
}
