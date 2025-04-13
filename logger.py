import os
import logging

logger = None
def get_logger():
    global logger
    if logger is not None:
        return logger
    logger = logging.getLogger("tripo_addon")
    logger.setLevel(logging.INFO)

    # Get the addon's directory path
    addon_dir = os.path.dirname(os.path.realpath(__file__))
    log_file = os.path.join(addon_dir, "tripo_addon.log")

    try:
        # File handler
        fh = logging.FileHandler(log_file)
        fh.setLevel(logging.INFO)

        # Console handler
        ch = logging.StreamHandler()
        ch.setLevel(logging.WARNING)

        # Formatter
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        fh.setFormatter(formatter)
        ch.setFormatter(formatter)

        logger.addHandler(fh)
        logger.addHandler(ch)

    except PermissionError:
        # If we can't create a log file, just use console logging
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        ch.setFormatter(formatter)
        logger.addHandler(ch)
        print("Warning: Could not create log file. Logging to console only.")
    return logger

def close_logger():
    global logger
    if logger is not None:
        logger.handlers.clear()
        logger = None

