import logging

# -----------------------------------------------------------------------------
# Logging configuration for the penetration testing agent.
#
# - Sets the logging level to INFO
# - Defines a consistent format including timestamp, log level, and message
# - Logs are sent both to a file ('pentest.log') and the console (stdout)
# - Logger instance 'pentest-agent' is used throughout the application
# -----------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler("pentest.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("pentest-agent")
